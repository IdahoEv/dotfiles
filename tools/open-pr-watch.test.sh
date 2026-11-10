#!/usr/bin/env bash
# open-pr-watch.test.sh — poll exit code → phase stamp, event and notification.
#
#   open-pr-watch.test.sh
#
# Plain script, exits non-zero on failure (see finalize-check.test.sh). The poll
# script and osascript are stubs; the phase is observed through a fake
# $CLAUDE_JOB_DIR/state.json, so agent-phase.sh runs for real.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/open-pr-watch-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME" "$ROOT/bin"
export WF_TELEMETRY_LOG="$ROOT/events.jsonl"
export CLAUDE_JOB_DIR="$ROOT/job"; mkdir -p "$CLAUDE_JOB_DIR"

cat > "$ROOT/bin/poll" <<'STUB'
#!/usr/bin/env bash
exit "${POLL_RC:-0}"
STUB
cat > "$ROOT/bin/osascript" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$NOTIFY_LOG"
STUB
chmod +x "$ROOT/bin/poll" "$ROOT/bin/osascript"
export PATH="$ROOT/bin:$PATH" OPEN_PR_POLL="$ROOT/bin/poll" NOTIFY_LOG="$ROOT/notify.log"

watch() {  # <poll-rc> → stdout of the watcher
  rm -f "$NOTIFY_LOG" "$WF_TELEMETRY_LOG"
  printf '{"name":"[REVIEW][PR] Is42 foo","state":"working"}' > "$CLAUDE_JOB_DIR/state.json"
  POLL_RC="$1" "$TOOLS/open-pr-watch.sh" 7
}
phase() { jq -r '.name | split(" ")[0]' "$CLAUDE_JOB_DIR/state.json"; }
event() { tail -1 "$WF_TELEMETRY_LOG" 2>/dev/null | jq -r "$1" 2>/dev/null; }

out="$(watch 0)"
check "comments: outcome line"  "pr=7 exit_code=0 outcome=comments: review comments arrived: run /github-review-comments" "$out"
check "comments: phase untouched" "[REVIEW][PR]" "$(phase)"
check "comments: notified"      "1" "$(grep -c 'display notification' "$NOTIFY_LOG")"
check "comments: notification names the PR" "1" "$(grep -c 'PR #7' "$NOTIFY_LOG")"

out="$(watch 3)"
check "signed off: phase reviewed" "[REVIEWED][PR]" "$(phase)"
check "signed off: outcome"     "1" "$(grep -c 'outcome=signed-off' <<<"$out")"

out="$(watch 4)"
check "reviewer unavailable: phase reviewed" "[REVIEWED][PR]" "$(phase)"

out="$(watch 1)"
check "timeout: phase untouched" "[REVIEW][PR]" "$(phase)"
check "timeout: outcome"        "1" "$(grep -c 'outcome=timeout' <<<"$out")"

out="$(watch 9)"
check "unknown exit: outcome error" "1" "$(grep -c 'outcome=error' <<<"$out")"

"$TOOLS/open-pr-watch.sh" bogus >/dev/null 2>&1; check "bad PR number refused" "1" "$?"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
