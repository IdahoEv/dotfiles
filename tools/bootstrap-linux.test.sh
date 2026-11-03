#!/usr/bin/env bash
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bootstrap="$tools_dir/bootstrap-linux.sh"
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
printf "fake-download-of %s\n" "$url" > "$out"'

export MOCK_SUDO_LOG="$tmp/sudo.log" MOCK_CURL_URLS="$tmp/curl.urls" MOCK_SUDO_DEST="$tmp/sudo-dest"

reset() { # fresh HOME, empty logs
  rm -rf "$tmp/home" "$tmp/sudo-dest"/*
  mkdir -p "$tmp/home"
  : > "$MOCK_SUDO_LOG"; : > "$MOCK_CURL_URLS"
}
run() { # run [env...] [-- args...] — stdout/stderr to $tmp/run.{out,err}
  local envs=()
  while (($#)) && [[ "$1" != -- ]]; do envs+=("$1"); shift; done
  (($#)) && shift
  env PATH="$tmp/bin:/usr/bin:/bin" HOME="$tmp/home" TMPDIR="$tmp" ${envs[@]+"${envs[@]}"} \
    bash "$bootstrap" "$@" > "$tmp/run.out" 2> "$tmp/run.err"
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
grep -qF 'apt-get install -y zsh fzf direnv unzip tmux git curl' "$MOCK_SUDO_LOG" || fail "baseline apt packages should be installed"
pass "installs the baseline apt packages"

grep -qF 'apt-get install -y gh' "$MOCK_SUDO_LOG" || fail "gh should be installed"
grep -qF 'https://cli.github.com/packages/githubcli-archive-keyring.gpg' "$MOCK_CURL_URLS" || fail "gh keyring should be fetched"
grep -qF 'signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg' "$tmp/sudo-dest/github-cli.list" || fail "gh source list should be signed-by the keyring"
grep -qF 'arch=amd64' "$tmp/sudo-dest/github-cli.list" || fail "gh source list should carry the dpkg architecture"
pass "adds the gh apt repo with a signed keyring"

[[ -x "$tmp/home/.local/bin/oh-my-posh" && -x "$tmp/home/.local/bin/chezmoi" ]] || fail "binaries should land in ~/.local/bin"
grep -qF 'JanDeDobbeleer/oh-my-posh/releases/latest/download/posh-linux-amd64' "$MOCK_CURL_URLS" || fail "oh-my-posh release asset URL"
grep -qF 'twpayne/chezmoi/releases/latest/download/chezmoi-linux-amd64' "$MOCK_CURL_URLS" || fail "chezmoi release asset URL"
pass "installs oh-my-posh and chezmoi into ~/.local/bin"

grep -qF 'chsh -s ' "$MOCK_SUDO_LOG" && grep -q 'chsh -s .*/zsh ' "$MOCK_SUDO_LOG" || fail "login shell should be set to zsh"
pass "sets the login shell to zsh"

reset
run MOCK_ARCH=arm64 || fail "arm64 should succeed"
grep -qF 'posh-linux-arm64' "$MOCK_CURL_URLS" || fail "arch should select the arm64 asset"
expect_failure "unsupported arch" 'unsupported architecture' MOCK_ARCH=riscv64
pass "selects release assets by architecture"

reset
run || fail "first run"
: > "$MOCK_CURL_URLS"; : > "$MOCK_SUDO_LOG"
mock gh 'exit 0'
run MOCK_LOGIN_SHELL=/usr/bin/zsh || fail "second run"
[[ ! -s "$MOCK_CURL_URLS" ]] || fail "second run should download nothing"
! grep -q 'chsh' "$MOCK_SUDO_LOG" || fail "second run should not chsh when the login shell is zsh"
rm -f "$tmp/bin/gh"
pass "is idempotent: existing binaries, gh, and zsh login shell are left alone"

reset
run -- --skip-gh || fail "--skip-gh should succeed"
! grep -qF 'install -y gh' "$MOCK_SUDO_LOG" || fail "--skip-gh must not install gh"
expect_failure "unknown flag" 'unknown argument' -- --bogus
pass "--skip-gh skips gh; unknown flags are rejected"

expect_failure "non-Linux" 'Linux/WSL only' MOCK_UNAME=Darwin
expect_failure "apt failure" 'apt-get install failed' 'MOCK_SUDO_FAIL=apt-get install -y zsh'
expect_failure "gh failure" 'gh install failed' 'MOCK_SUDO_FAIL=apt-get install -y gh'
expect_failure "download failure" 'could not fetch' MOCK_CURL_FAIL=1
expect_failure "chsh failure" 'chsh failed' 'MOCK_SUDO_FAIL=^chsh'
pass "fails closed with a remediation message"

reset
run MOCK_CURL_FAIL=1 || true
[[ ! -e "$tmp/home/.local/bin/oh-my-posh" ]] || fail "a failed download must not leave a binary behind"
pass "leaves no partial binary on download failure"
