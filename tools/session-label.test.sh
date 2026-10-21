#!/usr/bin/env bash
# session-label.test.sh — behavioral checks for session-label.sh color resolution
# (conf `color` key → project-colors → none).
#
#   session-label.test.sh
#
# Plain script, exits non-zero on failure. HOME is a temp dir so the real
# ~/.config can't leak in.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SL="$TOOLS/session-label.sh"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/session-label-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME"
unset GIT_TOOLS_PROJECTS_DIR CLAUDE_JOB_DIR
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export SESSION_LABEL_COLORS_FILE="$ROOT/project-colors"
export SESSION_LABEL_STATE_FILE="$ROOT/state.json"
OV="$HOME/.config/git-tools/projects/acme/widgets"

git init -q "$ROOT/widgets"
git -C "$ROOT/widgets" commit -q --allow-empty -m init
git -C "$ROOT/widgets" remote add origin git@github.com:acme/widgets.git
git -C "$ROOT/widgets" worktree add -q "$ROOT/wt" -b feature

show()  { (cd "$ROOT/wt" && "$SL" --show 2>&1); }
state() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("color",""))' "$SESSION_LABEL_STATE_FILE"; }

check "no color anywhere" "" "$(show)"

printf 'widgets blue\n' > "$ROOT/project-colors"
check "falls back to project-colors" "blue" "$(show)"

mkdir -p "$OV"; printf 'color=cyan\n' > "$OV/start-ticket.conf"
check "overlay color beats project-colors" "cyan" "$(show)"

printf 'color=Pink\n' > "$ROOT/widgets/.start-ticket.conf"
check "repo conf beats overlay, case-folded" "pink" "$(show)"
rm "$ROOT/widgets/.start-ticket.conf"

echo '{"name":"x"}' > "$SESSION_LABEL_STATE_FILE"
(cd "$ROOT/wt" && "$SL" --color project)
check "--color project writes conf color" "cyan" "$(state)"

printf 'color=mauve\n' > "$OV/start-ticket.conf"
out="$(show)"
case "$out" in *"mauve"*"start-ticket.conf"*|*"start-ticket.conf"*"mauve"*) r=yes ;; *) r=no ;; esac
check "--show rejects bad conf color, naming it" "yes" "$r"
(cd "$ROOT/wt" && "$SL" --color project >/dev/null 2>&1); check "--color project rejects bad conf color" "1" "$?"
check "state untouched by rejected color" "cyan" "$(state)"
(cd "$ROOT/wt" && "$SL" --title "{project} Governor" --color project >/dev/null 2>&1); check "bad color still exits 1 with title" "1" "$?"
check "title survives bad color" "widgets Governor" "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$SESSION_LABEL_STATE_FILE")"

printf 'color=green \r\n' > "$OV/start-ticket.conf"
check "trailing space and CR trimmed" "green" "$(show)"
printf 'color= \n' > "$OV/start-ticket.conf"
check "blank conf value falls through to project-colors" "blue" "$(show)"

printf 'widgets teal\n' > "$ROOT/project-colors"; rm "$OV/start-ticket.conf"
(cd "$ROOT/wt" && "$SL" --color project >/dev/null 2>&1); check "bad project-colors entry still rejected" "1" "$?"

check "project checkout stays clean" "" "$(git -C "$ROOT/widgets" status --porcelain)"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
