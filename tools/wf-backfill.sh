#!/usr/bin/env bash
# wf-backfill.sh — recover review telemetry (finding text, round SHA, reviewer model)
# for PRs reviewed before it was recorded. One-off; see tools/lib/wf_backfill.py.
#
#   wf-backfill.sh --pr 150 --pr 149 [--repo owner/repo] [--dry-run]
#   wf-backfill.sh --branch 140-some-branch

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/wf_backfill.py" "$@"
