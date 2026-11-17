#!/usr/bin/env bash
# merge-run.sh — CLI of lib/merge_run.py; the deterministic /merge path (sync gate,
# gh merge, remote branch delete). Exit 0 merged, 2 stopped (`stopped=<reason>`),
# 1 usage error. See the module docstring.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/merge_run.py" "$@"
