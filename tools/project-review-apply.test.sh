#!/usr/bin/env bash
# project-review-apply.test.sh — behavioral checks for project-review-apply.sh.
# tracker.sh is replaced by a fake via PR_TRACKER; pending-actions.sh is the real one.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLY="$TOOLS/project-review-apply.sh"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then pass=$((pass + 1))
  else fail=$((fail + 1)); printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/pra-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
LOG="$ROOT/log"; PEND="$ROOT/pending.md"
export FAKE_LOG="$LOG" FAKE_STORE="$ROOT/store.json"

# Fake tracker: list reads FAKE_STORE (open/closed arrays); create appends to the store and logs.
cat > "$ROOT/tracker.sh" <<'EOF2'
#!/usr/bin/env bash
case "$1" in
  list)
    [ "${FAKE_LIST_RC:-0}" -eq 0 ] || exit "$FAKE_LIST_RC"
    state=open; [ "$2" = --state ] && state="$3"
    echo "list $state" >> "$FAKE_LOG"
    jq -c --arg s "$state" '{truncated: (env.FAKE_TRUNC == "1"), issues: .[$s]}' "$FAKE_STORE" ;;
  create)
    [ "${FAKE_CREATE_RC:-0}" -eq 0 ] || exit "$FAKE_CREATE_RC"
    case " $* " in *" --label "*) [ -z "${FAKE_NO_LABELS:-}" ] || exit 1 ;; esac
    shift; title="" body="" labels=""
    while [ $# -gt 0 ]; do case "$1" in
      --title) title="$2"; shift 2 ;; --body-file) body="$(cat "$2")"; shift 2 ;;
      --label) labels="$labels,$2"; shift 2 ;; *) shift ;; esac; done
    echo "create|$title|${labels#,}" >> "$FAKE_LOG"
    n=$(( $(jq '[.open[],.closed[]]|length' "$FAKE_STORE") + 100 ))
    jq --argjson n "$n" --arg b "$body" '.open += [{id:$n, body:$b}]' "$FAKE_STORE" > "$FAKE_STORE.t" && mv "$FAKE_STORE.t" "$FAKE_STORE"
    echo "{\"id\":$n,\"url\":\"u$n\"}" ;;
  *) echo "BAD VERB $1" >> "$FAKE_LOG"; exit 1 ;;
esac
EOF2
chmod +x "$ROOT/tracker.sh"
export PR_TRACKER="$ROOT/tracker.sh"

reset() { echo '{"open":[],"closed":[]}' > "$FAKE_STORE"; : > "$LOG"; rm -f "$PEND"; unset FAKE_LIST_RC FAKE_CREATE_RC FAKE_TRUNC FAKE_NO_LABELS; }
run() {  # <findings-json> <actions-json>  → stdout; rc in $RC
  printf '%s' "$1" > "$ROOT/findings.json"
  jq -nc --argjson a "$2" --arg p "$PEND" '{actions:$a, review_state:{pending_actions:$p}}' > "$ROOT/config.json"
  out="$("$APPLY" "$ROOT/findings.json" "$ROOT/config.json" 2>"$ROOT/err")"; RC=$?
}

F='{"findings":[
 {"lens":"quality","severity":"P1","status":"NEW","title":"Unquoted var in x.sh","body":"b1"},
 {"lens":"docs","severity":"P3","status":"NEW","title":"Typo","body":"b2"},
 {"lens":"plan","severity":"P0","status":"ALREADY TICKETED","title":"Known thing","body":"b3"},
 {"lens":"quality","severity":"P2","status":"KNOWN","title":"Old thing","body":"b4"}],
 "closures":[{"issue":12,"action":"close-duplicate","detail":"dup of #3"},
             {"issue":14,"action":"relabel","detail":"add debt","command":"gh issue edit 14"}]}'
A='{"file_tickets":{"severity":"P1","status":"NEW"},"labels":["review","debt"],"queue_closures":true,"doc_pr":false}'

reset; run "$F" "$A"
check "exit 0" 0 "$RC"
check "only the P1 NEW finding is filed" "create|Unquoted var in x.sh|review,debt" "$(grep '^create' "$LOG")"
check "body carries the stable key" 1 "$(jq '[.open[]|select(.body|test("<!-- project-review-key: [0-9a-f]{12} -->"))]|length' "$FAKE_STORE")"
check "summary lists filed" 1 "$(grep -c '^filed' <<<"$out")"

