#!/usr/bin/env bash
# telemetry.test.sh — event emission: schema, sanitization, failure policy,
# concurrent appends, and the emit points in agent-phase / review-state / open-pr.
#
#   lib/telemetry.test.sh
#
# Plain script, exits non-zero on failure (see repo-facts.test.sh).

set -uo pipefail
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$(dirname "$LIB")"
REPO="$(dirname "$TOOLS")"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/telemetry-test.XXXXXX")"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME"
export WF_TELEMETRY_LOG="$ROOT/events.jsonl"
unset CLAUDE_JOB_DIR WF_TELEMETRY
export CLAUDE_CODE_SESSION_ID=sess-1
LOG="$WF_TELEMETRY_LOG"

new_repo() {  # <branch> [origin-url]
  rm -rf "$ROOT/repo"
  git init -q -b main "$ROOT/repo"
  git -C "$ROOT/repo" remote add origin "${2:-git@github.com:acme/widgets.git}"
  git -C "$ROOT/repo" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
  git -C "$ROOT/repo" checkout -q -b "$1"
}
ev() { "$TOOLS/wf-event.sh" --dir "$ROOT/repo" "$@"; }
last() { tail -1 "$LOG" | jq -r "$1"; }
reset() { rm -f "$LOG"; }

# ---- schema and run id --------------------------------------------------------
new_repo 42-add-thing
reset; ev phase phase=WIP
check "github run_id"       "acme/widgets#42" "$(last .run_id)"
check "event name"          "phase"           "$(last .event)"
check "field"               "WIP"             "$(last .phase)"
check "session id"          "sess-1"          "$(last .session_id)"
check "schema version"      "1"               "$(last .v)"
check "ts is ISO UTC ms"    "1" "$(last .ts | grep -cE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}\.[0-9]{3}Z$')"
check "no job_id outside bg" "null"           "$(last .job_id)"

new_repo feature/sc-123/do-it
reset; ev x
check "shortcut run_id is repo-independent" "sc-123" "$(last .run_id)"

new_repo main-scratch
reset; ev x
check "non-ticket branch: nothing written" "absent" "$([ -e "$LOG" ] && echo present || echo absent)"
reset; ev ticket.start ticket=7
check "explicit ticket overrides branch" "acme/widgets#7" "$(last .run_id)"
reset; ev ticket.start ticket=7 scheme=shortcut
check "explicit scheme" "sc-7" "$(last .run_id)"

# ---- coercion and sanitization -------------------------------------------------
new_repo 42-add-thing
reset; ev x n=3 neg=-1 lead=007 big=12345678901234567890 t=true s=abc 'nl=a
b' BAD-key=1 run_id=evil v=9
check "int"                 "3number" "$(last '.n | tostring + (type)')"
check "negative int"        "-1number" "$(last '.neg | tostring + (type)')"
check "leading zero stays string" "007string" "$(last '.lead | tostring + (type)')"
check "huge int stays string" "string" "$(last '.big | type')"
check "bool"                "boolean" "$(last '.t | type')"
check "control chars flattened" "a b" "$(last .nl)"
check "bad key dropped"     "null"   "$(last '."BAD-key"')"
check "reserved keys protected" "acme/widgets#42 1" "$(last '"\(.run_id) \(.v)"')"
reset; ev x "long=$(printf 'y%.0s' $(seq 1 500))"
check "values capped at 200" "200" "$(last '.long | length')"

# ---- failure policy -------------------------------------------------------------
reset; WF_TELEMETRY=0 ev x
check "WF_TELEMETRY=0 disables" "1" "$([ -f "$LOG" ] && echo 0 || echo 1)"
err="$(WF_TELEMETRY_LOG=/dev/null/nope ev x 2>&1)"; rc=$?
check "unwritable log exits 0" "0" "$rc"
check "unwritable log warns"   "1" "$(grep -c 'telemetry: cannot write' <<<"$err")"
mkdir -p "$ROOT/nojq"; for b in git perl dirname basename mkdir; do ln -sf "$(command -v $b)" "$ROOT/nojq/$b"; done
err="$(PATH="$ROOT/nojq" /bin/bash "$TOOLS/wf-event.sh" --dir "$ROOT/repo" x 2>&1)"; rc=$?
check "no jq exits 0"  "0" "$rc"
check "no jq warns"    "1" "$(grep -c 'jq not found' <<<"$err")"
check "not a repo exits 0" "0" "$(cd "$ROOT" && "$TOOLS/wf-event.sh" x >/dev/null 2>&1; echo $?)"

