#!/usr/bin/env bash
# wf-review-gaps.sh — compare closed PR Copilot findings against local review telemetry.
#
#   wf-review-gaps.sh --since 2026-11-01 [--repo owner/repo] [--out report.md]
#   wf-review-gaps.sh --pr 150 --pr 149 [--repo owner/repo]
#   wf-review-gaps.sh --no-gh [--repo owner/repo] [--json]
#
# Writes a local, uncommitted report classifying missed Copilot-valid findings
# and proposing prompt, focus-agent, and model/effort experiments.

set -euo pipefail
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
exec python3 -I "$SCRIPT_DIR/lib/wf_review_gaps.py" "$@"
