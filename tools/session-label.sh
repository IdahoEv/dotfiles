#!/usr/bin/env bash
# session-label.sh — set a background session's title and/or color.
#
#   session-label.sh --title "{project} Governor" --color project
#   session-label.sh --title Workflow --color green
#   session-label.sh --color project          # /start: keep the title, color only
#
#   --title TEXT   "{project}" expands to the current repo's name
#   --color NAME   one of the /color palette, or "project" to resolve the repo's
#                  color (below)
#   --show         print the repo's project color and exit
#
# Same mechanism and caveats as agent-phase.sh: writes the job's state.json
# atomically, because `/rename` and `/color` can't be driven from a script or
# a bg session. state.json is Claude Code internals, so this no-ops (exit 0)
# anywhere it isn't looking at a bg session it understands. Whether the agent
# view honors a color written this way is unverified; the key exists in
# state.json for sessions colored by hand.
#
# Project color, first hit wins:
#   1. `color=` in start-ticket.conf, via the usual per-key lookup (worktree
#      .start-ticket.conf -> main repo -> config overlay -> ~/.config/start-ticket)
#   2. project-colors (next to this script), keyed by the directory holding the
#      repo's .git, so every worktree of Kardashev resolves to "Kardashev"
#   3. none: the color is left alone
# A value outside the palette is an error, not a silent skip.
#
# Exit codes: 0 on success and on every "not applicable" case; 1 on usage
# errors (unknown color, bad flag).

set -euo pipefail

die() { printf 'session-label: %s\n' "$*" >&2; exit 1; }

PALETTE="red blue green yellow purple orange pink cyan"
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
here="$(cd -P "$(dirname "$_src")" && pwd)"
# shellcheck source=lib/repo-facts.sh
. "$here/lib/repo-facts.sh"
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

# Conf value first, then project-colors; validated here so --show and
# --color project reject a typo the same way, naming the file to fix.
resolve_color() {  # <project> -> color or empty
  local c src=start-ticket.conf
  # Trimmed after lookup: conf_get keeps trailing blanks and CRs, and a blank
  # value must fall through to project-colors rather than fail the palette check.
  c="$(gt::conf_get color 2>/dev/null | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]' || true)"
  if [ -z "$c" ] && [ -n "$1" ]; then c="$(project_color "$1")"; src=project-colors; fi
  [ -z "$c" ] && return 0
  case " $PALETTE " in *" $c "*) ;; *) die "color '$c' in $src is not in the palette ($PALETTE)" ;; esac
  printf '%s' "$c"
}

proj="$(project || true)"

if [ "$show" = 1 ]; then
  resolve_color "$proj"
  exit 0
fi

[ -n "$title$color" ] || die "nothing to do: pass --title and/or --color"

if [ "$color" = project ]; then
  # A bad color must not block the title (the statusline keys on the governor
  # title): resolve_color has already printed the error, so drop the color and
  # exit 1 once the title is written.
  color="$(resolve_color "$proj")" || { color=""; trap 'exit 1' EXIT; }
fi
if [ -n "$color" ]; then
  case " $PALETTE " in *" $color "*) ;; *) die "unknown color '$color' (expected: $PALETTE)" ;; esac
fi
# An unknown project would leave a stray " Governor" title; skip the title instead.
if [[ "$title" == *"{project}"* && -z "$proj" ]]; then title=""; fi
title="${title//\{project\}/$proj}"
[ -n "$title$color" ] || exit 0

state_file="${SESSION_LABEL_STATE_FILE:-${CLAUDE_JOB_DIR:+$CLAUDE_JOB_DIR/state.json}}"
[ -n "$state_file" ] && [ -r "$state_file" ] && [ -w "$state_file" ] || exit 0
command -v python3 >/dev/null || exit 0

TITLE="$title" COLOR="$color" python3 - "$state_file" <<'PY'
import json, os, stat, sys, tempfile

path = sys.argv[1]
title, color = os.environ["TITLE"], os.environ["COLOR"]

try:
    with open(path) as fh:
        state = json.load(fh)
except (OSError, ValueError):
    sys.exit(0)          # unreadable or mid-write by the daemon; cosmetic, skip

if not isinstance(state, dict):
    sys.exit(0)
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
    os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))   # mkstemp is 0600
    os.replace(tmp, path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
PY
