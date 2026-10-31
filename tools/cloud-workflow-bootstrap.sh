#!/usr/bin/env bash
# Fetch the dotfiles repo at one commit so a non-Claude cloud agent can run its
# real workflow command files through workflow/adapters/<host>.md.
# Invoke with bash; no executable bit is required.
#
#   WORKFLOW_REF   branch, tag, or full commit SHA to use (default: main)
#   GITHUB_TOKEN   optional; raises the API rate limit (sent to the API call only)
#
# Prints key=value lines on stdout; exits non-zero and uses no cached copy on any failure.

set -euo pipefail

readonly repo="IdahoEv/dotfiles"
readonly ref="${WORKFLOW_REF:-main}"
readonly temp_root="${TMPDIR:-/tmp}"
readonly curl_opts=(--fail --silent --show-error --location --connect-timeout 10 --max-time 60 --retry 2)
readonly required_files=(
  dot_claude/commands/start.md
  dot_claude/commands/open-pr.md
  workflow/adapters/codex.md
  workflow/adapters/agy.md
  tools/start-ticket.sh
  tools/open-pr.sh
)

fail() {
  printf 'cloud-workflow-bootstrap: ERROR: %s\n' "$*" >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || fail "curl is required to retrieve the committed workflow."
command -v tar >/dev/null 2>&1 || fail "tar is required to unpack the committed workflow."

if [[ ! "$ref" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ || "$ref" == *..* ]]; then
  fail "Invalid WORKFLOW_REF '$ref'; use a branch, tag, or full commit SHA."
fi

if [[ "$ref" =~ ^[0-9a-f]{40}$ ]]; then
  commit_sha="$ref"
else
  command -v python3 >/dev/null 2>&1 || fail "python3 is required to validate the GitHub commit response."
  api_url="https://api.github.com/repos/${repo}/commits/${ref}"
  auth_header=()
  [[ -z "${GITHUB_TOKEN:-}" ]] || auth_header=(-H "Authorization: Bearer $GITHUB_TOKEN")

  commit_json="$(curl "${curl_opts[@]}" \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    ${auth_header[@]+"${auth_header[@]}"} \
    "$api_url")" || fail "Could not read $api_url; check network access, GitHub availability, and the unauthenticated rate limit (60 requests/hour/IP; set GITHUB_TOKEN to raise it). No cached workflow was used."

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
fi

work_dir="$(mktemp -d "${temp_root%/}/dotfiles-workflow.XXXXXX")" \
  || fail "Could not create a temporary directory."
trap 'rm -rf "$work_dir"' EXIT

archive_url="https://codeload.github.com/${repo}/tar.gz/${commit_sha}"
curl "${curl_opts[@]}" "$archive_url" -o "$work_dir/repo.tar.gz" \
  || fail "Could not fetch $archive_url; check network access and repository visibility. No cached workflow was used."

root="$work_dir/repo"
mkdir "$root"
tar -xzf "$work_dir/repo.tar.gz" -C "$root" --strip-components=1 \
  || fail "Could not extract the archive from $archive_url. No cached workflow was used."
rm -f "$work_dir/repo.tar.gz"

missing=()
for file in "${required_files[@]}"; do
  [[ -s "$root/$file" ]] || missing+=("$file")
done
((${#missing[@]} == 0)) \
  || fail "The snapshot at ${commit_sha} is missing required files: ${missing[*]}. No cached workflow was used."

# Tools resolve their own directory through symlinks, so linking keeps their sibling lookups intact.
bin_dir="$work_dir/bin"
mkdir "$bin_dir"
for tool in "$root"/tools/*.sh; do
  [[ "$tool" == *.test.sh ]] || ln -s "$tool" "$bin_dir/$(basename "$tool")"
done
chmod +x "$root"/tools/*.sh

trap - EXIT

printf 'workflow_source_repo=%s\n' "$repo"
printf 'workflow_source_commit=%s\n' "$commit_sha"
printf 'workflow_source_url=%s\n' "$archive_url"
printf 'workflow_root=%s\n' "$root"
printf 'workflow_bin=%s\n' "$bin_dir"
