#!/usr/bin/env bash
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bootstrap="$tools_dir/bootstrap-linux.sh"
manifest="$tools_dir/lib/packages.tsv"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

mkdir -p "$tmp/bin" "$tmp/sudo-dest"
mock() { # mock <name> <body>: an executable on the fake PATH
  printf '#!/usr/bin/env bash\n%s\n' "$2" > "$tmp/bin/$1"
  chmod +x "$tmp/bin/$1"
}

mock uname 'echo "${MOCK_UNAME:-Linux}"'
mock dpkg 'echo "${MOCK_ARCH:-amd64}"'
mock getent 'echo "evan:x:1000:1000::/home/evan:${MOCK_LOGIN_SHELL:-/bin/bash}"'
mock apt-get 'exit 0'
mock apt-cache '[[ -z "${MOCK_APT_MISSING:-}" || ! "$2" =~ $MOCK_APT_MISSING ]]'
mock zsh 'exit 0'
mock sudo '
printf "%s\n" "$*" >> "$MOCK_SUDO_LOG"
if [[ -n "${MOCK_SUDO_FAIL:-}" && "$*" =~ $MOCK_SUDO_FAIL ]]; then exit 1; fi
if [[ "$1" == install ]]; then cp "$4" "$MOCK_SUDO_DEST/$(basename "$5")"; fi
exit 0'
mock curl '
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
  https://astral.sh/uv/install.sh)
    printf "%s\n" "mkdir -p \"\$UV_UNMANAGED_INSTALL\"; : > \"\$UV_UNMANAGED_INSTALL/uv\"; chmod +x \"\$UV_UNMANAGED_INSTALL/uv\"; echo uv-installer >> \"\$MOCK_INSTALLER_LOG\"" > "$out" ;;
  https://fnm.vercel.app/install)
    printf "%s\n" "mkdir -p \"\$2\"; : > \"\$2/fnm\"; chmod +x \"\$2/fnm\"; echo \"fnm-installer \$*\" >> \"\$MOCK_INSTALLER_LOG\"" > "$out" ;;
  *) printf "fake-download-of %s\n" "$url" > "$out" ;;
esac'

export MOCK_SUDO_LOG="$tmp/sudo.log" MOCK_CURL_URLS="$tmp/curl.urls" MOCK_SUDO_DEST="$tmp/sudo-dest"
export MOCK_INSTALLER_LOG="$tmp/installer.log" MOCK_MANIFEST="$manifest"