run "$F" "$A"
check "rerun files nothing new" 1 "$(grep -c '^create' "$LOG")"
check "rerun reports duplicate" 1 "$(grep -c '^duplicate' <<<"$out")"

reset
key="$(run "$F" "$A"; sed -n 's/^filed\t\([0-9a-f]*\)\t.*/\1/p' <<<"$out")"
reset; jq -nc --arg k "$key" '{open:[],closed:[{id:5,body:("x <!-- project-review-key: " + $k + " -->")}]}' > "$FAKE_STORE"
run "$F" "$A"
check "closed ticket with the key suppresses filing" 0 "$(grep -c '^create' "$LOG")"
check "both open and closed sets were pulled" "list open
list closed" "$(grep '^list' "$LOG")"

reset; run "$F" '{"file_tickets":{"severity":"P3","status":"ANY"},"labels":[],"queue_closures":false,"doc_pr":false}'
check "ANY/P3 files P1,P3,P2 but never ALREADY TICKETED" 3 "$(grep -c '^create' "$LOG")"

reset; FAKE_CREATE_RC=2 run "$F" "$A"
check "exit-2 provider queues, exit 0" 0 "$RC"
check "unfiled finding queued as new-<key>" 1 "$("$TOOLS/pending-actions.sh" list "$PEND" | grep -cE '^new-[0-9a-f]{12}	file-ticket	')"

reset; run "$F" "$A"
check "closures queued via pending-actions" "12	close-duplicate	dup of #3	
14	relabel	add debt	gh issue edit 14" "$("$TOOLS/pending-actions.sh" list "$PEND")"
check "tracker never asked to close or edit" 0 "$(grep -c 'BAD VERB' "$LOG")"

reset; run "$F" '{"file_tickets":null,"labels":[],"queue_closures":false,"doc_pr":false}'
check "filing off and closures off does nothing" "0" "$(grep -c '^create' "$LOG")"
check "no pending file written" "no" "$([ -e "$PEND" ] && echo yes || echo no)"

reset; run "$F" null
check "actions null is report-only (exit 0)" 0 "$RC"
check "actions null makes no tracker call" 0 "$(wc -l < "$LOG" | tr -d ' ')"

reset; FAKE_LIST_RC=2 run "$F" "$A"
check "list exit 2 (cannot dedup) queues instead of filing" 0 "$(grep -c '^create' "$LOG")"
check "list exit 2 still exits 0" 0 "$RC"
reset; FAKE_LIST_RC=1 run "$F" "$A"
check "list failure aborts" 1 "$RC"
reset; FAKE_TRUNC=1 run "$F" "$A"
check "truncated list queues, exit 0" 0 "$RC"
check "truncated list files nothing" 0 "$(grep -c '^create' "$LOG")"
check "truncated list still queues the finding and closures" 3 "$("$TOOLS/pending-actions.sh" list "$PEND" | grep -c .)"

reset; FAKE_CREATE_RC=1 run "$F" "$A"
check "create failure exits 1" 1 "$RC"

reset; run '{"findings":[{"lens":"q","severity":"high","status":"NEW","title":"Bad","body":"x"},
 {"lens":"q","severity":"P1","status":"NEW","title":"Good","body":"y"}],"closures":[]}' "$A"
check "malformed severity is skipped, valid finding filed" "create|Good|review,debt" "$(grep '^create' "$LOG")"
check "malformed severity exits 0" 0 "$RC"

reset; run '{"findings":[{"lens":"q","severity":"P1","status":"NEW","title":"Unquoted var","body":"x"},
 {"lens":"r","severity":"P1","status":"NEW","title":"unquoted VAR!","body":"y"}],"closures":[]}' "$A"
check "same title in one run is filed once, regardless of lens" 1 "$(grep -c '^create' "$LOG")"
check "same-run duplicate cites the filed ticket id" 1 "$(grep -cE '^duplicate	[0-9a-f]{12}	#[0-9]+$' <<<"$out")"

reset; run '{"findings":[{"lens":"q","severity":"P1","status":"NEW","title":"日本語","body":"x"},
 {"lens":"q","severity":"P1","status":"NEW","title":"ログ","body":"y"}],"closures":[]}' "$A"
check "distinct non-ASCII titles are both filed" 2 "$(grep -c '^create' "$LOG")"

reset; FAKE_NO_LABELS=1 run "$F" "$A"
check "missing label: retried without labels and filed" "create|Unquoted var in x.sh|" "$(grep '^create' "$LOG")"
check "missing label: exit 0" 0 "$RC"

printf 'project-review-apply.test.sh: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
