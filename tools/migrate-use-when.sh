#!/usr/bin/env bash
# migrate-use-when.sh — move a reviewer's trailing `Use when:` clause out of
# its one-line `description:` into a `use_when:` key directly above it.
#
#   migrate-use-when.sh <agent-file>...
#
# Rewrites each file in place and prints one line per file: `migrated`,
# `skip (already has use_when:)`, or `skip (no single-line description with a
# Use when: clause)`. Only frontmatter is touched. Idempotent.
#
# Exit codes: 0 always for per-file skips; 1 on usage errors.

set -euo pipefail

[ "$#" -gt 0 ] && [ "$1" != "-h" ] && [ "$1" != "--help" ] || {
  printf 'usage: migrate-use-when.sh <agent-file>...\n' >&2
  exit 1
}

migrate() {  # <file> → prints status, rewrites when migrating
  local f="$1" tmp
  [ -f "$f" ] || { printf '%s: not a file\n' "$f" >&2; return 0; }
  if awk 'NR>1&&$0=="---"{exit} /^use_when:/{found=1; exit} END{exit !found}' "$f"; then
    printf '%s: skip (already has use_when:)\n' "$f"
    return 0
  fi
  tmp="$(mktemp "${TMPDIR:-/tmp}/migrate-use-when.XXXXXX")"
  awk '
    NR == 1 && $0 == "---" { fm = 1; print; next }
    fm && $0 == "---" { fm = 0 }
    fm && !done && /^description: [^"\047]/ && /^description: .* Use when: / {
      i = index($0, " Use when: ")
      desc = substr($0, 1, i - 1)
      clause = substr($0, i + length(" Use when: "))
      print "use_when: " clause
      print desc
      done = 1
      next
    }
    { print }
    END { exit done ? 0 : 3 }
  ' "$f" > "$tmp" && { cat "$tmp" > "$f"; printf '%s: migrated\n' "$f"; } \
    || printf '%s: skip (no single-line description with a Use when: clause)\n' "$f"
  rm -f "$tmp"
}

for f in "$@"; do migrate "$f"; done
