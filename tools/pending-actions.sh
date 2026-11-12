#!/usr/bin/env bash
# pending-actions.sh — CLI of lib/pending_actions.py: the pending-actions file protocol.
#
#   pending-actions.sh upsert <file> --issue N --action A --detail TEXT [--command CMD]
#   pending-actions.sh has    <file> --issue N --action A     exit 0 if queued, 1 if not
#   pending-actions.sh list   <file>                          issue<TAB>action<TAB>detail<TAB>command
#
# Rows are keyed (issue, action); upsert replaces a matching row in place, so rerunning
# a review never duplicates a queued action. Queues actions only; never touches the tracker.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/pending_actions.py" "$@"
