#!/usr/bin/env bash
# Installed as the runtime's run_cycle.sh (copy to a temp file + mv, never edit in place: a running bash reads its script
# incrementally). Runs the COMMITTED ops/team/run_cycle.sh from $REPO HEAD, held in memory, so a cycle editing the working
# tree never changes a running runner. A missing or syntax-broken HEAD copy falls back to the last good one.
TEAM="${JBHNTR_TEAM:-$HOME/.jbhntr-team}"
REPO="$(set -a; . "$TEAM/env" >/dev/null 2>&1; printf %s "${JBHNTR_REPO:-$HOME/jbhntr}")"
GOOD="$TEAM/run_cycle.good.sh"
S="$(git -C "$REPO" show HEAD:ops/team/run_cycle.sh 2>/dev/null)"
if [ -n "$S" ] && bash -n <(printf '%s\n' "$S") 2>/dev/null; then
  if ! printf '%s\n' "$S" | cmp -s - "$GOOD"; then printf '%s\n' "$S" > "$GOOD.tmp.$$" && mv -f "$GOOD.tmp.$$" "$GOOD"; fi
else
  H="$(git -C "$REPO" rev-parse -q HEAD 2>/dev/null)"
  if [ "$(cat "$TEAM/wrapper.warned" 2>/dev/null)" != "$H" ]; then   # one log line per HEAD, not one per chat poll
    echo "$(date -Is) [wrapper] HEAD:ops/team/run_cycle.sh missing or invalid; running $GOOD" >> "$TEAM/cycle.log"
    printf '%s' "$H" > "$TEAM/wrapper.warned"
  fi
  S="$(cat "$GOOD" 2>/dev/null)" || { echo "$(date -Is) [wrapper] no runner available" >> "$TEAM/cycle.log"; exit 1; }
fi
exec bash -c "$S" run_cycle.sh "$@"
