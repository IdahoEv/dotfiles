#!/usr/bin/env bash
# wf-report.sh — summarize workflow telemetry (docs/workflow-telemetry.md).
#
#   wf-report.sh                       # runs active in the last 14 days
#   wf-report.sh --since 30d --detail  # plus per-run breakdowns
#   wf-report.sh --run idahoev/dotfiles#40
#   wf-report.sh --json
#   wf-report.sh --prune 90            # drop events older than 90 days

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/wf_report.py" "$@"
