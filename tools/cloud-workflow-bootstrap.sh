#!/usr/bin/env bash
# Fetch the dotfiles repo at one commit so a non-Claude cloud agent can run its
# real workflow command files through workflow/adapters/<host>.md.
# Invoke with bash; no executable bit is required.
#
#   WORKFLOW_REF   branch, tag, or full commit SHA to use (default: main)
#   GITHUB_TOKEN   optional; raises the API rate limit (sent to the API call only)
#
#   WORKFLOW_INSTALL  set to "claude" for a Claude Code cloud session: also install the
#                     commands, agents and skills into ~/.claude (or $CLAUDE_CONFIG_DIR) and
#                     link tools/*.sh onto PATH. The snapshot is kept under
#                     $WORKFLOW_HOME (default ~/.cache/dotfiles-workflow/<sha>) instead of
#                     a temp dir, since the installed links point into it.
#                     Also installs a REST-backed `gh` wrapper (tools/cloud-gh-shim.py) in
#                     $WORKFLOW_HOME/shim: cloud sessions block GitHub GraphQL, which plain
#                     `gh issue view` / `gh pr view` / `gh pr create` need.
#   WORKFLOW_BIN_DIR  where to link the tools when installing (default /usr/local/bin if
#                     writable, else ~/.local/bin)
#
# Prints key=value lines on stdout; exits non-zero and uses no cached copy on any failure.

set -euo pipefail

readonly repo="IdahoEv/dotfiles"
readonly ref="${WORKFLOW_REF:-main}"
readonly temp_root="${TMPDIR:-/tmp}"
readonly install_mode="${WORKFLOW_INSTALL:-}"
readonly curl_opts=(--fail --silent --show-error --location --connect-timeout 10 --max-time 60 --retry 2)
readonly required_files=(
  dot_claude/commands/start.md
  dot_claude/commands/open-pr.md
  workflow/adapters/codex.md
  workflow/adapters/agy.md
  tools/start-ticket.sh
  tools/open-pr.sh
)
# Only the Claude install needs these; Codex/AGY runs pinned to an older SHA must still load.
readonly claude_required_files=(
  workflow/adapters/claude-cloud.md
  tools/cloud-gh-shim.py
)

fail() {
  printf 'cloud-workflow-bootstrap: ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -z "$install_mode" || "$install_mode" == claude ]] \
  || fail "Invalid WORKFLOW_INSTALL '$install_mode'; only 'claude' is supported."

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
wanted=("${required_files[@]}")
[[ "$install_mode" != claude ]] || wanted+=("${claude_required_files[@]}")
for file in "${wanted[@]}"; do
  [[ -s "$root/$file" ]] || missing+=("$file")
done
((${#missing[@]} == 0)) \
  || fail "The snapshot at ${commit_sha} is missing required files: ${missing[*]}. No cached workflow was used."

# Tools resolve their own directory through symlinks, so linking keeps their sibling lookups intact.
link_tools() { # link_tools <dir>
  local tool
  mkdir -p "$1"
  for tool in "$root"/tools/*.sh; do
    [[ "$tool" == *.test.sh || ! -f "$tool" || -L "$tool" ]] && continue
    chmod +x "$tool"
    dest="$1/$(basename "$tool")"
    if [[ -e "$dest" && ! -L "$dest" ]]; then
      printf 'cloud-workflow-bootstrap: WARN: %s exists and is not a link; not replacing it\n' "$dest" >&2
      continue
    fi
    ln -sf "$tool" "$dest"
  done
}

if [[ "$install_mode" == claude ]]; then
  # Keep the snapshot: installed links point into it. Replace any copy of the same commit.
  keep="${WORKFLOW_HOME:-$HOME/.cache/dotfiles-workflow}/$commit_sha"
  mkdir -p "$(dirname "$keep")"
  rm -rf "$keep.new"
  mv "$root" "$keep.new"
  rm -rf "$keep"
  mv "$keep.new" "$keep"
  root="$keep"
  rm -rf "$work_dir"

  claude_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
  # Source names carry chezmoi prefixes (executable_); strip them the way chezmoi would.
  # Only commands, agents and skills move: the global CLAUDE.md and settings are chezmoi
  # templates for the user's own machines. Existing files with the same name are replaced.
  for sub in commands agents skills; do
    [[ -d "$root/dot_claude/$sub" ]] || continue
    while IFS= read -r -d '' src; do
      rel="${src#"$root/dot_claude/"}"
      dest="$claude_dir/$(printf '%s' "$rel" | sed -E 's#(^|/)executable_#\1#g')"
      mkdir -p "$(dirname "$dest")"
      cp "$src" "$dest"
      [[ "$(basename "$src")" == executable_* ]] && chmod +x "$dest"
    done < <(find "$root/dot_claude/$sub" -type f -print0)
  done

  bin_dir="${WORKFLOW_BIN_DIR:-}"
  if [[ -z "$bin_dir" ]]; then
    if [[ -w /usr/local/bin ]]; then bin_dir=/usr/local/bin; else bin_dir="$HOME/.local/bin"; fi
  fi
  link_tools "$bin_dir"
  shim_dir="${WORKFLOW_HOME:-$HOME/.cache/dotfiles-workflow}/shim"
  mkdir -p "$shim_dir"
  install -m 0755 "$root/tools/cloud-gh-shim.py" "$shim_dir/gh"
  path_line="export PATH=\"$shim_dir:$bin_dir:\$PATH\""
  if [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
    # A SessionStart hook can export PATH for the whole session through this file.
    touch "$CLAUDE_ENV_FILE"
    grep -qxF "$path_line" "$CLAUDE_ENV_FILE" || printf '%s\n' "$path_line" >> "$CLAUDE_ENV_FILE"
  elif [[ -w "$HOME" ]]; then
    # No hook: persist it for the shells the session starts.
    touch "$HOME/.bashrc"
    grep -qxF "$path_line" "$HOME/.bashrc" || printf '%s\n' "$path_line" >> "$HOME/.bashrc"
  fi
  printf 'workflow_claude_dir=%s\n' "$claude_dir"
  printf 'workflow_shim=%s\n' "$shim_dir"
else
  bin_dir="$work_dir/bin"
  link_tools "$bin_dir"
fi

trap - EXIT

printf 'workflow_source_repo=%s\n' "$repo"
printf 'workflow_source_commit=%s\n' "$commit_sha"
printf 'workflow_source_url=%s\n' "$archive_url"
printf 'workflow_root=%s\n' "$root"
printf 'workflow_bin=%s\n' "$bin_dir"
