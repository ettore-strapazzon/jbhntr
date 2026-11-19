#!/usr/bin/env bash
# JBHNTR Team runner. Modes: chat (real-time Founder replies) | cycle | morning.
# Canonical copy (R3-34). The runtime's run_cycle.sh is ops/team/run_wrapper.sh, which runs the COMMITTED version of this file.
# The runner owns git sync: fetch -> rebase -> else merge -> else park local commits on origin/conflict/<mode>-<sha>.
# It never force-pushes and never drops a commit.
# Tests: RUN_CYCLE_LIB=1 sources the functions without running main; JBHNTR_TEAM / CLAUDE_BIN / JBHNTR_BRANCH override paths.
set -uo pipefail
MODE="${1:-cycle}"
TEAM="${JBHNTR_TEAM:-$HOME/.jbhntr-team}"
set -a; . "$TEAM/env"; set +a
REPO="${JBHNTR_REPO:-$HOME/jbhntr}"
APP="${JBHNTR_APP_URL:-https://jbhntr.app}"
BRANCH="${JBHNTR_BRANCH:-main}"
CLAUDE="${CLAUDE_BIN:-claude}"
LOG="$TEAM/cycle.log"
export PATH="$HOME/.local/bin:$PATH"

log() { echo "$(date -Is) [$MODE] $*" >>"$LOG"; }
ahead() { git rev-list --count "origin/$BRANCH..HEAD" 2>/dev/null || echo 0; }
# Boardroom call; the token goes through curl's stdin config, never argv (visible in ps).
bcurl() { printf 'user = "admin:%s"\n' "${JBHNTR_ADMIN_TOKEN:-}" | curl -s -K - "$@"; }
post_reply() { bcurl "$APP/boardroom/reply" --data-urlencode "body=$1" >/dev/null 2>&1; }

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

