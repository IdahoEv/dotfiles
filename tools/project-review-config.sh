#!/usr/bin/env bash
# project-review-config.sh — parse project-review.md § Actions and § Delivery into JSON.
#
#   project-review-config.sh <path-to-project-review.md>
#
# {"review_state": {"backlog":null|path, "archive":..., "pending_actions":...},
#  "actions": null | {"file_tickets": null | {"severity":"P1","status":"NEW"},
#                     "labels":[...], "queue_closures":bool, "doc_pr":bool},
#  "delivery": {"kind":"inline|file|email", "target":"...", "fallback":{"kind":"inline|file","target":"..."}}}
# A missing § Actions (or one still holding only <placeholders>) gives "actions": null,
# which means report-only. A missing § Delivery means inline. Exit 1 on an unparseable value.

set -euo pipefail

die() { printf 'project-review-config: %s\n' "$*" >&2; exit 1; }
command -v jq >/dev/null || die "jq is required"
[ $# -eq 1 ] && [ -f "$1" ] || die "usage: project-review-config.sh <project-review.md>"

body() {  # <name> → lines of "## <name>" up to the next heading
  awk -v n="## $1" '$0 == n {on=1; next} /^## / {on=0} on' "$FILE"; }
FILE="$1"

# "- key: value" → value, backticks stripped, placeholders (<...>) and comments dropped.
field() {  # <section> <key>
  body "$1" | sed -n "s/^- *$2: *//p" | head -1 | tr -d '`' | sed 's/[[:space:]]*$//'
}
is_placeholder() { case "$1" in *'<'*'>'*|*'|'*) return 0 ;; *) return 1 ;; esac; }

onoff() {  # <key> <value> → true|false
  case "$2" in on|"") [ "$2" = on ] && echo true || echo false ;; off) echo false ;; *) die "$1 must be on or off, got '$2'" ;; esac
}

actions=null
if body Actions | grep -q '^- '; then
  ft="$(field Actions file-tickets)"
  labels="$(field Actions ticket-labels)"
  qc="$(field Actions queue-ticket-closures)"
  dp="$(field Actions doc-pr)"
  for v in ft labels qc dp; do is_placeholder "${!v}" && printf -v "$v" '%s' ''; done
  ft_json=null
  if [ -n "$ft" ] && [ "$ft" != off ]; then
    read -r sev st extra <<<"$ft"
    [[ "$sev" =~ ^P[0-3]$ ]] || die "file-tickets severity must be P0..P3, got '$sev'"
    [ -n "${st:-}" ] && [ -z "${extra:-}" ] || die "file-tickets needs '<severity> <status>' or off, got '$ft'"
    case "$st" in NEW|ANY) ;; *) die "file-tickets status must be NEW or ANY, got '$st'" ;; esac
    ft_json="$(jq -nc --arg s "$sev" --arg t "$st" '{severity:$s, status:$t}')"
  fi
  labels_json="$(jq -nc --arg l "$labels" '$l | split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0))')"
  qc_json="$(onoff queue-ticket-closures "$qc")" || exit 1
  dp_json="$(onoff doc-pr "$dp")" || exit 1
  actions="$(jq -nc --argjson ft "$ft_json" --argjson l "$labels_json" \
    --argjson qc "$qc_json" --argjson dp "$dp_json" \
    '{file_tickets:$ft, labels:$l, queue_closures:$qc, doc_pr:$dp}')"
fi

parse_channel() {  # <value> → {"kind","target"}
  case "$1" in
    inline) echo '{"kind":"inline","target":""}' ;;
    email:?*) jq -nc --arg t "${1#email:}" '{kind:"email", target:$t}' ;;
    file:?*)  jq -nc --arg t "${1#file:}" '{kind:"file", target:$t}' ;;
    *) die "Delivery must be inline, file:<path> or email:<address>, got '$1'" ;;
  esac
}

delivery='{"kind":"inline","target":""}'
dv="$(body Delivery | sed '/^[[:space:]]*$/d; /^<!--/d; /^- *fallback:/d' | head -1 | sed 's/^- *//' | tr -d '`' | sed 's/[[:space:]]*$//')"
if [ -n "$dv" ] && ! is_placeholder "$dv"; then delivery="$(parse_channel "$dv")" || exit 1; fi
# Used when the primary channel (email) has no connector; defaults to inline.
fb="$(field Delivery fallback)"
fallback='{"kind":"inline","target":""}'
if [ -n "$fb" ] && ! is_placeholder "$fb"; then fallback="$(parse_channel "$fb")" || exit 1; fi
delivery="$(jq -c --argjson f "$fallback" '. + {fallback:$f}' <<<"$delivery")"

# Review-state paths the apply step may touch; a placeholder or absent line is null.
state_path() {
  local v; v="$(field "Review state" "$1")"
  if [ -z "$v" ] || is_placeholder "$v"; then echo null; else jq -nc --arg p "$v" '$p'; fi
}
review_state="$(jq -nc --argjson b "$(state_path backlog)" --argjson a "$(state_path archive)" \
  --argjson p "$(state_path pending-actions)" '{backlog:$b, archive:$a, pending_actions:$p}')"

jq -nc --argjson a "$actions" --argjson d "$delivery" --argjson r "$review_state" \
  '{actions:$a, delivery:$d, review_state:$r}'
