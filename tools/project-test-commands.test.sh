#!/usr/bin/env bash
# The review cycle runs the project's documented FAST/FULL commands. This repo's FAST must
# include the manifest check so a stale workflow/manifest.txt fails before reviewers or the PR.
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$tools_dir")"
pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

fast="$(grep -E '^- \*\*FAST\*\*' "$repo/CLAUDE.md" || true)"
full="$(grep -E '^- \*\*FULL\*\*' "$repo/CLAUDE.md" || true)"

[ -n "$fast" ] || fail "CLAUDE.md documents no FAST command"
[ -n "$full" ] || fail "CLAUDE.md documents no FULL command"
pass "CLAUDE.md documents FAST and FULL"

grep -q 'tools/workflow-manifest.test.sh' <<<"$fast" || fail "FAST must run tools/workflow-manifest.test.sh"
pass "FAST runs the manifest test"

for suite in fast full; do
  names="$(grep -oE 'tools/[A-Za-z0-9._*-]+\.test\.sh' <<<"${!suite}" || true)"
  [ -n "$names" ] || fail "$suite names no test paths"
  for t in $names; do
    # shellcheck disable=SC2086
    compgen -G "$repo/$t" >/dev/null || fail "$suite names a missing test: $t"
  done
done
pass "every test FAST and FULL name exists"
