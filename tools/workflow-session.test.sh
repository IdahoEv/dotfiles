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

# Stubs: wm creates a worktree beside the current checkout and prints its path
# last, as the real one does from the primary worktree.
cat > "$ROOT/wm" <<'SH'
#!/usr/bin/env bash
wt="$(dirname "$(git rev-parse --show-toplevel)")/$1"
git worktree add -q "$wt" "$1" 2>/dev/null || git worktree add -q "$wt" -b "$1"
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
has "kickoff points at repo CLAUDE.md" "$KF" 'The repo `CLAUDE.md` loads automatically'
if grep -qF 'session-label.sh' "$KF"; then r=yes; else r=no; fi
check "kickoff leaves labelling to the skill" no "$r"
has "kickoff names the issue command" "$KF" "gh issue create -R IdahoEv/dotfiles"
has "kickoff states the scope rule" "$KF" "every project"
has "kickoff loads /workflow" "$KF" "/workflow"
has "kickoff points at delivery.md" "$KF" "delivery.md"

has "launches via start-ticket --tab-only" "$ST_LOG" "--tab-only $ROOT/proj/workflow $KF"
has "label identifies the project" "$ST_LOG" "label=widgets workflow"

rm -f "$ST_LOG"
out="$(run)"; rc=$?
check "second run succeeds" "0" "$rc"
check "second run reuses the worktree" "1" "$(wt_count)"
case "$out" in *"reused=yes"*) r=yes ;; *) r=no ;; esac
check "reports reused=yes on re-run" yes "$r"
check "reuse does not launch a second session" "no" "$([ -e "$ST_LOG" ] && echo yes || echo no)"
case "$out" in *"launched=no"*) r=yes ;; *) r=no ;; esac
check "reports launched=no on reuse" yes "$r"
out="$(run --relaunch)"
has "--relaunch launches on reuse" "$ST_LOG" "--tab-only $ROOT/proj/workflow"

rm -f "$SESSION_LABEL_STATE_FILE"
out="$(run)"; rc=$?
check "no state file (iTerm/none launcher): runs" "0" "$rc"
echo '{"name":"widgets Governor"}' > "$SESSION_LABEL_STATE_FILE"

rm -f "$ST_LOG"
(cd "$P" && "$WS" --force >/dev/null 2>&1)
echo '{"name":"anything"}' > "$SESSION_LABEL_STATE_FILE"
(cd "$P" && "$WS" --force >/dev/null 2>&1); check "--force bypasses the governor check" "0" "$?"

# wm --init layout: a bare container whose worktrees are subdirectories, so
# gt::main_root is the container, not a checkout.
B="$ROOT/bareproj"
git clone -q --bare "$P" "$B/.bare"
git -C "$B/.bare" branch -q -D workflow
printf 'gitdir: ./.bare\n' > "$B/.git"
git -C "$B" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git -C "$B" worktree add -q "$B/main" "$(git -C "$P" branch --show-current)"
mkdir -p "$B/main/.claude"; printf 'BARE-GOVERNOR-MARKER\n' > "$B/main/.claude/governor.md"
echo '{"name":"bareproj Governor"}' > "$SESSION_LABEL_STATE_FILE"
(cd "$B/main" && "$WS" >/dev/null); check "bare layout: runs" "0" "$?"
has "bare layout: kickoff carries governor.md" "$TMPDIR/bareproj-kickoff-workflow.md" "BARE-GOVERNOR-MARKER"
check "bare layout: workflow worktree is a sibling of main" "yes" "$([ -d "$B/workflow" ] && echo yes || echo no)"

# A worktree dir deleted by hand leaves a prunable entry; it must not count as reuse.
S="$ROOT/proj3"; git init -q "$S/p"; git -C "$S/p" commit -q --allow-empty -m init
git -C "$S/p" worktree add -q "$S/workflow" -b workflow; rm -rf "$S/workflow"
git -C "$S/p" worktree add -q "$S/other" -b other; rm -rf "$S/other"
echo '{"name":"p Governor"}' > "$SESSION_LABEL_STATE_FILE"
out="$(cd "$S/p" && "$WS" 2>/dev/null)"; rc=$?
check "stale worktree entry: runs" "0" "$rc"
case "$out" in *"reused=no"*) r=yes ;; *) r=no ;; esac
check "stale worktree entry: recreated, not reused" yes "$r"
check "stale worktree entry: dir exists" yes "$([ -d "$S/workflow" ] && echo yes || echo no)"
check "other branches' stale entries are left alone" "1" "$(git -C "$S/p" worktree list --porcelain | grep -c 'refs/heads/other$')"

echo '{"color":"blue"}' > "$SESSION_LABEL_STATE_FILE"
(cd "$S/p" && "$WS" --relaunch >/dev/null 2>&1); check "state file without a title: trusts the caller" "0" "$?"

printf '#!/usr/bin/env bash\nexit 1\n' > "$ROOT/st-fail"; chmod +x "$ROOT/st-fail"
out="$(cd "$S/p" && WORKFLOW_SESSION_START="$ROOT/st-fail" "$WS" --relaunch 2>/dev/null)"; rc=$?
check "failed launch exits non-zero" "1" "$rc"
case "$out" in *"kickoff="*"launched=no"*) r=yes ;; *) r=no ;; esac
check "failed launch still reports paths and launched=no" yes "$r"

# wm can exit non-zero after creating the worktree (e.g. a failed dependency
# install); the session must still open.
F="$ROOT/proj2"; git init -q "$F/p"; git -C "$F/p" commit -q --allow-empty -m init
cat > "$ROOT/wm-fail" <<'SH'
#!/usr/bin/env bash
git worktree add -q "$(dirname "$(git rev-parse --show-toplevel)")/$1" -b "$1"
echo "npm install failed" >&2; exit 1
SH
chmod +x "$ROOT/wm-fail"
rm -f "$ST_LOG"; echo '{"name":"p Governor"}' > "$SESSION_LABEL_STATE_FILE"
out="$(cd "$F/p" && WORKFLOW_SESSION_WM="$ROOT/wm-fail" "$WS" 2>/dev/null)"; rc=$?
check "wm failing after creating the worktree: runs" "0" "$rc"
has "wm failing after creating the worktree: launches" "$ST_LOG" "--tab-only $F/workflow"

check "project checkout stays clean" "" "$(git -C "$P" status --porcelain | grep -v '^?? ')"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
