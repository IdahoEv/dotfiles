#!/usr/bin/env bash
# workflow-session.sh — from a governor session, open (or reuse) the project's
# `workflow` worktree and start a session there.
#
#   workflow-session.sh [--force]
#
#   --force   skip the governor-session check (testing, non-bg use)
#
# A governor session stays in the primary worktree and writes no code, so
# /workflow's config edits happen in a separate session. The kickoff carries the
# project's governor.md, a pointer to its CLAUDE.md, and the scope rule (project
# changes here, all-project changes as a dotfiles issue). The session starts via
# `start-ticket.sh --tab-only`, so the `launcher=` setting (iterm|bg|none) applies.
#
# Governor detection is the session title ("<project> Governor"), read from the
# job's state.json — the same file session-label.sh writes. Nothing else marks
# a governor session.
#
# stdout: worktree= kickoff= branch= reused=yes|no
# Test seams: WORKFLOW_SESSION_WM, WORKFLOW_SESSION_START, SESSION_LABEL_STATE_FILE.

set -euo pipefail

die() { printf 'workflow-session: %s\n' "$*" >&2; exit 1; }

_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
here="$(cd -P "$(dirname "$_src")" && pwd)"
# shellcheck source=lib/repo-facts.sh
. "$here/lib/repo-facts.sh"

BRANCH=workflow
wm="${WORKFLOW_SESSION_WM:-$(command -v worktree-manager.sh || echo "$here/worktree-manager.sh")}"
start="${WORKFLOW_SESSION_START:-$(command -v start-ticket.sh || echo "$here/start-ticket.sh")}"

force=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force) force=1; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0 ;;
    *) die "unknown flag: $1" ;;
  esac
done

session_title() {
  local f="${SESSION_LABEL_STATE_FILE:-${CLAUDE_JOB_DIR:+$CLAUDE_JOB_DIR/state.json}}"
  [ -n "$f" ] && [ -r "$f" ] && command -v python3 >/dev/null || return 0
  python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("name",""))
except Exception: pass' "$f"
}

main="$(gt::main_root)"
[ -n "$main" ] || die "not inside a git repo"
project="$(basename "$main")"

if [ "$force" = 0 ]; then
  case "$(session_title)" in
    *" Governor") ;;
    *) die "not a governor session (title must end ' Governor'); this opens a separate workflow session for a governor to use" ;;
  esac
fi

wt="$(git -C "$main" worktree list --porcelain | awk -v b="refs/heads/$BRANCH" '
  /^worktree /{p=substr($0,10)} $1=="branch" && $2==b {print p; exit}')"
reused=yes
if [ -z "$wt" ]; then
  reused=no
  wt="$(cd "$main" && "$wm" "$BRANCH" | tail -n 1)"
  [ -d "$wt" ] || die "worktree-manager did not produce a worktree path (got: $wt)"
fi

kickoff="${TMPDIR:-/tmp}/${project}-kickoff-workflow.md"
{
  printf 'Working on %s workflow config in this worktree. Branch `%s` is checked out.\n\n' "$project" "$BRANCH"
  printf 'Load `/workflow` for authoring guidance (scope routing, prompt-writing rules). Its chezmoi apply/delivery steps do not apply in this session.\n\n'
  printf '## Scope rule\n\n'
  printf -- '- Project-specific changes (the project conf, `CLAUDE.md`, kickoff preamble, `.claude/`) are made here, in this worktree.\n'
  printf -- '- A change that should apply to every project is not made here. File a dotfiles issue with the friction and evidence, or offer to:\n\n'
  printf '      gh issue create -R IdahoEv/dotfiles\n\n'
  if doc="$(gt::find_doc governor.md "$main")"; then
    printf '## Project context (governor.md)\n\n'
    cat "${doc%%$'\t'*}"
    printf '\n\n'
  fi
  printf 'The repo `CLAUDE.md` loads automatically in this worktree.\n\n'
  printf 'Cosmetic: run `session-label.sh --title Workflow --color project` (skip if not found; silent outside a background session).\n'
} > "$kickoff"

GT_LABEL_OVERRIDE="$project workflow" "$start" --tab-only "$wt" "$kickoff"

printf 'worktree=%s\nkickoff=%s\nbranch=%s\nreused=%s\n' "$wt" "$kickoff" "$BRANCH" "$reused"
