#!/usr/bin/env bash
# JBHNTR Team runner. Modes: chat (real-time Founder replies) | cycle | morning.
# Canonical copy (R3-34). The runtime's run_cycle.sh is ops/team/run_wrapper.sh, which runs the COMMITTED version of this file.
# Boardroom calls go through ops/team/bridge.py (R3-35); agent prompts are ops/team/prompts/<mode>.md (R3-37), both read from HEAD.
# The runner owns git sync: fetch -> rebase -> else merge -> else park local commits on origin/conflict/<mode>-<sha>.
# It never force-pushes and never drops a commit.
# Locks (R3-36): cycle/morning hold $TEAM/run.lock in the main clone; chat holds $TEAM/chat.lock in its own clone
# (JBHNTR_CHAT_REPO, default $TEAM/chat-wt, cloned on first use) and only probes run.lock to set CYCLE_RUNNING.
# Tests: RUN_CYCLE_LIB=1 sources the functions without running main; JBHNTR_TEAM / CLAUDE_BIN / JBHNTR_BRANCH override paths.
set -uo pipefail
MODE="${1:-cycle}"
TEAM="${JBHNTR_TEAM:-$HOME/.jbhntr-team}"
set -a; . "$TEAM/env"; set +a
unset JBHNTR_ADMIN_TOKEN   # only bridge.py needs it, and it reads the env file itself: keep it out of the agent's env
REPO="${JBHNTR_REPO:-$HOME/jbhntr}"
CHAT_REPO="${JBHNTR_CHAT_REPO:-$TEAM/chat-wt}"
BRANCH="${JBHNTR_BRANCH:-main}"
CLAUDE="${CLAUDE_BIN:-claude}"
LOG="$TEAM/cycle.log"
export CHAT_FILE="${CHAT_FILE:-$TEAM/chat.json}"
export PATH="$HOME/.local/bin:$PATH"

log() { echo "$(date -Is) [$MODE] $*" >>"$LOG"; }
ahead() { git rev-list --count "origin/$BRANCH..HEAD" 2>/dev/null || echo 0; }
# A repo file as committed at HEAD (like the wrapper, so a cycle's working-tree edits never change this run);
# missing from HEAD -> the last good copy kept in $TEAM/good/.
committed() {
  local s good="$TEAM/good/${1//\//_}"
  s="$(git -C "$REPO" show "HEAD:$1" 2>/dev/null)"
  if [ -n "$s" ]; then
    mkdir -p "$TEAM/good"; printf '%s\n' "$s" | cmp -s - "$good" || printf '%s\n' "$s" > "$good"
    printf '%s\n' "$s"
  else log "HEAD:$1 missing; using last good copy"; cat "$good" 2>/dev/null; fi
}
# Boardroom client (token + URL read from $TEAM/env by bridge.py itself; never argv).
bridge() { python3 <(committed ops/team/bridge.py) "$@"; }
post_reply() { printf '%s' "$1" | bridge reply >/dev/null 2>>"$LOG"; }

# Reply = everything after the last 'BOARDROOM:' line. Fallback (no marker): chat -> whole output, else last non-blank line.
boardroom_reply() {
  local r
  r="$(printf '%s\n' "$1" | awk '/^BOARDROOM:/{r=$0; sub(/^BOARDROOM:[[:space:]]*/,"",r); on=1; next} on{r=r "\n" $0} END{printf "%s", r}' \
       | sed '/^[[:space:]]*$/d')"
  if [ -z "$r" ]; then
    if [ "$MODE" = chat ]; then r="$(printf '%s\n' "$1" | sed '/^[[:space:]]*$/d')"
    else r="$(printf '%s\n' "$1" | grep -v '^[[:space:]]*$' | tail -1)"; fi
  fi
  printf '%s' "$r"
}

# True conflict: push local commits to a NEW branch conflict/<mode>-<sha> (the next cycle merges it), then follow origin.
park() {
  local b="conflict/$MODE-$(git rev-parse --short HEAD)"
  git push -q origin "HEAD:refs/heads/$b" || { log "CONFLICT with origin/$BRANCH; could not push $b, commits kept locally"; return 1; }
  log "CONFLICT with origin/$BRANCH: local commits parked on $b"
  git reset -q --keep "origin/$BRANCH" || log "reset --keep refused (local edits); tree stays diverged"
  post_reply "Heads-up: this $MODE run's work is saved on branch $b and is NOT on $BRANCH yet (a newer commit changed the same lines). Nothing is lost: the next cycle merges it first."
}

# Follow origin/$BRANCH and publish local commits: rebase (linear) -> merge -> park.
sync() {
  local i
  git rebase --abort >/dev/null 2>&1; git merge --abort >/dev/null 2>&1   # leftovers of a killed run
  for i in 1 2 3; do
    git fetch -q --prune origin || { log "fetch failed ($i)"; sleep 2; continue; }
    # rebase would flatten merge commits (a merged conflict branch would then not count as merged): skip it when HEAD
    # already contains origin, and merge instead when local history has merges.
    if git merge-base --is-ancestor "origin/$BRANCH" HEAD 2>/dev/null; then :
    elif [ "$(git rev-list --merges --count "origin/$BRANCH..HEAD")" -gt 0 ] || ! git rebase -q --autostash "origin/$BRANCH" >/dev/null 2>&1; then
      git rebase --abort >/dev/null 2>&1
      if ! git merge -q --no-edit --autostash "origin/$BRANCH" >/dev/null 2>&1; then
        git merge --abort >/dev/null 2>&1
        park; return
      fi
    fi
    [ "$(ahead)" -gt 0 ] || return 0
    git push -q origin "HEAD:$BRANCH" && { log pushed; return 0; }
    log "push failed ($i)"; sleep 2
  done
  return 1
}

