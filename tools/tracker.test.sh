#!/usr/bin/env bash
# tracker.test.sh — behavioral checks for tracker.sh (provider seam: list and create).
# HOME is a temp dir; providers are fakes selected via START_TICKET_PROVIDER_DIR.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TR="$TOOLS/tracker.sh"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then pass=$((pass + 1))
  else fail=$((fail + 1)); printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/tracker-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
unset START_TICKET_PROVIDER_DIR
REPO="$ROOT/repo"; git init -q "$REPO"
PD="$ROOT/providers"; mkdir -p "$PD"

cat > "$PD/fake.sh" <<'EOF'
provider::available() { return 0; }
provider::list_issues() {  # <state> <limit>
  echo "$1 $2" >> "$FAKE_LOG"
  jq -n --argjson n "${FAKE_COUNT:-3}" --argjson l "$2" \
    '[range(0; ([$n,$l]|min)) | {id:(.+1), title:"t\(.+1)", state:"OPEN", labels:["a"], url:"u", updated:"2026-01-01", body:"b"}]'
}
provider::mark_in_progress() { echo "WRITE" >> "$FAKE_LOG"; }
provider::create_issue() {  # <title> <body-file> <labels-csv>
  echo "create|$1|$(cat "$2")|$3" >> "$FAKE_LOG"
  echo '{"id":99,"url":"u99"}'
}
EOF
cat > "$PD/nolist.sh" <<'EOF'
provider::available() { return 0; }
EOF
cat > "$PD/bad.sh" <<'EOF'
provider::available() { return 0; }
provider::list_issues() { echo null; }
EOF
cat > "$PD/down.sh" <<'EOF'
provider::available() { return 1; }
provider::list_issues() { :; }
EOF

tr() { (cd "$REPO" && FAKE_LOG="$ROOT/log" START_TICKET_PROVIDER_DIR="$PD" "$TR" "$@" 2>"$ROOT/err"); }

: > "$ROOT/log"
out="$(tr list --provider fake --limit 10)"; rc=$?
check "list succeeds" 0 "$rc"
check "issue count" 3 "$(jq '.issues|length' <<<"$out")"
check "not truncated" false "$(jq .truncated <<<"$out")"
check "issue shape" '["body","id","labels","state","title","updated","url"]' "$(jq -c '.issues[0]|keys' <<<"$out")"
check "default state is open" "open 11" "$(head -1 "$ROOT/log")"

out="$(FAKE_COUNT=50 tr list --provider fake --limit 5)"
check "truncated flagged" true "$(jq .truncated <<<"$out")"
check "truncated list trimmed to limit" 5 "$(jq '.issues|length' <<<"$out")"

tr list --provider fake --state all --limit 2 >/dev/null
check "state passed through" "all 3" "$(tail -1 "$ROOT/log")"

tr list --provider nolist >/dev/null; check "provider without list_issues exits 2" 2 "$?"
tr list --provider down >/dev/null;   check "unavailable provider fails" 1 "$?"
tr list --provider bad >/dev/null;    check "non-array provider output fails" 1 "$?"
tr list --provider nosuch >/dev/null; check "unknown provider fails" 1 "$?"
tr list --provider fake --state bogus >/dev/null; check "bad state rejected" 1 "$?"
tr list --provider fake --limit x >/dev/null; check "bad limit rejected" 1 "$?"
tr bogus --provider fake >/dev/null; check "unknown subcommand rejected" 1 "$?"
check "no start-ticket write function ever called" 0 "$(grep -c WRITE "$ROOT/log")"

printf 'the body' > "$ROOT/body"
out="$(tr create --provider fake --title "A title" --body-file "$ROOT/body" --label x --label y)"; rc=$?
check "create succeeds" 0 "$rc"
check "create prints id and url" '{"id":99,"url":"u99"}' "$out"
check "create passes title, body, joined labels" "create|A title|the body|x,y" "$(tail -1 "$ROOT/log")"
tr create --provider fake --body-file "$ROOT/body" >/dev/null; check "create needs title" 1 "$?"
tr create --provider fake --title t --body-file "$ROOT/nope" >/dev/null; check "create needs body file" 1 "$?"
tr create --provider fake --title t --body-file "$ROOT/body" --state open >/dev/null; check "create rejects list flags" 1 "$?"
tr create --provider nolist --title t --body-file "$ROOT/body" >/dev/null; check "provider without create_issue exits 2" 2 "$?"
tr create --provider down --title t --body-file "$ROOT/body" >/dev/null; check "create on unavailable provider fails" 1 "$?"

