#!/usr/bin/env bash
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bootstrap="$tools_dir/cloud-workflow-bootstrap.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

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
  https://api.github.com/repos/IdahoEv/dotfiles/commits/*)
    if [[ -n "${MOCK_API_BODY:-}" ]]; then
      printf '%s\n' "$MOCK_API_BODY"
    else
      printf '{"sha":"0123456789abcdef0123456789abcdef01234567"}\n'
    fi ;;
  https://codeload.github.com/IdahoEv/dotfiles/tar.gz/*)
    [[ "${MOCK_ARCHIVE_FAIL:-}" != 1 ]] || exit 22
    [[ -n "$out" ]] || exit 2
    cp "$MOCK_ARCHIVE" "$out" ;;
  *) printf 'unexpected URL: %s\n' "$url" >&2; exit 2 ;;
esac
MOCK_CURL
chmod +x "$tmp/bin/curl"

# make_archive <name> [omit-path]: a repo snapshot shaped like the dotfiles checkout.
make_archive() {
  local name="$1" omit="${2:-}" root="$tmp/src-$1/dotfiles-$sha"
  mkdir -p "$root/dot_claude/commands" "$root/tools" "$root/workflow/adapters"
  printf '# Start\n' > "$root/dot_claude/commands/start.md"
  printf '# Open PR\n' > "$root/dot_claude/commands/open-pr.md"
  printf '# Codex adapter\n' > "$root/workflow/adapters/codex.md"
  printf '#!/usr/bin/env bash\necho start-ticket\n' > "$root/tools/start-ticket.sh"
  printf '#!/usr/bin/env bash\necho open-pr\n' > "$root/tools/open-pr.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$root/tools/open-pr.test.sh"
  chmod +x "$root"/tools/*.sh
  [[ -z "$omit" ]] || rm -f "$root/$omit"
  tar -czf "$tmp/$name.tar.gz" -C "$tmp/src-$name" "dotfiles-$sha"
}
make_archive valid
make_archive no-start dot_claude/commands/start.md
make_archive no-adapter workflow/adapters/codex.md
make_archive no-tool tools/open-pr.sh
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
grep -q 'IdahoEv/dotfiles/commits/main$' "$tmp/curl.urls" || fail "default ref should resolve main"
grep -q "tar.gz/$sha\$" "$tmp/curl.urls" || fail "archive should be fetched by resolved SHA"
pass "fetches the repo at one SHA, extracts it, exposes tools, reports the SHA"

: > "$MOCK_CURL_URLS"
run valid WORKFLOW_REF="$pin" || fail "pinned SHA should load"
! grep -q 'api.github.com' "$MOCK_CURL_URLS" || fail "a full SHA ref needs no API call"
grep -q "tar.gz/$pin\$" "$MOCK_CURL_URLS" || fail "pinned SHA should be fetched verbatim"
grep -q "workflow_source_commit=$pin" "$tmp/run.out" || fail "pinned SHA should be reported"
: > "$MOCK_CURL_URLS"
run valid WORKFLOW_REF=v1.2 || fail "tag ref should load"
grep -q 'commits/v1.2$' "$MOCK_CURL_URLS" || fail "a tag ref should be resolved through the API"
expect_failure "invalid ref" 'Invalid WORKFLOW_REF' valid 'WORKFLOW_REF=../etc'
pass "WORKFLOW_REF pins a SHA or tag and rejects unsafe values"

expect_failure "API failure" 'Could not read' valid MOCK_CURL_FAIL=1
expect_failure "malformed SHA" 'invalid commit response' valid 'MOCK_API_BODY={"sha":"abc"}'
expect_failure "non-JSON body" 'invalid commit response' valid 'MOCK_API_BODY=not json'
pass "fails closed when the ref cannot be resolved"

expect_failure "archive fetch failure" 'Could not fetch' valid MOCK_ARCHIVE_FAIL=1
expect_failure "empty archive" 'Could not extract\|missing required' empty
expect_failure "corrupt archive" 'Could not extract' corrupt
pass "fails closed when the archive cannot be fetched or extracted"

expect_failure "missing command" 'missing required' no-start
expect_failure "missing adapter" 'missing required' no-adapter
expect_failure "missing tool" 'missing required' no-tool
pass "rejects a snapshot missing a required command, adapter, or tool"

! grep -q 'Authorization' "$MOCK_CURL_ARGS" || fail "no Authorization header expected without GITHUB_TOKEN"
grep -q -- '--max-time' "$MOCK_CURL_ARGS" || fail "curl calls should set a total timeout"
grep -q -- '--retry' "$MOCK_CURL_ARGS" || fail "curl calls should retry"
: > "$MOCK_CURL_ARGS"
run valid GITHUB_TOKEN=tok || fail "token run should succeed"
[[ "$(grep -c 'Authorization: Bearer tok' "$MOCK_CURL_ARGS")" == 1 ]] || fail "token should be sent on the API call only"
pass "sends timeouts/retry always and the token only on the API call when set"
