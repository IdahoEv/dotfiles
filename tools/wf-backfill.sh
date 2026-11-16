#!/usr/bin/env bash
# wf-backfill.sh — recover review telemetry (local finding text/SHAs/models, or
# bot findings from merged PRs). See tools/lib/wf_backfill.py.
#
#   wf-backfill.sh --pr 150 --pr 149 [--repo owner/repo] [--dry-run]
#   wf-backfill.sh --branch 140-some-branch
#   wf-backfill.sh --bot --pr 173 [--repo owner/repo] [--dry-run]
#   wf-backfill.sh --bot --since 2026-11-11 [--repo owner/repo] [--dry-run]

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/wf_backfill.py" "$@"
