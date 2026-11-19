#!/usr/bin/env bash
# project-review-config.test.sh — checks for project-review-config.sh and the template's new sections.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG="$TOOLS/project-review-config.sh"
TEMPLATE="$TOOLS/project-config-templates/project-review.md"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then pass=$((pass + 1))
  else fail=$((fail + 1)); printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/prc-test.XXXXXX")"
trap 'rm -rf "$ROOT"' EXIT
cfg() { printf '%s\n' "$1" > "$ROOT/c.md"; "$CFG" "$ROOT/c.md" 2>"$ROOT/err"; }

check "no Actions section is report-only" 'null' "$(cfg '# x
## Cadence
- Window: 7' | jq -c .actions)"
check "review state paths" '{"backlog":null,"archive":null,"pending_actions":"docs/p.md"}' "$(cfg '## Review state
- backlog: `<path>`
- pending-actions: `docs/p.md`' | jq -c .review_state)"

check "full Actions + email delivery" \
  '{"actions":{"file_tickets":{"severity":"P1","status":"NEW"},"labels":["debt","review"],"queue_closures":true,"doc_pr":false},"delivery":{"kind":"email","target":"a@b.co","fallback":{"kind":"file","target":"out/r.md"}}}' \
  "$(cfg '## Actions
- file-tickets: P1 NEW
- ticket-labels: `debt`, review
- queue-ticket-closures: on
- doc-pr: off

## Delivery
email:a@b.co
- fallback: file:out/r.md' | jq -c 'del(.review_state)')"

check "file-tickets off" 'null' "$(cfg '## Actions
- file-tickets: off
- doc-pr: on' | jq -c .actions.file_tickets)"
check "file delivery" '{"kind":"file","target":"out/r.md","fallback":{"kind":"inline","target":""}}' "$(cfg '## Delivery
file:`out/r.md`' | jq -c .delivery)"
check "delivery skips comment lines" '{"kind":"inline","target":"","fallback":{"kind":"inline","target":""}}' "$(cfg '## Delivery
<!-- inline | file:<path> | email:<address> -->
inline' | jq -c .delivery)"
check "placeholders mean off" '{"file_tickets":null,"labels":[],"queue_closures":false,"doc_pr":false}' "$(cfg '## Actions
- file-tickets: <severity> <status>
- ticket-labels: <label>, <label>
- queue-ticket-closures: on|off
- doc-pr: on|off' | jq -c .actions)"

cfg '## Actions
- file-tickets: P9 NEW' >/dev/null; check "bad severity rejected" 1 "$?"
cfg '## Actions
- file-tickets: P1' >/dev/null; check "missing status rejected" 1 "$?"
cfg '## Actions
- doc-pr: maybe' >/dev/null; check "bad on/off rejected" 1 "$?"
cfg '## Delivery
carrier-pigeon' >/dev/null; check "bad delivery rejected" 1 "$?"
cfg '## Delivery
email:a@b.co
- fallback: email:c@d.co' >/dev/null; check "email fallback rejected" 1 "$?"
"$CFG" "$ROOT/missing.md" >/dev/null 2>&1; check "missing file fails" 1 "$?"

"$CFG" "$TEMPLATE" >/dev/null 2>&1; check "shipped template parses" 0 "$?"
for h in "## Actions" "## Delivery"; do
  check "template has $h" 1 "$(grep -cx "$h" "$TEMPLATE")"
done
for k in file-tickets ticket-labels queue-ticket-closures doc-pr; do
  check "template documents $k" 1 "$(grep -c -- "- $k:" "$TEMPLATE")"
done

printf 'project-review-config.test.sh: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