# ---- concurrency ------------------------------------------------------------------
reset
for i in $(seq 1 50); do ev concurrent "i=$i" "pad=$(printf 'p%.0s' $(seq 1 150))" & done; wait
check "50 parallel writers: 50 lines" "50" "$(wc -l < "$LOG" | tr -d ' ')"
check "every line parses"   "50" "$(jq -c . "$LOG" 2>/dev/null | wc -l | tr -d ' ')"
check "every writer present" "50" "$(jq -r .i "$LOG" | sort -u | wc -l | tr -d ' ')"
check "lines under PIPE_BUF" "0" "$(awk 'length($0) >= 4096' "$LOG" | wc -l | tr -d ' ')"

# ---- hook payloads --------------------------------------------------------------
hook() { printf '%s' "$1" | "$TOOLS/wf-event.sh" --hook; }
reset
hook "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"s-9\",\"cwd\":\"$ROOT/repo\",\"source\":\"startup\",\"transcript_path\":\"/secret/path.jsonl\"}"
check "SessionStart → session.start" "session.start startup s-9" "$(last '"\(.event) \(.source) \(.session_id)"')"
check "transcript path not logged" "0" "$(grep -c secret "$LOG")"
hook "{\"hook_event_name\":\"StopFailure\",\"session_id\":\"s-9\",\"cwd\":\"$ROOT/repo\",\"error\":\"rate_limit\"}"
check "StopFailure → session.fail" "session.fail rate_limit" "$(last '"\(.event) \(.error)"')"
hook "{\"hook_event_name\":\"StopFailure\",\"session_id\":\"s-9\",\"cwd\":\"$ROOT/repo\",\"error\":\"free text with a prompt fragment\"}"
check "free-text detail redacted" "other" "$(last .error)"
hook "{\"hook_event_name\":\"SubagentStop\",\"session_id\":\"s-9\",\"cwd\":\"$ROOT/repo\",\"agent_type\":\"correctness-reviewer\"}"
check "SubagentStop agent type" "correctness-reviewer" "$(last .agent_type)"
hook "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"\",\"cwd\":\"$ROOT/repo\",\"source\":\"resume\"}"
check "empty middle field doesn't shift the rest" "session.start resume acme/widgets#42" \
  "$(last '"\(.event) \(.source) \(.run_id)"')"
hook "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"s-10\",\"cwd\":\"$ROOT/repo\",\"source\":\"start\\u001fx\"}"
check "separator in a value doesn't split it" "other s-10" "$(last '"\(.source) \(.session_id)"')"
n="$(wc -l < "$LOG")"; hook '{"hook_event_name":"PreToolUse"}'; hook 'not json'
check "other events and junk ignored" "$n" "$(wc -l < "$LOG")"

# ---- emit points ----------------------------------------------------------------
cd "$ROOT/repo" || exit 1
reset; "$TOOLS/agent-phase.sh" WIP; "$TOOLS/agent-phase.sh" --pr; "$TOOLS/agent-phase.sh" --no-review
check "agent-phase emits set + no-review only" "WIP REVIEWED" "$(jq -r .phase "$LOG" | xargs)"
reset
mkdir -p "$ROOT/bin"; ln -sf "$TOOLS/wf-event.sh" "$ROOT/bin/wf-event.sh"
PATH="$ROOT/bin:$PATH" bash "$REPO/dot_claude/skills/github-review-procedure/executable_github-review-state.sh" --set-local '1*'
PATH="$ROOT/bin:$PATH" bash "$REPO/dot_claude/skills/github-review-procedure/executable_github-review-state.sh" --set-local 2
check "review-state: round start/end" "2:start 2:end" "$(jq -r '"\(.round):\(.state)"' "$LOG" | xargs)"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