reset() { # fresh HOME, empty logs
  rm -rf "$tmp/home" "$tmp/sudo-dest"/*
  mkdir -p "$tmp/home"
  : > "$MOCK_SUDO_LOG"; : > "$MOCK_CURL_URLS"; : > "$MOCK_INSTALLER_LOG"
}
run() { # run [env...] [-- args...] — stdout/stderr to $tmp/run.{out,err}; SCRIPT overrides the script under test
  local envs=()
  while (($#)) && [[ "$1" != -- ]]; do envs+=("$1"); shift; done
  (($#)) && shift
  env PATH="$tmp/bin:/usr/bin:/bin" HOME="$tmp/home" TMPDIR="$tmp" ${envs[@]+"${envs[@]}"} \
    bash "${SCRIPT:-$bootstrap}" "$@" > "$tmp/run.out" 2> "$tmp/run.err"
}
expect_failure() { # expect_failure <label> <stderr-pattern> [env...] [-- args...]
  local label="$1" pattern="$2"; shift 2
  reset
  if run "$@"; then fail "$label must fail"; fi
  grep -q "$pattern" "$tmp/run.err" || fail "$label should say: $pattern"
  compgen -G "$tmp/bootstrap-linux.*" >/dev/null && fail "$label should clean up its temp dir"
  return 0
}

reset
run || fail "happy path should succeed"
grep -qF 'apt-get install -y git curl jq fzf direnv tmux tree shellcheck wget unzip zsh python3' "$MOCK_SUDO_LOG" || fail "core and dev apt packages should be installed from the manifest"
grep -qF 'apt-get install -y ripgrep fd-find bat eza silversearcher-ag git-delta' "$MOCK_SUDO_LOG" || fail "search-tier apt packages should be installed"
pass "installs the manifest's apt packages by tier"

grep -qF 'apt-get install -y gh' "$MOCK_SUDO_LOG" || fail "gh should be installed"
grep -qF 'https://cli.github.com/packages/githubcli-archive-keyring.gpg' "$MOCK_CURL_URLS" || fail "gh keyring should be fetched"
grep -qF 'signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg' "$tmp/sudo-dest/github-cli.list" || fail "gh source list should be signed-by the keyring"
grep -qF 'arch=amd64' "$tmp/sudo-dest/github-cli.list" || fail "gh source list should carry the dpkg architecture"
pass "adds the gh apt repo with a signed keyring"

[[ -x "$tmp/home/.local/bin/oh-my-posh" && -x "$tmp/home/.local/bin/chezmoi" ]] || fail "binaries should land in ~/.local/bin"
grep -qF 'JanDeDobbeleer/oh-my-posh/releases/latest/download/posh-linux-amd64' "$MOCK_CURL_URLS" || fail "oh-my-posh release asset URL"
grep -qF 'twpayne/chezmoi/releases/latest/download/chezmoi-linux-amd64' "$MOCK_CURL_URLS" || fail "chezmoi release asset URL"
pass "installs oh-my-posh and chezmoi into ~/.local/bin"

[[ -x "$tmp/home/.local/bin/uv" && -x "$tmp/home/.local/bin/fnm" ]] || fail "uv and fnm should land in ~/.local/bin"
grep -qF 'uv-installer' "$MOCK_INSTALLER_LOG" || fail "uv installer should run with UV_UNMANAGED_INSTALL set"
grep -qF -- "fnm-installer --install-dir $tmp/home/.local/bin --skip-shell" "$MOCK_INSTALLER_LOG" || fail "fnm installer should target ~/.local/bin without touching shell rc files"
pass "runs the uv and fnm installers into ~/.local/bin"

grep -q 'chsh -s .*/zsh ' "$MOCK_SUDO_LOG" || fail "login shell should be set to zsh"
pass "sets the login shell to zsh"

grep -qF 'no apt equivalent, skipped: pyenv' "$tmp/run.out" || fail "manifest gaps should be reported"
pass "reports platform gaps from the manifest"

reset
run MOCK_APT_MISSING='^(eza|git-delta)$' || fail "missing optional packages must not fail the run"
grep -qF 'apt-get install -y ripgrep fd-find bat silversearcher-ag' "$MOCK_SUDO_LOG" || fail "available optional packages should still install"
grep -qF 'skipped: eza git-delta' "$tmp/run.out" || fail "unavailable optional packages should be reported"
expect_failure "required package missing" 'apt-get install failed' 'MOCK_SUDO_FAIL=apt-get install -y git curl'
pass "search tier is best-effort; core and dev fail closed"

reset
mock fdfind 'exit 0'; mock batcat 'exit 0'
run || fail "shim run"
[[ -L "$tmp/home/.local/bin/fd" && -L "$tmp/home/.local/bin/bat" ]] || fail "fd and bat should link to Debian's fdfind and batcat"
ln -sfn /nonexistent/fdfind "$tmp/home/.local/bin/fd"
run || fail "a dangling fd symlink should be replaced, not abort the run"
[[ -e "$tmp/home/.local/bin/fd" ]] || fail "the dangling fd link should now resolve"
rm -f "$tmp/bin/fdfind" "$tmp/bin/batcat"
pass "links fd and bat to Debian's renamed binaries"

reset
run MOCK_ARCH=arm64 || fail "arm64 should succeed"
grep -qF 'posh-linux-arm64' "$MOCK_CURL_URLS" || fail "arch should select the arm64 asset"
expect_failure "unsupported arch" 'unsupported architecture' MOCK_ARCH=riscv64
pass "selects release assets by architecture"

reset
run || fail "first run"
: > "$MOCK_CURL_URLS"; : > "$MOCK_SUDO_LOG"; : > "$MOCK_INSTALLER_LOG"
mock gh 'exit 0'
run MOCK_LOGIN_SHELL=/usr/bin/zsh || fail "second run"
[[ ! -s "$MOCK_CURL_URLS" ]] || fail "second run should download nothing"
[[ ! -s "$MOCK_INSTALLER_LOG" ]] || fail "second run should run no installers"
! grep -q 'chsh' "$MOCK_SUDO_LOG" || fail "second run should not chsh when the login shell is zsh"
rm -f "$tmp/bin/gh"
pass "is idempotent: existing binaries, gh, and zsh login shell are left alone"

reset
run -- --skip-gh || fail "--skip-gh should succeed"
! grep -qF 'install -y gh' "$MOCK_SUDO_LOG" || fail "--skip-gh must not install gh"
expect_failure "unknown flag" 'unknown argument' -- --bogus
pass "--skip-gh skips gh; unknown flags are rejected"

mkdir -p "$tmp/solo"
cp "$bootstrap" "$tmp/solo/bootstrap-linux.sh"
reset
SCRIPT="$tmp/solo/bootstrap-linux.sh" run BOOTSTRAP_REF=v9 || fail "run without a lib/ beside the script should fetch the manifest"
grep -qF 'raw.githubusercontent.com/IdahoEv/dotfiles/v9/tools/lib/packages.tsv' "$MOCK_CURL_URLS" || fail "manifest should be fetched at BOOTSTRAP_REF"
grep -qF 'apt-get install -y git curl' "$MOCK_SUDO_LOG" || fail "fetched manifest should drive the install"
pass "fetches the manifest when run standalone (curl one-liner flow)"

reset
mkdir -p "$tmp/decoy/lib"; printf 'core\tdecoy\tdecoy-pkg\tdecoy-pkg\n' > "$tmp/decoy/lib/packages.tsv"
(cd "$tmp/decoy" && env PATH="$tmp/bin:/usr/bin:/bin" HOME="$tmp/home" TMPDIR="$tmp" bash < "$bootstrap" > "$tmp/run.out" 2> "$tmp/run.err") || fail "piped run should succeed"
! grep -q 'unbound' "$tmp/run.err" || fail "piped run must not hit an unbound BASH_SOURCE"
grep -qF 'tools/lib/packages.tsv' "$MOCK_CURL_URLS" || fail "piped run must fetch the manifest, not read one from the cwd"
! grep -qF decoy-pkg "$MOCK_SUDO_LOG" || fail "a lib/packages.tsv in the cwd must be ignored"
pass "piped to bash: ignores a manifest in the cwd and fetches it"

expect_failure "non-Linux" 'Linux/WSL only' MOCK_UNAME=Darwin
expect_failure "apt failure" 'apt-get install failed' 'MOCK_SUDO_FAIL=apt-get install -y git'
expect_failure "gh failure" 'gh install failed' 'MOCK_SUDO_FAIL=apt-get install -y gh'
expect_failure "download failure" 'could not fetch' MOCK_CURL_FAIL=1
expect_failure "chsh failure" 'chsh failed' 'MOCK_SUDO_FAIL=^chsh'
pass "fails closed with a remediation message"

reset
run MOCK_CURL_FAIL=1 || true
[[ ! -e "$tmp/home/.local/bin/oh-my-posh" ]] || fail "a failed download must not leave a binary behind"
pass "leaves no partial binary on download failure"
