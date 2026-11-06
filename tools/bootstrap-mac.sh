#!/usr/bin/env bash
# bootstrap-mac.sh — prepare a fresh macOS machine for `chezmoi init --apply`.
# Invoke with bash; no executable bit is required. Idempotent; safe to re-run.
#
#   bootstrap-mac.sh [--skip-casks]
#
#   BOOTSTRAP_REF         branch, tag, or SHA to read tools/lib/packages.tsv from when the
#                         script runs without a checkout beside it (default: main)
#   BOOTSTRAP_BREW_PATHS  space-separated brew locations to look in after PATH
#                         (default: /opt/homebrew/bin/brew /usr/local/bin/brew)
#
# Installs Homebrew if missing, then every brew formula in tools/lib/packages.tsv and
# (unless --skip-casks) every cask. Packages already installed are left alone, never
# upgraded. macOS already ships zsh, so there is no login-shell step. Homebrew's
# installer is fetched over HTTPS from Homebrew's repo without checksum verification.
# Prerequisites: Xcode Command Line Tools (`xcode-select --install`) and network access.
#
# Exit codes: 0 on success; 1 on any failure (the message says what to do by hand).

set -euo pipefail

readonly curl_opts=(--fail --silent --show-error --location --connect-timeout 10 --max-time 120 --retry 2)
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd)"

fail() {
  printf 'bootstrap-mac: ERROR: %s\n' "$*" >&2
  exit 1
}

step() { printf 'bootstrap-mac: %s\n' "$*"; }

skip_casks=0
for arg in "$@"; do
  case "$arg" in
    --skip-casks) skip_casks=1 ;;
    *) fail "unknown argument '$arg'; usage: bootstrap-mac.sh [--skip-casks]" ;;
  esac
done

[[ "$(uname -s)" == Darwin ]] || fail "this script is for macOS only."
command -v curl >/dev/null 2>&1 || fail "curl is required."
xcode-select -p >/dev/null 2>&1 || fail "Xcode Command Line Tools are required; run: xcode-select --install"

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/bootstrap-mac.XXXXXX")" || fail "could not create a temporary directory."
trap 'rm -rf "$work_dir"' EXIT

fetch() { # fetch <url> <dest>
  curl "${curl_opts[@]}" "$1" -o "$2" || fail "could not fetch $1; check network access."
}

manifest="$script_dir/lib/packages.tsv"
if [[ ! -f "$manifest" ]]; then
  manifest="$work_dir/packages.tsv"
  fetch "https://raw.githubusercontent.com/IdahoEv/dotfiles/${BOOTSTRAP_REF:-main}/tools/lib/packages.tsv" "$manifest"
fi

manifest_rows() { grep -v -e '^#' -e '^[[:space:]]*$' "$manifest" || true; }

find_brew() {
  local candidate
  command -v brew 2>/dev/null && return 0
  for candidate in ${BOOTSTRAP_BREW_PATHS:-/opt/homebrew/bin/brew /usr/local/bin/brew}; do
    [[ -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

install_homebrew() {
  if find_brew >/dev/null; then
    step "Homebrew already installed"
    return
  fi
  step "installing Homebrew (asks for your sudo password once; the installer itself runs non-interactively)"
  sudo -v || fail "sudo access is required for the Homebrew installer."
  fetch https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh "$work_dir/homebrew-install.sh"
  NONINTERACTIVE=1 /bin/bash "$work_dir/homebrew-install.sh" \
    || fail "the Homebrew installer failed; see https://brew.sh for manual steps."
  find_brew >/dev/null || fail "Homebrew installed but brew was not found; open a new terminal and re-run."
}

install_packages() {
  local brew tier name apt pkg formulae=() casks=() gaps=() missing_formulae=() missing_casks=() failed_casks=()
  brew="$(find_brew)"
  eval "$("$brew" shellenv)"

  while IFS=$'\t' read -r tier name apt pkg; do
    case "$pkg" in
      builtin) ;;
      none) gaps+=("$name") ;;
      installer:*) fail "manifest row '$name' names an installer '$pkg'; brew rows must be packages." ;;
      *) if [[ "$tier" == cask ]]; then casks+=("$pkg"); else formulae+=("$pkg"); fi ;;
    esac
  done < <(manifest_rows)

  for pkg in ${formulae[@]+"${formulae[@]}"}; do
    "$brew" list --formula "$pkg" >/dev/null 2>&1 || missing_formulae+=("$pkg")
  done
  if ((${#missing_formulae[@]})); then
    step "installing formulae: ${missing_formulae[*]}"
    "$brew" install "${missing_formulae[@]}" || fail "brew install failed; re-run to retry the remaining packages."
  else
    step "all formulae already installed"
  fi

  if ((skip_casks)); then
    step "skipping casks (--skip-casks)"
  else
    for pkg in ${casks[@]+"${casks[@]}"}; do
      "$brew" list --cask "$pkg" >/dev/null 2>&1 || missing_casks+=("$pkg")
    done
    # Apps copied to /Applications by hand are invisible to `brew list`; one conflict must not block the rest.
    for pkg in ${missing_casks[@]+"${missing_casks[@]}"}; do
      step "installing cask: $pkg"
      "$brew" install --cask "$pkg" || failed_casks+=("$pkg")
    done
    if ((${#failed_casks[@]})); then
      step "WARNING: casks not installed (often an app already in /Applications; install or adopt by hand): ${failed_casks[*]}"
    elif ((${#missing_casks[@]} == 0)); then
      step "all casks already installed"
    fi
  fi

  ((${#gaps[@]} == 0)) || step "no brew equivalent, skipped: ${gaps[*]}"
}

install_homebrew
install_packages

step "done. Next: run chezmoi init --apply IdahoEv/dotfiles, then exec zsh. Set iTerm2's font to MesloLGS Nerd Font for the prompt glyphs."
