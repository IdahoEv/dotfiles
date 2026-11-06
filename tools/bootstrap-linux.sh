#!/usr/bin/env bash
# bootstrap-linux.sh — prepare a fresh Debian/Ubuntu/WSL machine for `chezmoi init --apply`.
# Invoke with bash; no executable bit is required. Idempotent; safe to re-run.
#
#   bootstrap-linux.sh [--skip-gh]
#
#   BOOTSTRAP_REF   branch, tag, or SHA to read tools/lib/packages.tsv from when the
#                   script runs without a checkout beside it (default: main)
#
# Installs the apt packages in tools/lib/packages.tsv (core and dev required; search
# best-effort), the GitHub CLI from GitHub's apt repo, the oh-my-posh, chezmoi, uv and
# fnm binaries into ~/.local/bin, fd/bat shims for Debian's renamed binaries, and makes
# zsh the login shell. Binaries and installers are fetched over HTTPS from the projects'
# own sites without checksum verification. Prerequisites: sudo, curl, an apt-based distro.
#
# Exit codes: 0 on success; 1 on any failure (the message says what to do by hand).

set -euo pipefail

readonly curl_opts=(--fail --silent --show-error --location --connect-timeout 10 --max-time 120 --retry 2)
readonly bin_dir="$HOME/.local/bin"
readonly gh_keyring=/etc/apt/keyrings/githubcli-archive-keyring.gpg
readonly gh_list=/etc/apt/sources.list.d/github-cli.list
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

fail() {
  printf 'bootstrap-linux: ERROR: %s\n' "$*" >&2
  exit 1
}

step() { printf 'bootstrap-linux: %s\n' "$*"; }

skip_gh=0
for arg in "$@"; do
  case "$arg" in
    --skip-gh) skip_gh=1 ;;
    *) fail "unknown argument '$arg'; usage: bootstrap-linux.sh [--skip-gh]" ;;
  esac
done

[[ "$(uname -s)" == Linux ]] || fail "this script is for Linux/WSL only."
command -v sudo >/dev/null 2>&1 || fail "sudo is required."
command -v curl >/dev/null 2>&1 || fail "curl is required; run: sudo apt install -y curl"
command -v apt-get >/dev/null 2>&1 || fail "apt-get not found; install the apt column of tools/lib/packages.tsv by hand."

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/bootstrap-linux.XXXXXX")" || fail "could not create a temporary directory."
trap 'rm -rf "$work_dir"' EXIT

fetch() { # fetch <url> <dest>
  curl "${curl_opts[@]}" "$1" -o "$2" \
    || fail "could not fetch $1; check network access (on WSL, see the IPv6 note in docs/bootstrap-linux.md)."
}

manifest="$script_dir/lib/packages.tsv"
if [[ ! -f "$manifest" ]]; then
  manifest="$work_dir/packages.tsv"
  fetch "https://raw.githubusercontent.com/IdahoEv/dotfiles/${BOOTSTRAP_REF:-main}/tools/lib/packages.tsv" "$manifest"
fi

manifest_rows() { grep -v -e '^#' -e '^[[:space:]]*$' "$manifest" || true; }

