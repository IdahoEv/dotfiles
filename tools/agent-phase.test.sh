#!/usr/bin/env bash
# agent-phase.test.sh — behavioral checks for agent-phase.sh's tag grammar and transitions.
#
#   agent-phase.test.sh
#
# Plain script, exits non-zero on failure. HOME and CLAUDE_JOB_DIR are temp dirs.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AP="$TOOLS/agent-phase.sh"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/agent-phase-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME/.config"
export CLAUDE_JOB_DIR="$ROOT/job"; mkdir -p "$CLAUDE_JOB_DIR"
export WF_TELEMETRY=0

name() { jq -r .name "$CLAUDE_JOB_DIR/state.json"; }
fresh() { printf '{"name":"%s"}\n' "${1:-Is1 do thing}" > "$CLAUDE_JOB_DIR/state.json"; }
ap() { "$AP" "$@" >/dev/null; }

fresh "[PLAN] Is1 do thing"
ap WIP
check "stage replaces stage" "[WIP] Is1 do thing" "$(name)"

ap --plan-reviews
check "plan-reviews: local + github by default" "[L- G-] Is1 do thing" "$(name)"

touch "$HOME/.config/local-review-only"
ap WIP; ap --plan-reviews
check "plan-reviews: local-only flag drops G" "[L-] Is1 do thing" "$(name)"
rm "$HOME/.config/local-review-only"

ap WIP; ap --plan-reviews
ap --plan-reviews
check "plan-reviews is idempotent" "[L- G-] Is1 do thing" "$(name)"
ap --review L 1
check "review starts round 1" "[L1 G-] Is1 do thing" "$(name)"
ap --review L 2
check "next round" "[L2 G-] Is1 do thing" "$(name)"
ap --review L ok
check "accepted keeps round" "[L2✓ G-] Is1 do thing" "$(name)"
ap --pr
check "PR tag after the group" "[L2✓ G-] [PR] Is1 do thing" "$(name)"
ap --review G next
check "parallel/serial source starts" "[L2✓ G1] [PR] Is1 do thing" "$(name)"
ap --review G ok
check "all accepted with PR raises attention" "[!] [L2✓ G1✓] [PR] Is1 do thing" "$(name)"
ap --ok
check "ok clears attention" "[L2✓ G1✓] [PR] Is1 do thing" "$(name)"
ap --ok
check "ok when absent is a no-op" "[L2✓ G1✓] [PR] Is1 do thing" "$(name)"

ap --attn
check "attn prefixes" "[!] [L2✓ G1✓] [PR] Is1 do thing" "$(name)"
ap --plan-reviews
check "plan-reviews keeps sources already started" "[L2✓ G1✓] [PR] Is1 do thing" "$(name)"
ap --attn; ap --review G 2
check "state change clears attention" "[L2✓ G2] [PR] Is1 do thing" "$(name)"

ap WIP
check "back to WIP drops sources, keeps PR" "[WIP] [PR] Is1 do thing" "$(name)"
ap --attn
check "attn on a stage tag" "[!] [WIP] [PR] Is1 do thing" "$(name)"

ap MERGED
check "MERGED drops PR and attention" "[MERGED] Is1 do thing" "$(name)"
ap DONE
check "DONE" "[DONE] Is1 do thing" "$(name)"

touch "$HOME/.config/local-review-only"
fresh "Is1 do thing"; ap --plan-reviews; ap --review L 1 ok; ap --pr
check "local-only: accepted plus PR awaits merge" "[!] [L1✓] [PR] Is1 do thing" "$(name)"

fresh "[spike] try X"; ap WIP
check "bracketed title text is kept" "[WIP] [spike] try X" "$(name)"
fresh "[!] [L1 H-] [PR] Is2 x"
check "show reads the prefix" "[!] [L1 H-] [PR]" "$("$AP" --show)"
ap --clear
check "clear strips every tag" "Is2 x" "$(name)"

fresh "[REVIEWED][PR] Is3 legacy"; ap WIP
check "legacy tags are replaced" "[WIP] [PR] Is3 legacy" "$(name)"

"$AP" --review X 1 2>/dev/null; check "bad source rejected" "1" "$?"
"$AP" --review L abc 2>/dev/null; check "bad round rejected" "1" "$?"
"$AP" REVIEW 2>/dev/null; check "removed stage rejected" "1" "$?"

( unset CLAUDE_JOB_DIR; "$AP" WIP ); check "no job dir is a silent no-op" "0" "$?"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
