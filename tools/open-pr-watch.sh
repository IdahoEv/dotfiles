#!/usr/bin/env bash
# open-pr-watch.sh — the detached post-PR leg of /open-pr: poll for review
# comments, then notify. Started by open-pr.sh; runs fine by hand.
#
#   open-pr-watch.sh <pr_number>
#
# On exit of github-review-poll.sh: stamps REVIEW → REVIEWED when polling has
# ended without comments (timeout, no PR, signed off, or a reviewer couldn't run), sends a macOS notification, and
# emits a pr.watch event. $OPEN_PR_POLL overrides the poll script.
#
# Poll exit codes: 0 comments arrived, 1 timeout, 2 no PR, 3 signed off,
# 4 a reviewer couldn't run.

set -uo pipefail

_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"

pr="${1:-}"
[[ "$pr" =~ ^[1-9][0-9]*$ ]] || { printf 'open-pr-watch: usage: open-pr-watch.sh <pr_number>\n' >&2; exit 1; }

poll="${OPEN_PR_POLL:-$HOME/.claude/skills/github-review-procedure/github-review-poll.sh}"
rc=0
"$poll" "$pr" || rc=$?

case "$rc" in
  0) outcome=comments;  msg="review comments arrived: run /github-review-comments" ;;
  1) outcome=timeout;   msg="no review activity before the poll timed out" ;;
  2) outcome=no-pr;     msg="no PR found" ;;
  3) outcome=signed-off; msg="reviewers signed off; ready to merge" ;;
  4) outcome=reviewer-unavailable; msg="a reviewer couldn't run" ;;
  *) outcome=error;     msg="poll failed (exit $rc)" ;;
esac

case "$rc" in
  1|2|3|4) "$SCRIPT_DIR/agent-phase.sh" --no-review >/dev/null 2>&1 || true ;;
esac

"$SCRIPT_DIR/wf-event.sh" pr.watch "pr_number=$pr" "exit_code=$rc" "outcome=$outcome" >/dev/null 2>&1 || true

if command -v osascript >/dev/null 2>&1; then
  # Quotes and backslashes would end the AppleScript string early.
  safe="${msg//[\"\\]/}"
  osascript -e "display notification \"$safe\" with title \"PR #$pr\"" >/dev/null 2>&1 || true
fi

printf 'pr=%s exit_code=%s outcome=%s: %s\n' "$pr" "$rc" "$outcome" "$msg"
exit 0
