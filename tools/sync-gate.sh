#!/usr/bin/env bash
# sync-gate.sh — CLI of lib/sync_gate.py; read-only check that local state equals
# what the PR would merge. Exit 0 ready, 2 refused (`verdict=`/`reason=`), 1 usage.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/sync_gate.py" "$@"
