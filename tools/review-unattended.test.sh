#!/usr/bin/env bash
# review-unattended.test.sh — checks for the marker switch and round counter.
#
#   review-unattended.test.sh
#
# Plain script, exits non-zero on failure. HOME is a temp dir so the real
# ~/.config can't leak in; the counter lives in a throwaway git repo.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$TOOLS/review-unattended.sh"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/review-unattended-test.XXXXXX")"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME/.config"
REPO="$ROOT/repo"; git init -q "$REPO"
run() { (cd "$REPO" && "$SCRIPT" "$@"); }

run active; check "inactive without marker" 1 $?

touch "$HOME/.config/github-review-unattended"
run active; check "active with marker" 0 $?

touch "$HOME/.config/local-review-only"
run active; check "local-review-only overrides marker" 1 $?
rm "$HOME/.config/local-review-only"

check "round 1" "round=1" "$(run next-round)"
check "round 2" "round=2" "$(run next-round)"
run reset
check "round 1 after reset" "round=1" "$(run next-round)"

export REVIEW_UNATTENDED_MAX=2
run reset
check "round 1 of 2" "round=1" "$(run next-round)"
check "final round is flagged" "round=2 last=1" "$(run next-round)"
out="$(run next-round)"; rc=$?
check "cap output" "cap=reached" "$out"
check "cap exit code" 1 "$rc"

(cd "$ROOT" && "$SCRIPT" next-round) 2>/dev/null; check "outside a repo fails" 2 $?
run bogus 2>/dev/null; check "unknown subcommand fails" 2 $?

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