install_apt_packages() {
  local tier name apt brew required=() optional=() unavailable=() gaps=()
  while IFS=$'\t' read -r tier name apt brew; do
    [[ "$tier" != cask ]] || continue
    case "$apt" in
      builtin|installer:*) ;;
      none) gaps+=("$name") ;;
      *) if [[ "$tier" == search ]]; then optional+=("$apt"); else required+=("$apt"); fi ;;
    esac
  done < <(manifest_rows)

  step "installing apt packages: ${required[*]}"
  sudo apt-get update || fail "apt-get update failed."
  sudo apt-get install -y "${required[@]}" || fail "apt-get install failed."

  local available=() pkg
  for pkg in ${optional[@]+"${optional[@]}"}; do
    if apt-cache show "$pkg" >/dev/null 2>&1; then available+=("$pkg"); else unavailable+=("$pkg"); fi
  done
  if ((${#available[@]})); then
    step "installing optional apt packages: ${available[*]}"
    sudo apt-get install -y "${available[@]}" || fail "apt-get install of optional packages failed."
  fi
  ((${#unavailable[@]} == 0)) || step "not in this distro's apt, skipped: ${unavailable[*]}"
  ((${#gaps[@]} == 0)) || step "no apt equivalent, skipped: ${gaps[*]}"
}

install_gh() {
  if command -v gh >/dev/null 2>&1; then
    step "gh already installed"
    return
  fi
  if ((skip_gh)); then
    step "skipping gh (--skip-gh)"
    return
  fi
  step "installing gh from cli.github.com"
  local arch
  arch="$(dpkg --print-architecture)"
  fetch https://cli.github.com/packages/githubcli-archive-keyring.gpg "$work_dir/gh.gpg"
  printf 'deb [arch=%s signed-by=%s] https://cli.github.com/packages stable main\n' "$arch" "$gh_keyring" > "$work_dir/gh.list"
  {
    sudo mkdir -p "$(dirname "$gh_keyring")" \
      && sudo install -m 0644 "$work_dir/gh.gpg" "$gh_keyring" \
      && sudo install -m 0644 "$work_dir/gh.list" "$gh_list" \
      && sudo apt-get update \
      && sudo apt-get install -y gh
  } || fail "gh install failed; follow https://github.com/cli/cli/blob/trunk/docs/install_linux.md by hand, or re-run with --skip-gh."
}

have_binary() { [[ -x "$bin_dir/$1" ]] || command -v "$1" >/dev/null 2>&1; }

# install_release_binary <name> <url-prefix> <asset-prefix>: skips when the binary is already present.
install_release_binary() {
  local name="$1" url_prefix="$2" asset_prefix="$3" arch
  if have_binary "$name"; then
    step "$name already installed"
    return
  fi
  arch="$(dpkg --print-architecture)"
  case "$arch" in
    amd64|arm64) ;;
    *) fail "unsupported architecture '$arch' for $name." ;;
  esac
  step "installing $name to $bin_dir"
  fetch "$url_prefix/${asset_prefix}${arch}" "$work_dir/$name"
  mkdir -p "$bin_dir"
  chmod +x "$work_dir/$name"
  mv "$work_dir/$name" "$bin_dir/$name"
}

# run_installer <name> <url> [args...]: downloads the project's installer to a file, then runs it.
run_installer() {
  local name="$1" url="$2"
  shift 2
  if have_binary "$name"; then
    step "$name already installed"
    return
  fi
  step "installing $name to $bin_dir"
  mkdir -p "$bin_dir"
  fetch "$url" "$work_dir/$name-install.sh"
  bash "$work_dir/$name-install.sh" "$@" >/dev/null || fail "the $name installer failed; see $url."
}

install_installers() {
  local tier name apt brew
  while IFS=$'\t' read -r tier name apt brew; do
    case "$apt" in
      installer:gh-repo) install_gh ;;
      installer:oh-my-posh) install_release_binary oh-my-posh https://github.com/JanDeDobbeleer/oh-my-posh/releases/latest/download posh-linux- ;;
      installer:chezmoi) install_release_binary chezmoi https://github.com/twpayne/chezmoi/releases/latest/download chezmoi-linux- ;;
      installer:uv) UV_UNMANAGED_INSTALL="$bin_dir" run_installer uv https://astral.sh/uv/install.sh ;;
      installer:fnm) run_installer fnm https://fnm.vercel.app/install --install-dir "$bin_dir" --skip-shell ;;
      installer:*) fail "manifest row '$name' names an unknown installer '$apt'." ;;
    esac
  done < <(manifest_rows)
}

# Debian ships these under different names; the dotfiles and tools expect the upstream ones.
link_renamed_binaries() {
  local upstream debian path
  for pair in fd:fdfind bat:batcat; do
    upstream="${pair%%:*}" debian="${pair##*:}"
    path="$(command -v "$debian" 2>/dev/null || true)"
    if [[ -n "$path" ]] && ! command -v "$upstream" >/dev/null 2>&1; then
      step "linking $upstream -> $debian in $bin_dir"
      mkdir -p "$bin_dir"
      ln -s "$path" "$bin_dir/$upstream"
    fi
  done
}

set_default_shell() {
  local zsh_path current
  zsh_path="$(command -v zsh)" || fail "zsh is not on PATH after install."
  current="$(getent passwd "$(id -un)" | cut -d: -f7 || true)"
  if [[ "$current" == "$zsh_path" || "$current" == */zsh ]]; then
    step "login shell is already zsh"
    return
  fi
  step "setting login shell to $zsh_path"
  sudo chsh -s "$zsh_path" "$(id -un)" || fail "chsh failed; run: sudo chsh -s $zsh_path $(id -un)"
}

install_apt_packages
install_installers
link_renamed_binaries
set_default_shell

step "done. Next: run ~/.local/bin/chezmoi init --apply IdahoEv/dotfiles, then exec zsh"
