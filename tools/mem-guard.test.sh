#!/usr/bin/env bash
# Integration tests for mem-guard.sh: real ps + real tmux (isolated socket), fake agent
# binaries named claude/agy/codex, and fixtures for the host pressure reading.
# Unit coverage (attribution, thresholds, parsing) lives in lib/mem_guard_test.py.

set -uo pipefail
TOOLS="$(cd "$(dirname "$0")" && pwd)"
MG="$TOOLS/mem-guard.sh"
ROOT="$(cd -P "$(mktemp -d)" && pwd)"
SOCK="mem-guard-test-$$"
pass=0 fail=0
cleanup() { tmux -L "$SOCK" kill-server >/dev/null 2>&1 || true; pkill -f "$ROOT/bin/" >/dev/null 2>&1 || true; rm -rf "$ROOT"; }
trap cleanup EXIT

check() { if [ "$2" = "$3" ]; then pass=$((pass+1)); printf 'PASS %s\n' "$1"; else fail=$((fail+1)); printf 'FAIL %s\n  want [%s]\n  got  [%s]\n' "$1" "$2" "$3" >&2; fi; }
has() { if printf '%s' "$3" | grep -qF -- "$2"; then pass=$((pass+1)); printf 'PASS %s\n' "$1"; else fail=$((fail+1)); printf 'FAIL %s: missing [%s] in:\n%s\n' "$1" "$2" "$3" >&2; fi; }
lacks() { if printf '%s' "$3" | grep -qF -- "$2"; then fail=$((fail+1)); printf 'FAIL %s: unexpected [%s]\n' "$1" "$2" >&2; else pass=$((pass+1)); printf 'PASS %s\n' "$1"; fi; }

export HOME="$ROOT/home"; mkdir -p "$HOME" "$ROOT/bin"
unset MEM_GUARD_OVERRIDE MEM_GUARD_FAIL MEM_GUARD_ENABLED MEM_GUARD_PS_FIXTURE
export MEM_GUARD_HOST_FIXTURE="level=normal free_pct=70"

SLEEP="$(command -v sleep)"
for n in claude codex; do ln -s "$SLEEP" "$ROOT/bin/$n"; done
ln -s "$(command -v tail)" "$ROOT/bin/agy"   # takes a secret-looking argument without exiting

# ---- check: exit codes ---------------------------------------------------------
"$MG" check; check "healthy host: exit 0" 0 $?
err="$(MEM_GUARD_HOST_FIXTURE='level=warn free_pct=14' "$MG" check 2>&1)"; rc=$?
check "warn: exit 0" 0 "$rc"; has "warn: message" "WARNING" "$err"
err="$(MEM_GUARD_HOST_FIXTURE='level=critical free_pct=5' "$MG" check 2>&1)"; rc=$?
check "critical: exit 3" 3 "$rc"; has "critical: says nothing was killed" "no session was killed" "$err"
MEM_GUARD_HOST_FIXTURE='level=critical free_pct=5' "$MG" check --force >/dev/null 2>&1; check "--force: exit 0" 0 $?
MEM_GUARD_HOST_FIXTURE='level=critical free_pct=5' MEM_GUARD_OVERRIDE=1 "$MG" check >/dev/null 2>&1; check "env override: exit 0" 0 $?
MEM_GUARD_HOST_FIXTURE='level=normal free_pct=7' MEM_GUARD_BLOCK_FREE_PCT=5 "$MG" check >/dev/null 2>&1; check "configurable threshold: 7% passes when block=5" 0 $?
MEM_GUARD_HOST_FIXTURE='level=normal free_pct=7' MEM_GUARD_BLOCK_FREE_PCT=10 "$MG" check >/dev/null 2>&1; check "configurable threshold: 7% blocks when block=10" 3 $?
MEM_GUARD_HOST_FIXTURE='level=critical' MEM_GUARD_ENABLED=off "$MG" check >/dev/null 2>&1; check "disabled guard: exit 0" 0 $?
MEM_GUARD_HOST_FIXTURE='level=unknown' "$MG" check >/dev/null 2>&1; check "unreadable pressure fails open" 0 $?
MEM_GUARD_HOST_FIXTURE='level=unknown' MEM_GUARD_FAIL=closed "$MG" check >/dev/null 2>&1; check "unreadable pressure fails closed on request" 3 $?
MEM_GUARD_PS_FIXTURE="$ROOT/missing" "$MG" check >/dev/null 2>&1; check "unreadable process table still lets a healthy host launch" 0 $?