# shipped shortcut provider is a stub: list unsupported -> exit 2 (fake `short` makes it available)
mkdir -p "$ROOT/bin"; printf '#!/bin/sh\nexit 0\n' > "$ROOT/bin/short"; chmod +x "$ROOT/bin/short"
(cd "$REPO" && PATH="$ROOT/bin:$PATH" "$TR" list --provider shortcut >/dev/null 2>&1); check "shortcut stub exits 2" 2 "$?"

# shipped github provider: fake gh emits canned `gh issue list --json` output; --jq is applied by real jq
cat > "$ROOT/bin/gh" <<'EOF2'
#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
[ "$1 $2" = "issue create" ] && { echo "https://github.com/o/r/issues/42"; exit 0; }
[ "$1 $2" = "issue list" ] || exit 0
jqf=""; while [ $# -gt 0 ]; do [ "$1" = --jq ] && jqf="$2"; shift; done
echo '[{"number":7,"title":"T","state":"OPEN","labels":[{"name":"debt"},{"name":"x"}],"url":"u","updatedAt":"2026-02-02","body":"B"}]' | jq -c "$jqf"
EOF2
chmod +x "$ROOT/bin/gh"
out="$(cd "$REPO" && GH_LOG="$ROOT/ghlog" PATH="$ROOT/bin:$PATH" "$TR" list --provider github --state closed --limit 4 2>/dev/null)"
check "github list maps fields" '{"id":7,"title":"T","state":"OPEN","labels":["debt","x"],"url":"u","updated":"2026-02-02","body":"B"}' "$(jq -c '.issues[0]' <<<"$out")"
check "github list passes state and limit+1" "true" "$(grep -q -e '--state closed' "$ROOT/ghlog" && grep -q -e '--limit 5' "$ROOT/ghlog" && echo true)"

out="$(cd "$REPO" && GH_LOG="$ROOT/ghlog" PATH="$ROOT/bin:$PATH" "$TR" create --provider github --title T --body-file "$ROOT/body" --label a --label b 2>/dev/null)"
check "github create parses id from url" '{"id":42,"url":"https://github.com/o/r/issues/42"}' "$out"
check "github create passes labels and body file" "true" "$(grep -q -e "issue create --title T --body-file $ROOT/body --label a,b" "$ROOT/ghlog" && echo true)"
# shortcut stub defines no create_issue
(cd "$REPO" && PATH="$ROOT/bin:$PATH" "$TR" create --provider shortcut --title t --body-file "$ROOT/body" >/dev/null 2>&1); check "shortcut create exits 2" 2 "$?"

# github-mcp: the agent stages issues in TRACKER_MCP_DIR; create records a request and exits 2
MD="$ROOT/mcp"; mkdir -p "$MD"
echo '[{"id":1,"title":"a","state":"OPEN","labels":[],"url":"u","updated":"t","body":"b"}]' > "$MD/issues-open.json"
echo '[{"id":2,"title":"c","state":"CLOSED","labels":[],"url":"u","updated":"t","body":"b"}]' > "$MD/issues-closed.json"
mcp() { (cd "$REPO" && TRACKER_MCP_DIR="$MD" "$TR" "$@" 2>"$ROOT/err"); }
check "github-mcp lists staged open issues" '[1]' "$(mcp list --provider github-mcp --state open | jq -c '[.issues[].id]')"
check "github-mcp lists staged closed issues" '[2]' "$(mcp list --provider github-mcp --state closed | jq -c '[.issues[].id]')"
check "github-mcp all merges both" '[1,2]' "$(mcp list --provider github-mcp --state all | jq -c '[.issues[].id]')"
rm "$MD/issues-closed.json"; mcp list --provider github-mcp --state closed >/dev/null; check "github-mcp missing staged file fails" 1 "$?"
(cd "$REPO" && env -u TRACKER_MCP_DIR -u START_TICKET_MCP_DIR "$TR" list --provider github-mcp >/dev/null 2>&1); check "github-mcp without a staging dir is unavailable" 1 "$?"
mcp create --provider github-mcp --title "T 1" --body-file "$ROOT/body" --label a,b >/dev/null; check "github-mcp create exits 2" 2 "$?"
check "github-mcp create records a request" '{"title":"T 1","body":"the body","labels":["a","b"]}' "$(cat "$MD"/create/*.json | jq -c .)"

printf 'tracker.test.sh: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
