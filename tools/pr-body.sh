#!/usr/bin/env bash
# pr-body.sh — assemble PR bodies, save/load the early draft, record the review report.
# CLI of lib/pr_body.py; see its docstring for subcommands.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/pr_body.py" "$@"