# ---- report: real ps, unmanaged agents ---------------------------------------------
SECRET="sk-test-SECRET-ARGUMENT-123"
# Daemonized so they are not children of whatever agent is running this test (a nested
# agent is correctly attributed to its parent session, which would hide them from the report).
spawn() {
  python3 -c 'import subprocess, sys; subprocess.Popen(sys.argv[1:], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)' "$@"
}
spawn "$ROOT/bin/claude" 300
spawn "$ROOT/bin/agy" -f /dev/null "/nonexistent/$SECRET"
spawn "$ROOT/bin/codex" 300
sleep 0.5
CLAUDE_PID="$(pgrep -f "$ROOT/bin/claude" | head -1)"
AGY_PID="$(pgrep -f "$ROOT/bin/agy" | head -1)"
CODEX_PID="$(pgrep -f "$ROOT/bin/codex" | head -1)"
for pair in "claude:$CLAUDE_PID" "agy:$AGY_PID" "codex:$CODEX_PID"; do
  name="${pair%%:*}"; pid="${pair#*:}"
  check "report: $name spawned" 1 "$([ -n "$pid" ] && echo 1 || echo 0)"
done
out="$("$MG" report 2>&1)"
has "report: host line" "host pressure: normal, ~70% free" "$out"
has "report: finds the claude process" "claude pid $CLAUDE_PID" "$out"
has "report: finds agy" "agy pid $AGY_PID" "$out"
has "report: finds codex" "codex pid $CODEX_PID" "$out"
has "report: flags launcher-less sessions" "started outside the launcher" "$out"
has "report: states it is an estimate" "phys_footprint" "$out"
json="$("$MG" report --json)"
has "report --json: sessions listed" '"backend": "claude"' "$json"
lacks "privacy: command-line arguments never reach report output" "$SECRET" "$out"
lacks "privacy: command-line arguments never reach json output" "$SECRET" "$json"
kill "$CLAUDE_PID" "$AGY_PID" "$CODEX_PID" 2>/dev/null

# ---- report: managed tmux session, exited pane ----------------------------------------
mkdir -p "$ROOT/wt"
printf '{"version":1,"key":"Is191","tickets":[{"id":"191","url":""}]}\n' > "$ROOT/wt/.workstream.json"
tmux -L "$SOCK" new-session -d -s ws -n dashboard "sleep 60"
tmux -L "$SOCK" set-option -g remain-on-exit on
tmux -L "$SOCK" new-window -d -t =ws: -n Is191 -c "$ROOT/wt" "$ROOT/bin/claude 60"
tmux -L "$SOCK" new-window -d -t =ws: -n Is192 "true"
sleep 0.6
out="$("$MG" report --session ws --socket "$SOCK" 2>&1)"
has "tmux: managed window listed by name" "Is191" "$out"
lacks "tmux: managed window is not flagged as launcher-less" "Is191 *" "$out"
has "tmux: backend detected" "claude" "$out"
lacks "tmux: dashboard window 0 excluded" "dashboard" "$out"
has "tmux: exited pane shown as exited" "exited" "$out"
check "tmux: agent counted once, not also as launcher-less" "1" "$(printf '%s\n' "$out" | grep -c 'Is191')"
out="$("$MG" report --session no-such-session --socket "$SOCK" 2>&1)"; check "missing tmux session degrades" 0 $?
has "missing tmux session: still reports host" "host pressure" "$out"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
