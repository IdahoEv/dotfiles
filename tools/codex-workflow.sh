#!/usr/bin/env bash
set -euo pipefail
source_path="${BASH_SOURCE[0]}"
while [ -h "$source_path" ]; do
  source_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
  source_path="$(readlink "$source_path")"
  [[ "$source_path" = /* ]] || source_path="$source_dir/$source_path"
done
exec python3 -I "$(dirname "$source_path")/lib/codex_workflow.py" "$@"
