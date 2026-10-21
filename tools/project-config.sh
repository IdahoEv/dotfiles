#!/usr/bin/env bash
# project-config.sh — manage the per-project config overlay (see lib/repo-facts.sh).
#
#   project-config.sh dir                  overlay path for the current repo
#   project-config.sh find <name>          "<path><TAB><repo|overlay>", or exit 1
#   project-config.sh init                 scaffold the overlay; never overwrites
#   project-config.sh store-init [<url>]   git-init the projects root (no commits)
#
# The overlay lives outside every project checkout, so nothing in it can be
# committed to a project by accident. Lookup order and precedence: see
# git-tools-usage.md.

set -euo pipefail

die() { printf 'project-config: %s\n' "$*" >&2; exit 1; }

_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
# shellcheck source=lib/repo-facts.sh
. "$SCRIPT_DIR/lib/repo-facts.sh"

need_overlay() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repo"
  OVERLAY="$(gt::overlay_dir)"
  [ -n "$OVERLAY" ] || die "no parseable 'origin' remote — can't key the overlay"
}

cmd_init() {
  need_overlay
  local root t name dest
  root="$(gt::projects_root)"
  mkdir -p "$OVERLAY"
  # No kickoff-preamble template: an empty one is indistinguishable from real
  # config once copied. Create the file when there is something to say.
  for t in "$SCRIPT_DIR"/project-config-templates/*; do
    name="$(basename "$t")"; dest="$OVERLAY/$name"
    if [ -e "$dest" ]; then echo "exists   $dest"; else cp "$t" "$dest"; echo "created  $dest"; fi
  done
  git -C "$root" rev-parse --git-dir >/dev/null 2>&1 \
    || echo "note: $root is not a git repo; run 'project-config.sh store-init <url>' to version it" >&2
}

cmd_store_init() {
  local root url="${1:-}"
  root="$(gt::projects_root)"
  mkdir -p "$root"
  # Test the root itself, not "inside a repo": a store nested under another
  # checkout (e.g. a dotfiles tree) must still get its own repo.
  if [ ! -d "$root/.git" ]; then git init -q "$root"; echo "initialised $root"; fi
  if [ ! -e "$root/.gitignore" ]; then printf '.DS_Store\n*.swp\n*~\n' > "$root/.gitignore"; fi
  if [ -n "$url" ] && ! git -C "$root" remote get-url origin >/dev/null 2>&1; then
    git -C "$root" remote add origin "$url"; echo "origin -> $url"
  fi
  echo "commit and push from $root yourself; its paths name your projects, so keep the remote private"
}

case "${1:-}" in
  dir)        need_overlay; printf '%s\n' "$OVERLAY" ;;
  find)       [ -n "${2:-}" ] || die "usage: find <name>"; gt::find_doc "$2"; echo ;;
  init)       cmd_init ;;
  store-init) cmd_store_init "${2:-}" ;;
  -h|--help|"") sed -n '2,/^$/p' "$0" ;;
  *)          die "unknown command: $1" ;;
esac
