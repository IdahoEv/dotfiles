#!/usr/bin/env bash
# sync-run.sh — CLI of lib/sync_run.py; the deterministic /sync path (fetch, merge
# origin/<base>, push). Exit 0 done, 3 hand back to the model (`handoff=<reason>`),
# 1 usage/precondition error. See the module docstring.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/sync_run.py" "$@"