# Delete remote conflict/* branches whose tip is already on origin/$BRANCH (merged cleanly or by hand by the cycle).
prune_parked() {
  local b
  for b in $(git branch -r --merged "origin/$BRANCH" --format='%(refname:short)' | grep '^origin/conflict/'); do
    git push -q origin --delete "${b#origin/}" && log "deleted merged $b"
  done
}

# Before the agent (cycle/morning): merge every clean origin/conflict/*; still-conflicting ones go to the agent in PARKED_BRANCHES.
merge_parked() {
  local b
  PARKED_BRANCHES=""
  for b in $(git branch -r --no-merged HEAD --format='%(refname:short)' | grep '^origin/conflict/'); do
    if git merge -q --no-edit "$b" >/dev/null 2>&1; then
      log "merged parked $b"
    else
      git merge --abort >/dev/null 2>&1
      PARKED_BRANCHES="${PARKED_BRANCHES:+$PARKED_BRANCHES }$b"
      log "parked $b conflicts with $BRANCH; left for the agent to merge"
    fi
  done
  [ "$(ahead)" -gt 0 ] && sync
  prune_parked
  export PARKED_BRANCHES
}

# Prompt = committed ops/team/prompts/<mode>.md + the run's facts (no templating in the files).
build_prompt() {
  local p
  p="$(committed "ops/team/prompts/$MODE.md")"
  [ -n "$p" ] || return 1
  printf '%s\n\n## Runtime context\n- Working dir: %s\n- Branch: %s\n- Date: %s\n- PARKED_BRANCHES: %s\n- CYCLE_RUNNING: %s\n' \
    "$p" "$REPO" "$BRANCH" "$(date +%F)" "${PARKED_BRANCHES:-none}" "${CYCLE_RUNNING:-0}"
  [ "$MODE" = chat ] && printf -- '- CHAT_FILE: %s\n- Founder message(s) (JSON):\n%s\n' "$CHAT_FILE" "$INBOX"
  return 0
}

main() {
  local T N INBOX="" PROMPT OUT RC REPLY
  case "$MODE" in cycle) T=3h ;; morning) T=1h ;; chat) T=20m ;; *) echo "usage: $0 cycle|morning|chat" >&2; exit 2 ;; esac

  # Chat mode: cheap guard — if no Founder message is waiting, don't even start Claude.
  if [ "$MODE" = chat ]; then
    N="$(bridge peek 2>>"$LOG")"
    { [ "${N:-0}" -eq 0 ]; } 2>/dev/null && exit 0
  fi

  local MAIN="$REPO"
  if [ "$MODE" = chat ]; then
    exec 9>"$TEAM/chat.lock"
    flock -n 9 || { log "busy, skip"; exit 0; }
    # Probe, never hold: a cycle keeps running in the main clone while chat answers from its own clone.
    if flock -n "$TEAM/run.lock" true; then CYCLE_RUNNING=0; else CYCLE_RUNNING=1; fi
    export CYCLE_RUNNING
    [ -d "$CHAT_REPO/.git" ] || git clone -q "$(git -C "$MAIN" remote get-url origin)" "$CHAT_REPO" 2>>"$LOG" \
      || { log "no chat clone at $CHAT_REPO"; exit 1; }
    REPO="$CHAT_REPO"
  else
    exec 9>"$TEAM/run.lock"
    flock -n 9 || { log "busy, skip"; exit 0; }
  fi

  cd "$REPO" || { log "no repo"; exit 1; }
  [ -f "$MAIN/.venv/bin/activate" ] && . "$MAIN/.venv/bin/activate"
  sync || log "git sync failed, running on local state"
  PARKED_BRANCHES=""
  [ "$MODE" = chat ] || merge_parked
  export PARKED_BRANCHES

  if [ "$MODE" = chat ]; then
    N="$(bridge pull 2>>"$LOG")"
    { [ "${N:-0}" -gt 0 ]; } 2>/dev/null || exit 0
    INBOX="$(cat "$CHAT_FILE")"
  fi
  PROMPT="$(build_prompt)" || { log "no prompt for $MODE (HEAD and last good copy missing)"; exit 1; }

  log start
  OUT="$(timeout "$T" "$CLAUDE" -p "$PROMPT" --permission-mode bypassPermissions 2>>"$LOG")"
  RC=$?; log "claude exit $RC"
  printf '%s\n' "$OUT" >>"$LOG"
  REPLY="$(boardroom_reply "$OUT")"
  printf '%s\n' "$OUT" | grep -q '^SKIPPED:' && REPLY=""   # gate skip: log only, no chat message
  [ -n "$REPLY" ] && post_reply "$REPLY"

  [ -n "$(git status --porcelain)" ] && log "uncommitted changes left"
  [ "$(ahead)" -gt 0 ] && { sync || log "push failed, will retry next run"; }
  [ "$MODE" = chat ] || prune_parked
  log done
}

[ -n "${RUN_CYCLE_LIB:-}" ] || main "$@"