prompt_chat() {
cat <<EOF
You are the CEO of the JBHNTR Team, replying in real time to the Founder in the Boardroom.
Working dir: $REPO. Founder message(s) just received (JSON): $INBOX

Answer the Founder directly and concisely, in plain language. Read any company/ or code files
you need to answer accurately. If the Founder gives an instruction or decision:
 - Small + about company docs (a decision, an answer to an R-### request, a priority change):
   apply it now — edit the relevant company/state file, commit ONLY company/ files (the runner
   pushes; never push or force-push yourself), and say you've done it.
 - Needs a full work cycle (building/changing product): append it to company/state/BACKLOG.md
   (top sprint) or a DECISIONS/REQUESTS entry, commit company/, and say it's queued.
Never take outward actions (post/email/accounts/OAuth/pay). Never touch product code or the
three protected UI files. Never commit secrets.
Output ONLY your reply to the Founder — no preamble.
EOF
}

prompt_morning() {
cat <<EOF
You are the CEO of the JBHNTR Team. Working dir: $REPO.
Read company/state/KPIS.md, LEDGER.csv, REQUESTS.md, CYCLE_LOG.md (last 24h),
and company/updates/_TEMPLATE.md. Write company/updates/$(date +%F).md following the
8-section template with REAL numbers only (— = not measured). Keep it short. Commit the
company/ change (the runner pushes; never push yourself). Then output ONE line starting
exactly 'BOARDROOM: ' summarising the update for the Founder.
EOF
}

prompt_cycle() {
cat <<EOF
You are the CEO of the JBHNTR Team. Working dir: $REPO.
(Founder conversation is handled live by the chat responder; any orders are already filed
in BACKLOG/REQUESTS/DECISIONS — read them.)

0. PARKED BRANCHES: ${PARKED_BRANCHES:-none}. If any are listed, merge each into $BRANCH FIRST
   (git merge <branch>), resolving conflicts by keeping both sides (both rows/ids; renumber a
   duplicate id), and commit the merge. The runner deletes them once they are on $BRANCH.
1. Invoke the task-observer skill (session start), then read company/CHARTER.md,
   company/agents/SKILLS.md, all of company/state/*, and company/docs/marketing/GTM.md.
2. RECOVERY: resolve any task left "doing" in CYCLE_LOG.md/BACKLOG.md by a cut-off run.
3. IDLE CHECK: if no unblocked task in the current (top) sprint of BACKLOG.md and nothing new
   from the Founder, append a one-line CYCLE_LOG "idle, skipped" and STOP. Never run more than
   10 full cycles in one calendar day (count today's ## entries in CYCLE_LOG.md).
4. DISPATCH the 1-2 highest-leverage unblocked tasks per agent from the current top sprint
   (respect deps/gates). Launch each as a FOREGROUND sub-agent (Agent tool), in parallel,
   each told: "You are the <ROLE> of the JBHNTR Team. Read company/agents/<role>.md,
   company/CHARTER.md, company/agents/SKILLS.md. Do BACKLOG <id>: <task + acceptance>. Follow
   SKILLS.md: check the live skill list, invoke every matching skill, end with 'Skills used: …'.
   Take NO outward action (post/email/account/OAuth/pay) — draft exact REQUESTS.md steps instead.
   Return what you shipped, how it meets acceptance, any blocker."
5. REVIEW each deliverable vs its acceptance criteria; send back if short.
6. TEST once, after all sub-agents finish (never concurrently):
   pip install -q -r requirements-dev.txt && python -m pytest -q . Must be green before commit.
7. RECORD: update BACKLOG statuses, write a CYCLE_LOG entry, update DECISIONS/REQUESTS/KPIS.
7b. LIVE LOG: \$JBHNTR_ADMIN_TOKEN and \$JBHNTR_APP_URL are set in your environment (use the variables; never print or write the token). The MOMENT you dispatch each sub-agent, run (do not batch, do not wait for the cycle to end): curl -s -u "admin:\$JBHNTR_ADMIN_TOKEN" "\$JBHNTR_APP_URL/boardroom/log" --data-urlencode agent=<CEO|CTO|CMO|CPO|CFO|GC> --data-urlencode "task=<backlog id + short title>" --data-urlencode status=started --data-urlencode cycle=<today's cycle number>. When you finish reviewing that agent, post again with status=shipped (or blocked) and --data-urlencode "summary=<one plain sentence>". Post in real time so the Boardroom Live team feed updates as you work.
8. COMMIT company/ changes; commit product changes too only if the suite is green. Do NOT push
   or force-push: the runner syncs and pushes after you finish. Never commit secrets. Do NOT
   stage web/app/static/app.js, web/app/templates/matches.html, or
   web/app/templates/partials/track_card.html unless the task is specifically about them.
9. Output ONE final line starting exactly 'BOARDROOM: ' — a plain-language summary of what
   this cycle shipped, for the Founder.
EOF
}

main() {
  local T N INBOX="" PROMPT OUT RC REPLY
  case "$MODE" in cycle) T=3h ;; morning) T=1h ;; chat) T=20m ;; *) echo "usage: $0 cycle|morning|chat" >&2; exit 2 ;; esac

  # Chat mode: cheap guard — if no Founder message is waiting, don't even start Claude.
  if [ "$MODE" = chat ]; then
    N="$(bcurl "$APP/boardroom/peek" 2>/dev/null | grep -o '[0-9]\+' | head -1)"
    { [ "${N:-0}" -eq 0 ]; } 2>/dev/null && exit 0
  fi

  exec 9>"$TEAM/cycle.lock"
  flock -n 9 || { log "busy, skip"; exit 0; }

  cd "$REPO" || { log "no repo"; exit 1; }
  [ -f .venv/bin/activate ] && . .venv/bin/activate
  sync || log "git sync failed, running on local state"
  PARKED_BRANCHES=""
  [ "$MODE" = chat ] || merge_parked
  export PARKED_BRANCHES

  if [ "$MODE" = chat ]; then
    INBOX="$(bcurl "$APP/boardroom/pull" 2>/dev/null)"
    { [ -z "$INBOX" ] || [ "$INBOX" = "[]" ]; } && exit 0
  fi
  PROMPT="$("prompt_$MODE")"

  log start
  OUT="$(timeout "$T" "$CLAUDE" -p "$PROMPT" --permission-mode bypassPermissions 2>>"$LOG")"
  RC=$?; log "claude exit $RC"
  printf '%s\n' "$OUT" >>"$LOG"
  REPLY="$(boardroom_reply "$OUT")"
  [ -n "$REPLY" ] && post_reply "$REPLY"

  [ -n "$(git status --porcelain)" ] && log "uncommitted changes left"
  [ "$(ahead)" -gt 0 ] && { sync || log "push failed, will retry next run"; }
  [ "$MODE" = chat ] || prune_parked
  log done
}

[ -n "${RUN_CYCLE_LIB:-}" ] || main "$@"
