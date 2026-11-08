#!/usr/bin/env bash
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bootstrap="$tools_dir/cloud-workflow-bootstrap.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

unset GITHUB_TOKEN WORKFLOW_INSTALL WORKFLOW_HOME WORKFLOW_BIN_DIR CLAUDE_CONFIG_DIR CLAUDE_ENV_FILE

sha=0123456789abcdef0123456789abcdef01234567
pin=fedcba9876543210fedcba9876543210fedcba98

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

mkdir -p "$tmp/bin"
cat > "$tmp/bin/curl" <<'MOCK_CURL'
#!/usr/bin/env bash
set -euo pipefail
out=""
url=""
printf '%s\n' "$*" >> "$MOCK_CURL_ARGS"
while (($#)); do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
printf '%s\n' "$url" >> "$MOCK_CURL_URLS"
[[ "${MOCK_CURL_FAIL:-}" != 1 ]] || exit 22
case "$url" in
  https://codeload.github.com/IdahoEv/dotfiles/tar.gz/*)
    [[ "${MOCK_ARCHIVE_FAIL:-}" != 1 ]] || exit 22
    [[ -n "$out" ]] || exit 2
    cp "$MOCK_ARCHIVE" "$out" ;;
  *) printf 'unexpected URL: %s\n' "$url" >&2; exit 2 ;;
esac
MOCK_CURL
chmod +x "$tmp/bin/curl"

# pack <src-dir> <top-dir> <out.tar.gz> <commit>: a GitHub-style archive whose pax header names the commit.
pack() {
  python3 -I - "$@" <<'PY'
import sys, tarfile
src, top, out, commit = sys.argv[1:]
with tarfile.open(out, "w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": commit}) as tf:
    tf.add(f"{src}/{top}", arcname=top)
PY
}

