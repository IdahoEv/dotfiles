#!/usr/bin/env bash
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bootstrap="$tools_dir/bootstrap-mac.sh"
manifest="$tools_dir/lib/packages.tsv"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

mkdir -p "$tmp/bin" "$tmp/brewbin"
mock() { # mock <dir> <name> <body>: an executable on a fake PATH dir
  printf '#!/usr/bin/env bash\n%s\n' "$3" > "$tmp/$1/$2"
  chmod +x "$tmp/$1/$2"
}

brew_body='
printf "%s\n" "$*" >> "$MOCK_BREW_LOG"
case "$1" in
  shellenv) exit 0 ;;
  list) [[ " ${MOCK_BREW_INSTALLED:-} " == *" ${@: -1} "* ]] ;;
  install) [[ -z "${MOCK_BREW_FAIL:-}" || ! "$*" =~ $MOCK_BREW_FAIL ]] ;;
esac'
mock bin uname 'echo "${MOCK_UNAME:-Darwin}"'
mock bin sudo 'printf "sudo %s\n" "$*" >> "$MOCK_BREW_LOG"; [[ "${MOCK_NO_SUDO:-}" != 1 ]]'
mock bin xcode-select '[[ "${MOCK_NO_CLT:-}" != 1 ]]'
mock brewbin brew "$brew_body"
mock bin curl '
out=""; url=""
while (($#)); do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
printf "%s\n" "$url" >> "$MOCK_CURL_URLS"
[[ "${MOCK_CURL_FAIL:-}" != 1 ]] || exit 22
case "$url" in
  */tools/lib/packages.tsv) cp "$MOCK_MANIFEST" "$out" ;;
  https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)
    printf "%s\n" "mkdir -p \"\$MOCK_PREFIX/bin\"; cp \"\$MOCK_BREW_SRC\" \"\$MOCK_PREFIX/bin/brew\"; echo \"homebrew-installer NONINTERACTIVE=\${NONINTERACTIVE:-}\" >> \"\$MOCK_BREW_LOG\"" > "$out" ;;
  *) printf "fake-download-of %s\n" "$url" > "$out" ;;
esac'

export MOCK_BREW_LOG="$tmp/brew.log" MOCK_CURL_URLS="$tmp/curl.urls" MOCK_MANIFEST="$manifest"
export MOCK_PREFIX="$tmp/prefix" MOCK_BREW_SRC="$tmp/brewbin/brew"

