#!/usr/bin/env bash
# finalize-run.sh — CLI of lib/finalize_run.py; the deterministic /finalize path.
# Exit 0 done (one-line summary), 2 stopped (nothing touched), 3 hand back to the
# model (`handoff=<reason>`), 1 usage error. See the module docstring.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/finalize_run.py" "$@"