# make_archive <name> [omit-path]: a repo snapshot shaped like the dotfiles checkout.
make_archive() {
  local name="$1" omit="${2:-}" root="$tmp/src-$1/dotfiles-$sha"
  mkdir -p "$root/dot_claude/commands" "$root/dot_claude/agents" "$root/dot_claude/skills/proc" "$root/tools" "$root/workflow/adapters"
  printf '# Agent\n' > "$root/dot_claude/agents/reviewer.md"
  printf '# Skill\n' > "$root/dot_claude/skills/proc/SKILL.md"
  printf '#!/usr/bin/env bash\necho poll\n' > "$root/dot_claude/skills/proc/executable_poll.sh"
  printf '# Template\n' > "$root/dot_claude/CLAUDE.md.tmpl"
  printf '#!/usr/bin/env python3\nprint("shim")\n' > "$root/tools/cloud-gh-shim.py"
  printf '# Claude cloud adapter\n' > "$root/workflow/adapters/claude-cloud.md"
  printf '# Start\n' > "$root/dot_claude/commands/start.md"
  printf '# Open PR\n' > "$root/dot_claude/commands/open-pr.md"
  printf '# Codex adapter\n' > "$root/workflow/adapters/codex.md"
  printf '# AGY adapter\n' > "$root/workflow/adapters/agy.md"
  printf '#!/usr/bin/env bash\necho start-ticket\n' > "$root/tools/start-ticket.sh"
  printf '#!/usr/bin/env bash\necho open-pr\n' > "$root/tools/open-pr.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$root/tools/open-pr.test.sh"
  chmod +x "$root"/tools/*.sh
  [[ -z "$omit" ]] || rm -f "$root/$omit"
  pack "$tmp/src-$name" "dotfiles-$sha" "$tmp/$name.tar.gz" "$sha"
}
make_archive valid
make_archive no-start dot_claude/commands/start.md
make_archive no-adapter workflow/adapters/codex.md
make_archive no-agy-adapter workflow/adapters/agy.md
make_archive no-claude-adapter workflow/adapters/claude-cloud.md
make_archive no-tool tools/open-pr.sh
make_archive no-shim tools/cloud-gh-shim.py
: > "$tmp/empty.tar.gz"
printf 'not a tarball' > "$tmp/corrupt.tar.gz"

export MOCK_CURL_ARGS="$tmp/curl.args" MOCK_CURL_URLS="$tmp/curl.urls"
: > "$MOCK_CURL_ARGS"; : > "$MOCK_CURL_URLS"

run() { # run <archive> [env...] — stdout/stderr to $tmp/run.{out,err}
  local archive="$1"; shift
  env PATH="$tmp/bin:$PATH" TMPDIR="$tmp" MOCK_ARCHIVE="$tmp/$archive.tar.gz" "$@" \
    bash "$bootstrap" > "$tmp/run.out" 2> "$tmp/run.err"
}
no_leftovers() { ! compgen -G "$tmp/dotfiles-workflow.*" >/dev/null; }
expect_failure() { # expect_failure <label> <stderr-pattern> <archive> [env...]
  local label="$1" pattern="$2"; shift 2
  rm -rf "$tmp"/dotfiles-workflow.*
  if run "$@"; then fail "$label must fail closed"; fi
  grep -q "$pattern" "$tmp/run.err" || fail "$label should say: $pattern"
  no_leftovers || fail "$label should clean up its temp dir"
}

run valid || fail "valid archive should load"
grep -q "workflow_source_commit=$sha" "$tmp/run.out" || fail "source SHA should be reported"
root="$(sed -n 's/^workflow_root=//p' "$tmp/run.out")"
[[ -f "$root/dot_claude/commands/start.md" ]] || fail "repo should be extracted at workflow_root"
bin_dir="$(sed -n 's/^workflow_bin=//p' "$tmp/run.out")"
[[ -x "$bin_dir/start-ticket.sh" && -x "$bin_dir/open-pr.sh" ]] || fail "tools should be exposed on workflow_bin"
[[ ! -e "$bin_dir/open-pr.test.sh" ]] || fail "test scripts must not be exposed"
[[ "$("$bin_dir/start-ticket.sh")" == start-ticket ]] || fail "exposed tool should run"
grep -q 'tar.gz/main$' "$tmp/curl.urls" || fail "default ref should fetch main"
! grep -q 'api.github.com' "$tmp/curl.urls" || fail "the GitHub API must not be called"
grep -q "workflow_source_url=.*tar.gz/$sha\$" "$tmp/run.out" || fail "the reported URL should be pinned to the commit"
pass "fetches the repo once with no API call, reports the commit from the archive header"

pack "$tmp/src-valid" "dotfiles-$sha" "$tmp/valid-pin.tar.gz" "$pin"
: > "$MOCK_CURL_URLS"
run valid-pin WORKFLOW_REF="$pin" || fail "pinned SHA should load"
grep -q "tar.gz/$pin\$" "$MOCK_CURL_URLS" || fail "pinned SHA should be fetched verbatim"
grep -q "workflow_source_commit=$pin" "$tmp/run.out" || fail "pinned SHA should be reported"
expect_failure "pinned SHA mismatch" 'Pinned WORKFLOW_REF' valid "WORKFLOW_REF=$pin"
: > "$MOCK_CURL_URLS"
run valid WORKFLOW_REF=v1.2 || fail "tag ref should load"
grep -q 'tar.gz/v1.2$' "$MOCK_CURL_URLS" || fail "a tag ref should be fetched by name"
expect_failure "invalid ref" 'Invalid WORKFLOW_REF' valid 'WORKFLOW_REF=../etc'
pass "WORKFLOW_REF pins a SHA (verified against the archive) or names a tag, and rejects unsafe values"

tar -czf "$tmp/nopax.tar.gz" -C "$tmp/src-valid" "dotfiles-$sha"
expect_failure "archive without a commit id" 'Could not determine the commit' nopax
pass "fails closed when the archive does not name its commit"

expect_failure "archive fetch failure" 'Could not fetch' valid MOCK_ARCHIVE_FAIL=1
expect_failure "empty archive" 'Could not determine the commit' empty
expect_failure "corrupt archive" 'Could not determine the commit' corrupt
pass "fails closed when the archive cannot be fetched or extracted"

expect_failure "missing command" 'missing required' no-start
expect_failure "missing codex adapter" 'missing required' no-adapter
expect_failure "missing agy adapter" 'missing required' no-agy-adapter
expect_failure "missing claude-cloud adapter" 'missing required' no-claude-adapter WORKFLOW_INSTALL=claude HOME="$tmp/h0"
expect_failure "missing gh shim" 'missing required' no-shim WORKFLOW_INSTALL=claude HOME="$tmp/h0"
expect_failure "missing tool" 'missing required' no-tool
pass "rejects a snapshot missing a required command, adapter, or tool"

grep -q -- '--max-time' "$MOCK_CURL_ARGS" || fail "curl calls should set a total timeout"
grep -q -- '--retry' "$MOCK_CURL_ARGS" || fail "curl calls should retry"
! grep -q 'Authorization' "$MOCK_CURL_ARGS" || fail "no credentials are sent"
pass "sends timeouts/retry and no credentials"

# Claude Code cloud install: commands/agents/skills land in the config dir, tools on PATH.
home="$tmp/home"; mkdir -p "$home"
env_file="$tmp/claude-env"; : > "$env_file"
rm -rf "$tmp"/dotfiles-workflow.*
run valid WORKFLOW_INSTALL=claude HOME="$home" WORKFLOW_BIN_DIR="$tmp/installbin" CLAUDE_ENV_FILE="$env_file" \
  || fail "claude install should succeed"
[[ -f "$home/.claude/commands/start.md" && -f "$home/.claude/agents/reviewer.md" ]] || fail "commands and agents should be installed"
[[ -x "$home/.claude/skills/proc/poll.sh" ]] || fail "executable_ prefix should be stripped and the file made executable"
[[ ! -e "$home/.claude/CLAUDE.md" && ! -e "$home/.claude/CLAUDE.md.tmpl" ]] || fail "the global CLAUDE.md template must not be installed"
[[ "$("$tmp/installbin/start-ticket.sh")" == start-ticket ]] || fail "installed tool link should run"
[[ ! -e "$tmp/installbin/open-pr.test.sh" ]] || fail "test scripts must not be linked"
root="$(sed -n 's/^workflow_root=//p' "$tmp/run.out")"
[[ "$root" == "$home/.cache/dotfiles-workflow/$sha" && -f "$root/workflow/adapters/claude-cloud.md" ]] || fail "install should keep the snapshot under WORKFLOW_HOME"
grep -q 'export PATH=' "$env_file" || fail "PATH should be exported through CLAUDE_ENV_FILE"
grep -q "workflow_claude_dir=$home/.claude" "$tmp/run.out" || fail "the config dir should be reported"
[[ "$("$home/.cache/dotfiles-workflow/shim/gh")" == shim ]] || fail "the gh shim should be installed as gh"
grep -q "workflow_shim=$home/.cache/dotfiles-workflow/shim" "$tmp/run.out" || fail "the shim dir should be reported"
grep -q "shim:$tmp/installbin" "$env_file" || fail "the shim must precede the tool links on PATH"
run valid WORKFLOW_INSTALL=claude HOME="$home" WORKFLOW_BIN_DIR="$tmp/installbin" || fail "no-hook install should succeed"
grep -q "shim:$tmp/installbin" "$home/.bashrc" || fail "without CLAUDE_ENV_FILE, PATH should persist in ~/.bashrc"
run valid WORKFLOW_INSTALL=claude HOME="$home" WORKFLOW_BIN_DIR="$tmp/installbin" || fail "re-running the install should succeed"
[[ "$(grep -c 'shim:' "$env_file")" == 1 ]] || fail "CLAUDE_ENV_FILE must not collect duplicate PATH lines"
no_leftovers || fail "a claude install should clean up its temp dir"
[[ "$(grep -c 'shim:' "$home/.bashrc")" == 1 ]] || fail "~/.bashrc must not collect duplicate PATH lines"
expect_failure "unknown install mode" 'Invalid WORKFLOW_INSTALL' valid WORKFLOW_INSTALL=bogus
pass "WORKFLOW_INSTALL=claude installs commands, agents, skills and tool links, idempotently"

# A pre-Claude-support snapshot still loads for the hosts that do not install; only the install needs the new files.
run no-claude-adapter || fail "a snapshot without claude-cloud files should still load for non-install runs"
expect_failure "install without claude files" 'missing required' no-claude-adapter WORKFLOW_INSTALL=claude HOME="$home"
# Symlinked tools are not linked or chmodded; a real binary of the same name is not replaced.
make_archive evil
ln -sf /etc/hostname "$tmp/src-evil/dotfiles-$sha/tools/evil.sh"
pack "$tmp/src-evil" "dotfiles-$sha" "$tmp/evil.tar.gz" "$sha"
mkdir -p "$tmp/evilbin"; printf '#!/bin/sh\necho real\n' > "$tmp/evilbin/open-pr.sh"; chmod +x "$tmp/evilbin/open-pr.sh"
run evil WORKFLOW_INSTALL=claude HOME="$home" WORKFLOW_BIN_DIR="$tmp/evilbin" || fail "evil archive should still install"
[[ ! -e "$tmp/evilbin/evil.sh" ]] || fail "symlinked tools must not be linked"
[[ "$("$tmp/evilbin/open-pr.sh")" == real ]] || fail "an existing non-link binary must not be replaced"
pass "install requires claude files only in install mode; skips symlinked tools; keeps existing binaries"