reset() {
  rm -rf "$tmp/prefix"
  : > "$MOCK_BREW_LOG"; : > "$MOCK_CURL_URLS"
}
run() { # run [env...] [-- args...]; BREW_ON_PATH=0 hides the mock brew; SCRIPT overrides the script under test
  local envs=() path="$tmp/bin:$tmp/brewbin:/usr/bin:/bin"
  while (($#)) && [[ "$1" != -- ]]; do envs+=("$1"); shift; done
  (($#)) && shift
  [[ "${BREW_ON_PATH:-1}" == 1 ]] || path="$tmp/bin:/usr/bin:/bin"
  env PATH="$path" HOME="$tmp/home" TMPDIR="$tmp" BOOTSTRAP_BREW_PATHS="$tmp/prefix/bin/brew" ${envs[@]+"${envs[@]}"} \
    bash "${SCRIPT:-$bootstrap}" "$@" > "$tmp/run.out" 2> "$tmp/run.err"
}
expect_failure() { # expect_failure <label> <stderr-pattern> [env...] [-- args...]
  local label="$1" pattern="$2"; shift 2
  reset
  if run "$@"; then fail "$label must fail"; fi
  grep -q "$pattern" "$tmp/run.err" || fail "$label should say: $pattern"
  compgen -G "$tmp/bootstrap-mac.*" >/dev/null && fail "$label should clean up its temp dir"
  return 0
}

reset
run || fail "happy path should succeed"
grep -qF 'install git curl jq gh fzf direnv tmux tree shellcheck wget oh-my-posh chezmoi python@3.13 uv fnm pyenv ripgrep fd bat eza the_silver_searcher git-delta' "$MOCK_BREW_LOG" || fail "formulae should come from the manifest's brew column"
pass "installs the manifest's brew formulae"

for c in iterm2 font-meslo-lg-nerd-font hammerspoon 1password-cli; do
  grep -qxF "install --cask $c" "$MOCK_BREW_LOG" || fail "cask $c should be installed on its own"
done
reset
run -- --skip-casks || fail "--skip-casks should succeed"
! grep -q -- '--cask' "$MOCK_BREW_LOG" || fail "--skip-casks must not install casks"
pass "installs casks unless --skip-casks"

! grep -qE 'install.* (zsh|unzip)( |$)' "$MOCK_BREW_LOG" || fail "builtin packages must not be brewed"
pass "skips packages macOS already ships"

reset
run MOCK_BREW_INSTALLED='git jq fzf iterm2' || fail "partial install should succeed"
formula_line="$(grep '^install ' "$MOCK_BREW_LOG" | grep -v -- '--cask')"
! grep -qE ' (git|jq|fzf)( |$)' <<<"$formula_line" || fail "installed formulae should not be reinstalled"
grep -qE ' curl( |$)' <<<"$formula_line" || fail "missing formulae should still install"
! grep -qx 'install --cask iterm2' "$MOCK_BREW_LOG" || fail "installed casks should not be reinstalled"
pass "installs only what's missing"

reset
run MOCK_BREW_INSTALLED="$(awk -F'\t' '!/^#/ && NF && $4 != "builtin" && $4 != "none" {print $4}' "$manifest" | tr '\n' ' ')" || fail "fully installed run"
! grep -q '^install' "$MOCK_BREW_LOG" || fail "a fully installed machine should run no brew install"
pass "is idempotent when everything is installed"

reset
SCRIPT="$tmp/solo/bootstrap-mac.sh"
mkdir -p "$tmp/solo"; cp "$bootstrap" "$SCRIPT"
run BOOTSTRAP_REF=v9 || fail "run without a lib/ beside the script should fetch the manifest"
grep -qF 'raw.githubusercontent.com/IdahoEv/dotfiles/v9/tools/lib/packages.tsv' "$MOCK_CURL_URLS" || fail "manifest should be fetched at BOOTSTRAP_REF"
grep -qF 'install git curl jq' "$MOCK_BREW_LOG" || fail "fetched manifest should drive the install"
unset SCRIPT
pass "fetches the manifest when run standalone (curl one-liner flow)"

reset
BREW_ON_PATH=0 run || fail "missing Homebrew should be installed"
grep -qF 'homebrew-installer NONINTERACTIVE=1' "$MOCK_BREW_LOG" || fail "Homebrew installer should run non-interactively"
grep -qF 'install git curl jq' "$MOCK_BREW_LOG" || fail "packages should install after Homebrew"
reset
run || fail "existing Homebrew run"
! grep -qF 'Homebrew/install' "$MOCK_CURL_URLS" || fail "an existing Homebrew must not be reinstalled"
pass "installs Homebrew only when missing"

expect_failure "non-macOS" 'macOS only' MOCK_UNAME=Linux
expect_failure "missing CLT" 'xcode-select --install' MOCK_NO_CLT=1
expect_failure "brew failure" 'brew install failed' 'MOCK_BREW_FAIL=^install git'
BREW_ON_PATH=0 expect_failure "missing sudo" 'sudo access is required' MOCK_NO_SUDO=1
expect_failure "unknown flag" 'unknown argument' -- --bogus
BREW_ON_PATH=0 expect_failure "download failure" 'could not fetch' MOCK_CURL_FAIL=1
pass "fails closed with a remediation message"

reset
run MOCK_BREW_FAIL='--cask iterm2' || fail "a conflicting cask must not fail the run"
grep -qxF 'install --cask hammerspoon' "$MOCK_BREW_LOG" || fail "casks after a failed one should still install"
grep -qF 'WARNING: casks not installed' "$tmp/run.out" || fail "failed casks should be reported"
pass "a failing cask warns and does not block the others"

reset
BREW_ON_PATH=0 run || fail "Homebrew install"
grep -qxF 'sudo -v' "$MOCK_BREW_LOG" || fail "sudo should be primed before the Homebrew installer"
pass "primes sudo before the Homebrew installer"

reset
SCRIPT="$tmp/piped.sh"; cp "$bootstrap" "$SCRIPT"
env PATH="$tmp/bin:$tmp/brewbin:/usr/bin:/bin" HOME="$tmp/home" TMPDIR="$tmp" BOOTSTRAP_BREW_PATHS="$tmp/prefix/bin/brew" bash < "$SCRIPT" > "$tmp/run.out" 2> "$tmp/run.err" || fail "piped run should succeed"
! grep -q 'unbound' "$tmp/run.err" || fail "piped run must not hit an unbound BASH_SOURCE"
unset SCRIPT
pass "runs when piped to bash (no BASH_SOURCE)"
