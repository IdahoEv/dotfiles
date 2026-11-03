#!/usr/bin/env bash
# bootstrap-linux.sh — prepare a fresh Debian/Ubuntu/WSL machine for `chezmoi init --apply`.
# Invoke with bash; no executable bit is required. Idempotent; safe to re-run.
#
#   bootstrap-linux.sh [--skip-gh]
#
# Installs baseline apt packages, the GitHub CLI (from GitHub's apt repo), the
# oh-my-posh and chezmoi binaries into ~/.local/bin, and makes zsh the login shell.
# Binaries are fetched over HTTPS from the projects' latest GitHub release without
# checksum verification. Prerequisites: sudo, curl, and an apt-based distro.
#
# Exit codes: 0 on success; 1 on any failure (the message says what to do by hand).

set -euo pipefail

readonly curl_opts=(--fail --silent --show-error --location --connect-timeout 10 --max-time 120 --retry 2)
readonly apt_packages=(zsh fzf direnv unzip tmux git curl)
readonly bin_dir="$HOME/.local/bin"
readonly gh_keyring=/etc/apt/keyrings/githubcli-archive-keyring.gpg
readonly gh_list=/etc/apt/sources.list.d/github-cli.list

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
command -v apt-get >/dev/null 2>&1 || fail "apt-get not found; install zsh fzf direnv unzip tmux gh by hand."

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/bootstrap-linux.XXXXXX")" || fail "could not create a temporary directory."
trap 'rm -rf "$work_dir"' EXIT

fetch() { # fetch <url> <dest>
  curl "${curl_opts[@]}" "$1" -o "$2" \
    || fail "could not fetch $1; check network access (on WSL, see the IPv6 note in docs/bootstrap-linux.md)."
}

install_apt_packages() {
  step "installing apt packages: ${apt_packages[*]}"
  sudo apt-get update || fail "apt-get update failed."
  sudo apt-get install -y "${apt_packages[@]}" || fail "apt-get install failed."
}

install_gh() {
  if command -v gh >/dev/null 2>&1; then
    step "gh already installed"
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

# install_release_binary <name> <url-prefix> <asset-prefix>: skips when ~/.local/bin/<name> exists.
install_release_binary() {
  local name="$1" url_prefix="$2" asset_prefix="$3" arch
  if [[ -x "$bin_dir/$name" ]]; then
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
if ((skip_gh)); then step "skipping gh (--skip-gh)"; else install_gh; fi
install_release_binary oh-my-posh https://github.com/JanDeDobbeleer/oh-my-posh/releases/latest/download posh-linux-
install_release_binary chezmoi https://github.com/twpayne/chezmoi/releases/latest/download chezmoi-linux-
set_default_shell

step "done. Next: exec zsh, then run: ~/.local/bin/chezmoi init --apply IdahoEv/dotfiles"
