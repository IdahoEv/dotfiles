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

(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" REVIEW)
(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --no-review)
check "non-bg --no-review" "[REVIEWED][PR]" "$(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --show)"

(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" MERGED)
check "non-bg MERGED drops PR" "[MERGED]" "$(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --show)"

(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --clear)
check "non-bg --clear" "" "$(cd "$REPO" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --show)"

# --dir targets a worktree from a different cwd
(cd "$TMP" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --dir "$REPO" REVIEW)
check "--dir from outside repo" "[REVIEW]" "$(cd "$TMP" && env -u CLAUDE_JOB_DIR "$TOOLS_DIR/agent-phase.sh" --dir "$REPO" --show)"

# Inside background session: updates BOTH state.json and .workstream.json
JOB_DIR="$TMP/job"
mkdir -p "$JOB_DIR"
printf '{"name": "stale name"}\n' > "$JOB_DIR/state.json"
(cd "$REPO" && CLAUDE_JOB_DIR="$JOB_DIR" "$TOOLS_DIR/agent-phase.sh" WIP >/dev/null)
check "bg state.json mirrors record" "[WIP] Is188 phase tags" "$(jq -r .name "$JOB_DIR/state.json")"
check "bg .workstream.json" "[WIP]" "$("$TOOLS_DIR/workstream.sh" phase --dir "$REPO" --show)"
check "bg --show" "[WIP]" "$(cd "$REPO" && CLAUDE_JOB_DIR="$JOB_DIR" "$TOOLS_DIR/agent-phase.sh" --show)"
check "bg --show without state.json" "[WIP]" "$(cd "$REPO" && CLAUDE_JOB_DIR="$TMP/missing-job" "$TOOLS_DIR/agent-phase.sh" --show)"

printf 'agent-phase.test.sh: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
