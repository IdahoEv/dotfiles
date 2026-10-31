#!/usr/bin/env bash
# finalize-check.test.sh — chain_ids output of finalize-check.sh.
#
#   finalize-check.test.sh
#
# Plain script, exits non-zero on failure. Runs in a throwaway repo with HOME
# redirected; gh is not needed, only the branch/worktree facts are asserted.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/finalize-check-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

get() { sed -n "s/^$1=//p"; }

git init -q -b main "$ROOT/repo"
git -C "$ROOT/repo" commit -q --allow-empty -m init
git -C "$ROOT/repo" worktree add -q "$ROOT/wt" -b 7-first-ticket

out="$("$TOOLS/finalize-check.sh" --dir "$ROOT/wt" 2>/dev/null)"
check "single ticket: ticket_id" "7" "$(get ticket_id <<<"$out")"
check "single ticket: chain_ids is the ticket" "7" "$(get chain_ids <<<"$out")"

printf '7\n8\n9\n' > "$(git -C "$ROOT/wt" rev-parse --absolute-git-dir)/chain"
out="$("$TOOLS/finalize-check.sh" --dir "$ROOT/wt" 2>/dev/null)"
check "chain: ticket_id stays the head" "7" "$(get ticket_id <<<"$out")"
check "chain: chain_ids lists every ticket" "7,8,9" "$(get chain_ids <<<"$out")"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
