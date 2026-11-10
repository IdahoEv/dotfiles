#!/usr/bin/env bash
# Fetch the dotfiles repo at one commit so a non-Claude cloud agent can run its
# real workflow command files through workflow/adapters/<host>.md.
# Invoke with bash; no executable bit is required.
#
#   WORKFLOW_REF   branch, tag, or full commit SHA to use (default: main)
#                  Needs outbound HTTPS to codeload.github.com only (no GitHub API call).
#
#   WORKFLOW_FETCH "archive" (codeload tarball only) or "raw" (raw.githubusercontent.com files only);
#                  default tries the archive, then falls back to raw.
#   WORKFLOW_SRC   a local clone to install from instead of downloading (committed tree at
#                  WORKFLOW_REF, default HEAD). For sessions where GitHub access is scoped to
#                  other repositories and codeload.github.com refuses this one.
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
# Trust: in raw mode the manifest and the files come from the same ref over TLS, so the sha256 check
# proves a consistent snapshot, not authenticity. A pinned full SHA proves the bytes are fixed (and,
# via the archive, that they are that commit), not that the commit was reviewed or is on this repo's
# branches (raw serves any commit in the fork network).
#
# Prints key=value lines on stdout; exits non-zero and uses no cached copy on any failure.

set -euo pipefail

readonly repo="IdahoEv/dotfiles"
readonly ref="${WORKFLOW_REF:-main}"
readonly temp_root="${TMPDIR:-/tmp}"
readonly install_mode="${WORKFLOW_INSTALL:-}"
readonly curl_opts=(--fail --silent --show-error --location --connect-timeout 10 --max-time 60 --retry 2 --proto =https --proto-redir =https)
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

# Prints the commit an archive was cut from (GitHub records it in the pax global header).
archive_commit() { # archive_commit <file.tar.gz>
  python3 -I - "$1" <<'PY'
import re, sys, tarfile
try:
    with tarfile.open(sys.argv[1], "r:gz") as tf:
        value = tf.pax_headers.get("comment", "")
except (tarfile.TarError, OSError) as exc:
    sys.exit(f"could not read the archive: {exc}")
if re.fullmatch(r"[0-9a-f]{40}", value) is None:
    sys.exit("the archive does not record a commit id")
print(value)
PY
}

[[ -z "$install_mode" || "$install_mode" == claude ]] \
  || fail "Invalid WORKFLOW_INSTALL '$install_mode'; only 'claude' is supported."

command -v curl >/dev/null 2>&1 || fail "curl is required to retrieve the committed workflow."
command -v tar >/dev/null 2>&1 || fail "tar is required to unpack the committed workflow."

if [[ -n "${WORKFLOW_SRC:-}" ]]; then
  # git validates the ref against the clone; only keep it from reading as an option.
  [[ "${WORKFLOW_REF:-HEAD}" != -* ]] || fail "Invalid WORKFLOW_REF '${WORKFLOW_REF}'."
elif [[ ! "$ref" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ || "$ref" == *..* ]]; then
  fail "Invalid WORKFLOW_REF '$ref'; use a branch, tag, or full commit SHA."
fi

work_dir="$(mktemp -d "${temp_root%/}/dotfiles-workflow.XXXXXX")" \
  || fail "Could not create a temporary directory."
trap 'rm -rf "$work_dir"' EXIT

if [[ -n "${WORKFLOW_SRC:-}" ]]; then
  # A local clone of the repo (e.g. one a cloud session attached and cloned itself). The
  # committed tree at the ref is exported, so uncommitted edits in the clone are never installed.
  command -v git >/dev/null 2>&1 || fail "git is required to read WORKFLOW_SRC."
  src_ref="${WORKFLOW_REF:-HEAD}"
  commit_sha="$(git -C "$WORKFLOW_SRC" rev-parse --verify --quiet "${src_ref}^{commit}")" \
    || fail "Ref '$src_ref' not found in WORKFLOW_SRC '$WORKFLOW_SRC' (is it a git checkout? shallow or single-branch clones only have the refs they fetched; see git's message above). No cached workflow was used."
  case "$(git -C "$WORKFLOW_SRC" remote get-url origin 2>/dev/null || true)" in
    *"${repo}"*) ;;
    *) printf 'cloud-workflow-bootstrap: WARN: %s does not have origin %s; commit %s may not exist upstream\n' "$WORKFLOW_SRC" "$repo" "$commit_sha" >&2 ;;
  esac
  archive_url="https://github.com/${repo}/commit/${commit_sha}"
  root="$work_dir/repo"
  mkdir "$root"
  git -C "$WORKFLOW_SRC" archive "$commit_sha" | tar -x -C "$root" \
    || fail "Could not export $commit_sha from $WORKFLOW_SRC. No cached workflow was used."
