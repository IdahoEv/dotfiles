#!/usr/bin/env bash
# sibling-worktrees.sh — CLI of lib/sibling_worktrees.py; /open-pr parses its
# TAB-separated records. Same name, same flags, same output bytes as the bash
# implementation it replaced.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/sibling_worktrees.py" "$@"
