#!/usr/bin/env bash
# migrate-use-when.test.sh — behavioral checks for migrate-use-when.sh.
#
#   migrate-use-when.test.sh
#
# Plain script, exits non-zero on failure. Works on temp copies only.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIG="$TOOLS/migrate-use-when.sh"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

contains() {  # <description> <needle> <haystack>
  case "$3" in *"$2"*) check "$1" yes yes ;; *) check "$1" yes no ;; esac
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/migrate-use-when-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT

old="$ROOT/old.md"
printf -- '---\nname: x-reviewer\ndescription: Reviews x. Read-only. Use when: the diff touches x, or y.\ntools: Read\n---\nBody mentions Use when: here.\n' > "$old"

out="$("$MIG" "$old")"
contains "reports migrated" "old.md: migrated" "$out"
check "key sits directly above description" \
  "use_when: the diff touches x, or y.
description: Reviews x. Read-only." \
  "$(sed -n '3,4p' "$old")"
check "other frontmatter untouched" "tools: Read" "$(sed -n '5p' "$old")"
check "body untouched" "Body mentions Use when: here." "$(tail -1 "$old")"

before="$(cat "$old")"
out="$("$MIG" "$old")"
contains "second run skips" "skip (already has use_when:)" "$out"
check "second run changes nothing" "$before" "$(cat "$old")"

multi="$ROOT/multi.md"
printf -- '---\nname: m\ndescription: >-\n  Reviews. Use when: z.\n---\nbody\n' > "$multi"
before="$(cat "$multi")"
out="$("$MIG" "$multi")"
contains "multi-line description is skipped" "skip (no single-line" "$out"
check "multi-line file unchanged" "$before" "$(cat "$multi")"

quoted="$ROOT/quoted.md"
printf -- '---\nname: q\ndescription: "Reviews q. Use when: w."\n---\nbody\n' > "$quoted"
before="$(cat "$quoted")"
out="$("$MIG" "$quoted")"
contains "quoted description is skipped" "skip (no single-line" "$out"
check "quoted file unchanged" "$before" "$(cat "$quoted")"

none="$ROOT/none.md"
printf -- '---\nname: n\ndescription: Reviews n.\n---\nbody\n' > "$none"
out="$("$MIG" "$none")"
contains "no clause is skipped" "skip (no single-line" "$out"

out="$("$MIG" 2>&1)"; rc=$?
check "no argument exits 1" "1" "$rc"
contains "no argument shows usage" "usage:" "$out"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
