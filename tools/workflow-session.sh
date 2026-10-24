#!/usr/bin/env bash
# workflow-session.sh — from a governor session, open (or reuse) the project's
# `workflow` worktree and start a session there.
#
#   workflow-session.sh [--force] [--relaunch]
#
#   --force      skip the governor-session check
#   --relaunch   start a session even when the worktree already existed
#
# A governor session stays in the primary worktree and writes no code, so
# /workflow's config edits happen in a separate session. The kickoff carries the
# project's governor.md, a pointer to its CLAUDE.md, and the scope rule (project
# changes here, all-project changes as a dotfiles issue). The session starts via
# `start-ticket.sh --tab-only`, so the `launcher=` setting (iterm|bg|none) applies.
#
# The caller (the /workflow skill) is the real governor gate. This only refuses
# when a bg session's state.json names a non-governor title; with no state file
# (iTerm, none), no title, or an unreadable one, it trusts the caller.
#
# A reused worktree gets no new session by default: one may still be live in it,
# and two sessions editing one checkout collide.
#
# stdout: worktree= kickoff= branch= reused=yes|no launched=yes|no
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

force=0 relaunch=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force) force=1; shift ;;
    --relaunch) relaunch=1; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0 ;;
    *) die "unknown flag: $1" ;;
  esac
done

session_title() {  # rc 1 when there is no readable state file or title to judge by
  local f="${SESSION_LABEL_STATE_FILE:-${CLAUDE_JOB_DIR:+$CLAUDE_JOB_DIR/state.json}}"
  [ -n "$f" ] && [ -r "$f" ] && command -v python3 >/dev/null || return 1
  python3 -c 'import json,sys
try: n=json.load(open(sys.argv[1])).get("name","")
except Exception: sys.exit(1)
if not n: sys.exit(1)
print(n)' "$f"
}

main="$(gt::main_root)"
[ -n "$main" ] || die "not inside a git repo"
project="$(basename "$main")"
# In a `wm --init` layout main_root is the bare container: no .claude/ and not
# a work tree. The governor's own checkout is both.
top="$(git rev-parse --show-toplevel)"

if [ "$force" = 0 ] && title="$(session_title)"; then
  case "$title" in
    *" Governor") ;;
    *) die "not a governor session (title '$title' does not end ' Governor'); this opens a separate workflow session for a governor to use" ;;
  esac
fi

workflow_worktree() {
  git -C "$main" worktree list --porcelain | awk -v b="refs/heads/$BRANCH" '
    /^worktree /{p=substr($0,10)} $1=="branch" && $2==b {print p; exit}'
}

wt="$(workflow_worktree)"
# A dir removed by hand stays listed and would pass as reusable. Drop only this
# entry: a repo-wide prune would also drop other branches' temporarily missing ones.
if [ -n "$wt" ] && [ ! -d "$wt" ]; then
  git -C "$main" worktree remove --force "$wt" >&2
  wt=""
fi
reused=yes
if [ -z "$wt" ]; then
  reused=no
  # wm can fail after the worktree exists (e.g. dependency install), so ask git
  # rather than trusting its exit code or output.
  (cd "$top" && "$wm" "$BRANCH" >&2) || printf 'workflow-session: worktree-manager exited non-zero; checking for the worktree anyway\n' >&2
  wt="$(workflow_worktree)"
  [ -n "$wt" ] && [ -d "$wt" ] || die "worktree-manager did not create a '$BRANCH' worktree"
fi

kickoff="${TMPDIR:-/tmp}/${project}-kickoff-workflow.md"
{
  printf 'Working on %s workflow config in this worktree. Branch `%s` is checked out.\n\n' "$project" "$BRANCH"
  printf 'Load `/workflow` for authoring guidance (scope routing, prompt-writing rules). Its chezmoi apply/delivery steps do not apply in this session.\n\n'
  printf '## Scope rule\n\n'
  printf -- '- Project-specific changes (the project conf, `CLAUDE.md`, kickoff preamble, `.claude/`) are made here, in this worktree.\n'
  printf -- '- A change that should apply to every project is not made here. File a dotfiles issue with the friction and evidence, or offer to:\n\n'
  printf '      gh issue create -R IdahoEv/dotfiles\n\n'
  if doc="$(gt::find_doc governor.md "$top")"; then
    printf '## Project context (governor.md)\n\n'
    cat "${doc%%$'\t'*}"
    printf '\n\n'
  fi
  printf 'The repo `CLAUDE.md` loads automatically in this worktree.\n'
} > "$kickoff"

launched=no rc=0
if [ "$reused" = no ] || [ "$relaunch" = 1 ]; then
  if GT_LABEL_OVERRIDE="$project workflow" "$start" --tab-only "$wt" "$kickoff"; then
    launched=yes
  else
    rc=1
    printf 'workflow-session: start-ticket.sh failed; session not launched\n' >&2
  fi
else
  printf 'workflow-session: %s already existed; not starting a second session (a live one may be using it). Pass --relaunch to start one anyway.\n' "$wt" >&2
fi

printf 'worktree=%s\nkickoff=%s\nbranch=%s\nreused=%s\nlaunched=%s\n' "$wt" "$kickoff" "$BRANCH" "$reused" "$launched"
exit "$rc"
