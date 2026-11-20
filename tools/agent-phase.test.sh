#!/usr/bin/env bash
# Test agent-phase.sh updates .workstream.json (with and without CLAUDE_JOB_DIR).
set -euo pipefail

TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0
FAIL=0

check() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    PASS=$((PASS + 1))
  else
    printf 'FAIL %s: expected %q, got %q\n' "$name" "$expected" "$actual" >&2
    FAIL=$((FAIL + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

REPO="$TMP/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q

# Outside a workstream: no-ops cleanly with exit 0
(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" WIP)
check "no workstream exits 0" "0" "$?"

# Initialize .workstream.json
"$TOOLS_DIR/workstream.sh" init-ticket --dir "$REPO" --provider github --ids 188 --title "Phase tags"

# Outside background session (no CLAUDE_JOB_DIR): updates .workstream.json
(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" WIP)
check "non-bg WIP" "[WIP]" "$(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --show)"

(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --pr)
check "non-bg --pr" "[WIP][PR]" "$(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --show)"

(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --plan-reviews)
(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --review L ok)
check "non-bg review keeps PR" "[L✓ G-][PR]" "$(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --show)"

(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" MERGED)
check "non-bg MERGED drops PR" "[MERGED]" "$(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --show)"

(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --clear)
check "non-bg --clear" "" "$(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --show)"

# --dir targets a worktree from a different cwd
(cd "$TMP" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --dir "$REPO" --review L 1)
check "--dir from outside repo" "[L1]" "$(cd "$TMP" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --dir "$REPO" --show)"

# Inside background session: updates BOTH state.json and .workstream.json
JOB_DIR="$TMP/job"
mkdir -p "$JOB_DIR"
printf '{"name": "stale name"}\n' > "$JOB_DIR/state.json"
(cd "$REPO" && CLAUDE_JOB_DIR="$JOB_DIR" "$TOOLS_DIR/agent-phase.sh" WIP >/dev/null)
check "bg state.json mirrors record" "[WIP] Is188 phase tags" "$(jq -r .name "$JOB_DIR/state.json")"
check "bg .workstream.json" "[WIP]" "$("$TOOLS_DIR/workstream.sh" phase --dir "$REPO" --show)"
check "bg --show" "[WIP]" "$(cd "$REPO" && CLAUDE_JOB_DIR="$JOB_DIR" "$TOOLS_DIR/agent-phase.sh" --show)"
check "bg --show without state.json" "[WIP]" "$(cd "$REPO" && CLAUDE_JOB_DIR="$TMP/missing-job" "$TOOLS_DIR/agent-phase.sh" --show)"

# ---- tag grammar and transitions, driven through state.json (no workstream record) ----
export HOME="$TMP/home"; mkdir -p "$HOME/.config"
export CLAUDE_JOB_DIR="$TMP/job2"; mkdir -p "$CLAUDE_JOB_DIR"
export WF_TELEMETRY=0
cd "$TMP"
AP="$TOOLS_DIR/agent-phase.sh"
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
check "PR tag after the group" "[L2✓ G-][PR] Is1 do thing" "$(name)"
ap --review G next
check "second source starts" "[L2✓ G1][PR] Is1 do thing" "$(name)"
ap --review G ok
check "all accepted with PR raises attention" "[!][L2✓ G1✓][PR] Is1 do thing" "$(name)"
ap --ok
check "ok clears attention" "[L2✓ G1✓][PR] Is1 do thing" "$(name)"
before="$(name)"; ap --ok
check "ok when absent is a no-op" "$before" "$(name)"
ap --attn
check "attn prefixes" "[!][L2✓ G1✓][PR] Is1 do thing" "$(name)"
ap --plan-reviews
check "plan-reviews keeps sources already started" "[L2✓ G1✓][PR] Is1 do thing" "$(name)"
ap --attn; ap --review G 2
check "state change clears attention" "[L2✓ G2][PR] Is1 do thing" "$(name)"
ap WIP
check "back to WIP drops sources, keeps PR" "[WIP][PR] Is1 do thing" "$(name)"
ap --attn
check "attn on a stage tag" "[!][WIP][PR] Is1 do thing" "$(name)"
ap MERGED
check "MERGED drops PR and attention" "[MERGED] Is1 do thing" "$(name)"
ap DONE
check "DONE" "[DONE] Is1 do thing" "$(name)"

touch "$HOME/.config/local-review-only"
fresh "Is1 do thing"; ap --plan-reviews; ap --review L 1 ok; ap --pr
check "local-only: accepted plus PR awaits merge" "[!][L1✓][PR] Is1 do thing" "$(name)"

fresh "[spike] try X"; ap WIP
check "bracketed title text is kept" "[WIP] [spike] try X" "$(name)"
fresh "[!][L1 H-][PR] Is2 x"
check "show reads the prefix" "[!][L1 H-][PR]" "$("$AP" --show)"
ap --clear
check "clear strips every tag" "Is2 x" "$(name)"
fresh "[REVIEWED][PR] Is3 legacy"; ap WIP
check "legacy tags are replaced" "[WIP][PR] Is3 legacy" "$(name)"

rc=0; "$AP" --review X 1 2>/dev/null || rc=$?; check "bad source rejected" "1" "$rc"
rc=0; "$AP" --review L abc 2>/dev/null || rc=$?; check "bad round rejected" "1" "$rc"
rc=0; "$AP" REVIEW 2>/dev/null || rc=$?; check "removed stage rejected" "1" "$rc"
rc=0; ( unset CLAUDE_JOB_DIR; "$AP" WIP ) || rc=$?; check "no job dir is a silent no-op" "0" "$rc"

printf 'agent-phase.test.sh: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
