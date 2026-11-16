#!/usr/bin/env bash
# mem-guard.sh — per-session memory attribution and launch guard; wraps lib/mem_guard.py.
#
#   mem-guard.sh report [--session <tmux-session>] [--json]
#   mem-guard.sh check  [--force] [--quiet] [--context <name>]    # exit 0 go, 3 blocked
#
# See docs/memory-guard.md.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/mem_guard.py" "$@"
