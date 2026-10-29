#!/usr/bin/env bash
# Fetch the canonical ticket-to-PR contract from a pinned dotfiles commit.
# Invoke with bash; no executable bit is required.

set -euo pipefail

readonly repo="IdahoEv/dotfiles"
readonly workflow_path="workflow/ticket-to-pr.md"
readonly api_url="https://api.github.com/repos/${repo}/commits/main"
readonly temp_root="${TMPDIR:-/tmp}"

fail() {
  printf 'codex-cloud-bootstrap: ERROR: %s\n' "$*" >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || fail "curl is required to retrieve the committed workflow."
command -v python3 >/dev/null 2>&1 || fail "python3 is required to validate the GitHub commit response."

commit_json="$(curl --fail --silent --show-error --location \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  "$api_url")" || fail "Could not read $api_url; check network access and GitHub availability. No cached workflow was used."

commit_sha="$(printf '%s' "$commit_json" | python3 -c '
import json, re, sys
try:
    value = json.load(sys.stdin)["sha"]
except (ValueError, KeyError, TypeError):
    sys.exit("response did not contain a commit SHA")
if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
    sys.exit("response contained an invalid commit SHA")
print(value)
')" || fail "GitHub returned an invalid commit response. No cached workflow was used."

work_dir="$(mktemp -d "${temp_root%/}/dotfiles-workflow.XXXXXX")" \
  || fail "Could not create a temporary directory."
workflow_file="$work_dir/ticket-to-pr.md"
workflow_url="https://raw.githubusercontent.com/$repo/$commit_sha/$workflow_path"

if ! curl --fail --silent --show-error --location "$workflow_url" -o "$workflow_file"; then
  rm -rf "$work_dir"
  fail "Could not fetch $workflow_url; check network access and repository visibility. No cached workflow was used."
fi

if ! python3 - "$workflow_file" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
try:
    content = path.read_text(encoding="utf-8")
except (OSError, UnicodeError) as exc:
    sys.exit(f"cannot read workflow: {exc}")
required = (
    "<!-- workflow-contract: ticket-to-pr/v1 -->",
    "## Required behavior",
    "## Safety boundaries",
    "## Completion report",
)
missing = [marker for marker in required if marker not in content]
if not content.strip() or missing:
    sys.exit("workflow is empty or missing required contract markers: " + ", ".join(missing))
PY
then
  rm -rf "$work_dir"
  fail "The committed workflow failed validation at $workflow_url. No cached workflow was used."
fi

cat > "$work_dir/source.txt" <<EOF
repository=$repo
commit=$commit_sha
path=$workflow_path
url=$workflow_url
EOF

printf 'workflow_source_repo=%s\n' "$repo"
printf 'workflow_source_commit=%s\n' "$commit_sha"
printf 'workflow_source_path=%s\n' "$workflow_file"
printf 'workflow_source_url=%s\n' "$workflow_url"
printf 'workflow_source_manifest=%s\n' "$work_dir/source.txt"
