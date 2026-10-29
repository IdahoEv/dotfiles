#!/usr/bin/env bash
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bootstrap="$tools_dir/codex-cloud-bootstrap.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

mkdir -p "$tmp/bin"
cat > "$tmp/bin/curl" <<'MOCK_CURL'
#!/usr/bin/env bash
set -euo pipefail
out=""
url=""
while (($#)); do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
[[ "${MOCK_CURL_FAIL:-}" != 1 ]] || exit 22
if [[ "$url" == "https://api.github.com/repos/IdahoEv/dotfiles/commits/main" ]]; then
  printf '{"sha":"0123456789abcdef0123456789abcdef01234567"}\n'
elif [[ "$url" == "https://raw.githubusercontent.com/IdahoEv/dotfiles/0123456789abcdef0123456789abcdef01234567/workflow/ticket-to-pr.md" ]]; then
  [[ -n "$out" ]] || exit 2
  cp "$MOCK_WORKFLOW_FILE" "$out"
else
  printf 'unexpected URL: %s\n' "$url" >&2
  exit 2
fi
MOCK_CURL
chmod +x "$tmp/bin/curl"

cat > "$tmp/valid.md" <<'VALID'
<!-- workflow-contract: ticket-to-pr/v1 -->
## Required behavior
## Safety boundaries
## Completion report
VALID

PATH="$tmp/bin:$PATH" MOCK_WORKFLOW_FILE="$tmp/valid.md" \
  bash "$bootstrap" > "$tmp/success.out" || fail "valid workflow should load"
grep -q 'workflow_source_commit=0123456789abcdef0123456789abcdef01234567' "$tmp/success.out" || fail "source SHA should be reported"
workflow_file="$(sed -n 's/^workflow_source_path=//p' "$tmp/success.out")"
[[ -s "$workflow_file" ]] || fail "fetched workflow path should exist"
pass "fetches and validates a committed workflow and reports its SHA"

cat > "$tmp/invalid.md" <<'INVALID'
This is an incomplete workflow.
INVALID
if PATH="$tmp/bin:$PATH" MOCK_WORKFLOW_FILE="$tmp/invalid.md" \
  bash "$bootstrap" > "$tmp/invalid.out" 2> "$tmp/invalid.err"; then
  fail "invalid workflow must fail closed"
fi
grep -q 'failed validation' "$tmp/invalid.err" || fail "validation failure should be actionable"
pass "rejects an invalid workflow without falling back"

if PATH="$tmp/bin:$PATH" MOCK_CURL_FAIL=1 MOCK_WORKFLOW_FILE="$tmp/valid.md" \
  bash "$bootstrap" > "$tmp/network.out" 2> "$tmp/network.err"; then
  fail "network failure must fail closed"
fi
grep -q 'No cached workflow was used' "$tmp/network.err" || fail "retrieval failure should say no cache was used"
pass "fails clearly when the workflow source cannot be retrieved"
