#!/usr/bin/env bash
# repo-facts.sh — CLI of lib/repo_facts.py; one subcommand per gt:: function
# (see its docstring). The sourced lib/repo-facts.sh facade forwards here.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/repo_facts.py" "$@"
