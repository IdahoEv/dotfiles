#!/usr/bin/env bash
# project-review-apply.sh — act on a project-review findings block, per project-review.md § Actions.
#
#   project-review-apply.sh <findings.json> <config.json>
#
# findings.json: {"findings":[{lens,severity,status,title,body}],
#                 "closures":[{issue,action,detail,command?}]}
# config.json:   project-review-config.sh output (uses .actions and .review_state.pending_actions).
#
# Filing is deterministic: each finding gets a stable key (sha1 of the normalized title),
# stamped in the ticket body as <!-- project-review-key: K -->. A key already present in an
# open or closed ticket is never filed again. A provider that cannot create (tracker.sh exit 2)
# or cannot list completely (so dedup is impossible: exit 2 or a truncated pull) gets the finding
# queued in pending-actions instead. A create that fails (exit 1) is retried once without labels,
# since a label missing from the repo is the usual cause. Findings with a malformed severity are skipped.
# Closures and redefinitions are only ever queued; no ticket is closed or edited here.
#
# Output (tab-separated): filed|duplicate <key> <url|#id>; queued <issue|new-key> <action>; skipped|failed <id> <why>.
# Exit: 0 ok · 1 a tracker call failed.
# Tools resolve next to this script (or PR_TRACKER / PR_PENDING for tests), never via PATH.

set -euo pipefail

die() { printf 'project-review-apply: %s\n' "$*" >&2; exit 1; }

_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
TRACKER="${PR_TRACKER:-$SCRIPT_DIR/tracker.sh}"
PENDING="${PR_PENDING:-$SCRIPT_DIR/pending-actions.sh}"
# PR_PROVIDER forces the tracker provider (e.g. github-mcp where gh cannot authenticate).
prov=(); [ -z "${PR_PROVIDER:-}" ] || prov=(--provider "$PR_PROVIDER")

[ $# -eq 2 ] && [ -f "$1" ] && [ -f "$2" ] || die "usage: project-review-apply.sh <findings.json> <config.json>"
command -v jq >/dev/null || die "jq is required"
FINDINGS="$1" CONFIG="$2"
jq -e '.findings | type == "array"' "$FINDINGS" >/dev/null 2>&1 || die "findings.json needs a .findings array"

pending_file="$(jq -r '.review_state.pending_actions // empty' "$CONFIG")"
file_tickets="$(jq -c '.actions.file_tickets // empty' "$CONFIG")"
queue_closures="$(jq -r '.actions.queue_closures // false' "$CONFIG")"
rc_total=0

queue() {  # <issue> <action> <detail> [command] — prints the outcome line
  if [ -z "$pending_file" ]; then
    printf 'skipped\t%s\tno pending-actions path in § Review state\n' "$1"
  elif "$PENDING" upsert "$pending_file" --issue "$1" --action "$2" --detail "$3" ${4:+--command "$4"}; then
    printf 'queued\t%s\t%s\n' "$1" "$2"
  else
    printf 'failed\t%s\tpending-actions upsert\n' "$1"; rc_total=1
  fi
}

oneline() { tr '\n\r\t' '   ' <<<"$1"; }

finding_key() {  # <title>; lens is excluded: the "first contributing lens" can change between sweeps
  local lower norm
  lower="$(tr '[:upper:]' '[:lower:]' <<<"$1")"
  norm="$(tr -c 'a-z0-9\n' ' ' <<<"$lower" | tr -s ' ' | sed 's/^ //; s/ $//')"
  printf '%s' "${norm:-$lower}" | python3 -c 'import hashlib,sys; print(hashlib.sha1(sys.stdin.buffer.read()).hexdigest()[:12])'
}

if [ -n "$file_tickets" ]; then
  max_sev="$(jq -r .severity <<<"$file_tickets")" want_status="$(jq -r .status <<<"$file_tickets")"
  labels=()
  while IFS= read -r l; do [ -n "$l" ] && labels+=(--label "$l"); done < <(jq -r '.actions.labels[]?' "$CONFIG")

  # Candidates: severity at or above the threshold, never ALREADY TICKETED, NEW unless status is ANY.
  candidates="$(jq -c --arg m "${max_sev#P}" --arg s "$want_status" '
    .findings[] | select((.severity // "") | test("^P[0-3]$"))
    | select((.severity[1:] | tonumber) <= ($m | tonumber))
    | select(.status != "ALREADY TICKETED") | select($s == "ANY" or .status == "NEW")' "$FINDINGS")"

  if [ -n "$candidates" ]; then
    known="" can_file=1
    for state in open closed; do
      rc=0; page="$("$TRACKER" list --state "$state" ${prov[@]+"${prov[@]}"})" || rc=$?
      if [ "$rc" -eq 2 ]; then can_file=0; break; fi
      [ "$rc" -eq 0 ] || die "tracker list --state $state failed"
      if [ "$(jq -r .truncated <<<"$page")" != false ]; then can_file=0; break; fi
      known="$known
$(jq -r '.issues[] | "\(.id)\t\(.body // "" | [scan("project-review-key: ([0-9a-f]{12})")] | map(.[0]) | join(" "))"' <<<"$page")"
    done

    while IFS= read -r f; do
      title="$(jq -r .title <<<"$f")" lens="$(jq -r .lens <<<"$f")"
      key="$(finding_key "$title")"
      detail="$(oneline "$(jq -r .severity <<<"$f") $lens: $title")"
      if [ "$can_file" -eq 1 ]; then
        hit="$(awk -F'\t' -v k="$key" 'index($2, k) {print $1; exit}' <<<"$known")"
        if [ -n "$hit" ]; then printf 'duplicate\t%s\t#%s\n' "$key" "$hit"; continue; fi
        bodyf="$(mktemp "${TMPDIR:-/tmp}/pra-body.XXXXXX")"
        { jq -r .body <<<"$f"; printf '\n\n<!-- project-review-key: %s -->\n' "$key"; } > "$bodyf"
        rc=0; res="$("$TRACKER" create --title "$title" --body-file "$bodyf" ${prov[@]+"${prov[@]}"} ${labels[@]+"${labels[@]}"})" || rc=$?
        if [ "$rc" -eq 1 ] && [ "${#labels[@]}" -gt 0 ]; then
          rc=0; res="$("$TRACKER" create --title "$title" --body-file "$bodyf" ${prov[@]+"${prov[@]}"})" || rc=$?
        fi
        rm -f "$bodyf"
        case "$rc" in
          0) printf 'filed\t%s\t%s\n' "$key" "$(jq -r .url <<<"$res")"
             known="$known
$(jq -r .id <<<"$res")	$key"; continue ;;
          2) ;;
          *) printf 'failed\t%s\t%s\n' "$key" "$detail"; rc_total=1; continue ;;
        esac
      fi
      queue "new-$key" file-ticket "$detail"
    done <<<"$candidates"
  fi
fi

if [ "$queue_closures" = true ]; then
  while IFS= read -r c; do
    [ -n "$c" ] || continue
    issue="$(jq -r .issue <<<"$c")" action="$(jq -r .action <<<"$c")"
    queue "$issue" "$action" "$(oneline "$(jq -r .detail <<<"$c")")" "$(oneline "$(jq -r '.command // ""' <<<"$c")")"
  done < <(jq -c '.closures[]?' "$FINDINGS")
fi

exit "$rc_total"
