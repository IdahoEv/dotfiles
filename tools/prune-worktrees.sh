#!/usr/bin/env bash
# prune-worktrees.sh — CLI of lib/prune_worktrees.py; dry-run report of stale
# worktrees and merged branches, removal with --yes.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/prune_worktrees.py" "$@"