else
  command -v python3 >/dev/null 2>&1 || fail "python3 is required (commit id and manifest checks)."
  readonly fetch_mode="${WORKFLOW_FETCH:-}"
  [[ -z "$fetch_mode" || "$fetch_mode" == archive || "$fetch_mode" == raw ]] \
    || fail "Invalid WORKFLOW_FETCH '$fetch_mode'; use 'archive' or 'raw'."
  root="$work_dir/repo"
  have_archive=""

  if [[ "$fetch_mode" != raw ]]; then
    # One download, no GitHub API: the archive for a branch or tag records the commit it was cut from
    # in its pax header, so the SHA comes from the bytes we actually unpack.
    archive_url="https://codeload.github.com/${repo}/tar.gz/${ref}"
    if curl "${curl_opts[@]}" "$archive_url" -o "$work_dir/repo.tar.gz"; then
      have_archive=1
    elif [[ "$fetch_mode" == archive ]]; then
      fail "Could not fetch $archive_url; check that the ref exists and that the environment allows codeload.github.com. No cached workflow was used."
    else
      printf 'cloud-workflow-bootstrap: archive download failed (a 403 means this session cannot read the repo through codeload); fetching files from raw.githubusercontent.com instead\n' >&2
    fi
  fi

  if [[ -n "$have_archive" ]]; then
    commit_sha="$(archive_commit "$work_dir/repo.tar.gz")" \
      || fail "Could not determine the commit of $archive_url. No cached workflow was used."
    if [[ "$ref" =~ ^[0-9a-f]{40}$ && "$ref" != "$commit_sha" ]]; then
      fail "Pinned WORKFLOW_REF $ref but the archive is commit $commit_sha. No cached workflow was used."
    fi
    # Report the immutable form so a run can be reproduced exactly.
    archive_url="https://codeload.github.com/${repo}/tar.gz/${commit_sha}"
    mkdir "$root"
    tar -xzf "$work_dir/repo.tar.gz" -C "$root" --strip-components=1 \
      || fail "Could not extract the archive from $archive_url. No cached workflow was used."
    rm -f "$work_dir/repo.tar.gz"
  else
    # Sessions whose GitHub access is scoped to other repositories get 403 from the API and
    # codeload for this one, but raw.githubusercontent.com serves public files. workflow/manifest.txt
    # lists every file with its sha256; each is fetched and verified, so a push landing mid-download
    # (or a stale CDN copy) fails closed instead of installing a mixed snapshot.
    raw_base="https://raw.githubusercontent.com/${repo}/${ref}"
    archive_url="$raw_base/workflow/manifest.txt"
    curl "${curl_opts[@]}" "$archive_url" -o "$work_dir/manifest.txt" \
      || fail "Could not fetch $archive_url; check that the ref exists (refs older than workflow/manifest.txt cannot use the raw fallback) and that the environment allows raw.githubusercontent.com. No cached workflow was used."
    python3 -I - "$work_dir/manifest.txt" > "$work_dir/files.txt" <<'PY' || fail "workflow/manifest.txt is malformed. No cached workflow was used."
import re, sys
line_re = re.compile(r"^([0-9a-f]{64})  (644|755)  ([A-Za-z0-9._/-]+)$")
seen = set()
for raw in open(sys.argv[1], encoding="utf-8").read().splitlines():
    m = line_re.match(raw)
    if not m or m.group(3).startswith("/") or ".." in m.group(3).split("/") or m.group(3) in seen:
        sys.exit(f"bad manifest line: {raw!r}")
    seen.add(m.group(3))
    print(m.group(3))
if not seen:
    sys.exit("empty manifest")
PY
    mkdir "$root"
    xargs -P 8 -I{} curl "${curl_opts[@]}" --create-dirs "$raw_base/{}" -o "$root/{}" < "$work_dir/files.txt" \
      || fail "Could not fetch every file listed in $archive_url. No cached workflow was used."
    python3 -I - "$work_dir/manifest.txt" "$root" <<'PY' || fail "A fetched file does not match workflow/manifest.txt (a push may have landed mid-download or the CDN is stale: retry in a few minutes or pin WORKFLOW_REF to a full SHA; if it persists, workflow/manifest.txt is stale on this ref and needs tools/workflow-manifest.sh --write). No cached workflow was used."
import hashlib, os, sys
manifest, root = sys.argv[1:]
for raw in open(manifest, encoding="utf-8").read().splitlines():
    digest, mode, path = raw.split("  ", 2)
    full = os.path.join(root, path)
    with open(full, "rb") as fh:
        if hashlib.sha256(fh.read()).hexdigest() != digest:
            sys.exit(f"hash mismatch: {path}")
    os.chmod(full, int(mode, 8))
PY
    if [[ "$ref" =~ ^[0-9a-f]{40}$ ]]; then
      commit_sha="$ref"
    else
      # raw has no commit id for a branch; stamp the manifest digest instead (pin a SHA for an exact one).
      commit_sha="manifest-$(python3 -I -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()[:12])' "$work_dir/manifest.txt")"
    fi
  fi
fi

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
if [[ -n "${WORKFLOW_SRC:-}" ]]; then source_ref="local:$src_ref"; else source_ref="$ref"; fi
printf 'workflow_source_ref=%s\n' "$source_ref"
printf 'workflow_source_url=%s\n' "$archive_url"
printf 'workflow_root=%s\n' "$root"
printf 'workflow_bin=%s\n' "$bin_dir"
