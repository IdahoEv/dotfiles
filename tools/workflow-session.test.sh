#!/usr/bin/env bash
# workflow-session.test.sh — behavioral checks for workflow-session.sh.
#
#   workflow-session.test.sh
#
# Plain script, exits non-zero on failure. HOME is a temp dir so the real
# ~/.config can't leak in; worktree-manager.sh and start-ticket.sh are stubbed.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$TOOLS/workflow-session.sh"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

has() {  # <description> <file> <fixed string>
  if grep -qF -- "$3" "$2" 2>/dev/null; then r=yes; else r=no; fi
  check "$1" yes "$r"
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/workflow-session-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME"
unset GIT_TOOLS_PROJECTS_DIR CLAUDE_JOB_DIR
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export TMPDIR="$ROOT/tmp"; mkdir -p "$TMPDIR"
export SESSION_LABEL_STATE_FILE="$ROOT/state.json"

# Stubs: wm creates a sibling worktree and prints its path last, as the real one does.
cat > "$ROOT/wm" <<'SH'
#!/usr/bin/env bash
main="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
wt="$(dirname "$main")/$1"
git worktree add -q "$wt" -b "$1"
echo "$wt"
SH
cat > "$ROOT/st" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$ST_LOG"
printf 'label=%s\n' "${GT_LABEL_OVERRIDE:-}" >> "$ST_LOG"
SH
chmod +x "$ROOT/wm" "$ROOT/st"
export WORKFLOW_SESSION_WM="$ROOT/wm" WORKFLOW_SESSION_START="$ROOT/st" ST_LOG="$ROOT/st.log"

mkdir -p "$ROOT/proj"
git init -q "$ROOT/proj/widgets"
P="$ROOT/proj/widgets"
git -C "$P" commit -q --allow-empty -m init
git -C "$P" remote add origin git@github.com:acme/widgets.git
mkdir -p "$P/.claude"
printf 'GOVERNOR-CONTEXT-MARKER\n' > "$P/.claude/governor.md"
printf '# widgets\n' > "$P/CLAUDE.md"

run() { (cd "$P" && "$WS" "$@" 2>&1); }
kickoff() { printf '%s' "$TMPDIR/widgets-kickoff-workflow.md"; }
wt_count() { git -C "$P" worktree list --porcelain | grep -c 'branch refs/heads/workflow$'; }

echo '{"name":"widgets Workflow"}' > "$SESSION_LABEL_STATE_FILE"
out="$(run)"; rc=$?
check "refuses outside a governor session" "1" "$rc"
check "no worktree created when refused" "0" "$(wt_count)"
check "no session launched when refused" "no" "$([ -e "$ST_LOG" ] && echo yes || echo no)"

echo '{"name":"widgets Governor"}' > "$SESSION_LABEL_STATE_FILE"
out="$(run)"; rc=$?
check "runs in a governor session" "0" "$rc"
check "creates one workflow worktree" "1" "$(wt_count)"
case "$out" in *"reused=no"*) r=yes ;; *) r=no ;; esac
check "reports reused=no on first run" yes "$r"

KF="$(kickoff)"
has "kickoff carries governor.md" "$KF" "GOVERNOR-CONTEXT-MARKER"
has "kickoff points at repo CLAUDE.md" "$KF" "CLAUDE.md"
has "kickoff names the issue command" "$KF" "gh issue create -R IdahoEv/dotfiles"
has "kickoff states the scope rule" "$KF" "every project"
has "kickoff sets title and color" "$KF" "session-label.sh --title Workflow --color project"
has "kickoff loads /workflow" "$KF" "/workflow"

has "launches via start-ticket --tab-only" "$ST_LOG" "--tab-only $ROOT/proj/workflow $KF"
has "label identifies the project" "$ST_LOG" "label=widgets workflow"

out="$(run)"; rc=$?
check "second run succeeds" "0" "$rc"
check "second run reuses the worktree" "1" "$(wt_count)"
case "$out" in *"reused=yes"*) r=yes ;; *) r=no ;; esac
check "reports reused=yes on re-run" yes "$r"

rm -f "$ST_LOG"
(cd "$P" && "$WS" --force >/dev/null 2>&1)
echo '{"name":"anything"}' > "$SESSION_LABEL_STATE_FILE"
(cd "$P" && "$WS" --force >/dev/null 2>&1); check "--force bypasses the governor check" "0" "$?"

check "project checkout stays clean" "" "$(git -C "$P" status --porcelain | grep -v '^?? ')"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
