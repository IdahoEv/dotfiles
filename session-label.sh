#!/usr/bin/env bash
# session-label.sh — set a background session's title and/or color.
#
#   session-label.sh --title "{project} Governor" --color project
#   session-label.sh --title Workflow --color green
#   session-label.sh --color project          # /start: keep the title, color only
#
#   --title TEXT   "{project}" expands to the current repo's name
#   --color NAME   one of the /color palette, or "project" to look the repo up
#                  in project-colors (next to this script)
#   --show         print the repo's project color and exit
#
# Same mechanism and caveats as agent-phase.sh: writes the job's state.json
# atomically, because `/rename` and `/color` can't be driven from a script or
# a bg session. state.json is Claude Code internals, so this no-ops (exit 0)
# anywhere it isn't looking at a bg session it understands. Whether the agent
# view honors a color written this way is unverified; the key exists in
# state.json for sessions colored by hand.
#
# Project = the directory holding the repo's .git, so every worktree of
# Kardashev resolves to "Kardashev". An unmapped project gets no color.
#
# Exit codes: 0 on success and on every "not applicable" case; 1 on usage
# errors (unknown color, bad flag).

set -euo pipefail

die() { printf 'session-label: %s\n' "$*" >&2; exit 1; }

PALETTE="red blue green yellow purple orange pink cyan"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
colors_file="${SESSION_LABEL_COLORS_FILE:-$here/project-colors}"

title="" color="" show=0
while [ $# -gt 0 ]; do
  case "$1" in
    --title) title="${2:?--title needs a value}"; shift 2 ;;
    --color) color="${2:?--color needs a value}"; shift 2 ;;
    --show)  show=1; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0 ;;
    *) die "unknown flag: $1" ;;
  esac
done

project() {
  local common
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  basename "$(dirname "$common")"
}

project_color() {  # <project> -> color or empty
  [ -r "$colors_file" ] || return 0
  awk -v p="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" '
    /^[[:space:]]*(#|$)/ { next }
    tolower($1) == p { print tolower($2); exit }' "$colors_file"
}

proj="$(project || true)"

if [ "$show" = 1 ]; then
  [ -n "$proj" ] && project_color "$proj"
  exit 0
fi

[ -n "$title$color" ] || die "nothing to do: pass --title and/or --color"

if [ "$color" = project ]; then
  color="$([ -n "$proj" ] && project_color "$proj" || true)"
elif [ -n "$color" ]; then
  case " $PALETTE " in *" $color "*) ;; *) die "unknown color '$color' (expected: $PALETTE)" ;; esac
fi
title="${title//\{project\}/$proj}"

state_file="${SESSION_LABEL_STATE_FILE:-${CLAUDE_JOB_DIR:+$CLAUDE_JOB_DIR/state.json}}"
[ -n "$state_file" ] && [ -r "$state_file" ] && [ -w "$state_file" ] || exit 0
command -v python3 >/dev/null || exit 0

TITLE="$title" COLOR="$color" python3 - "$state_file" <<'PY'
import json, os, sys, tempfile

path = sys.argv[1]
title, color = os.environ["TITLE"], os.environ["COLOR"]

try:
    with open(path) as fh:
        state = json.load(fh)
except (OSError, ValueError):
    sys.exit(0)          # unreadable or mid-write by the daemon; cosmetic, skip

before = dict(state)
if title:
    state["name"] = title
    # Stops auto-naming from replacing the title with a conversation summary.
    state["nameSource"] = "user"
if color:
    state["color"] = color
if state == before:
    sys.exit(0)

# Atomic replace: the daemon rewrites this file on every status change.
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".state.json.")
try:
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
PY
