#!/usr/bin/env bash
# tracker.test.sh — behavioral checks for tracker.sh (read-only provider seam).
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
EOF
cat > "$PD/nolist.sh" <<'EOF'
provider::available() { return 0; }
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
tr list --provider nosuch >/dev/null; check "unknown provider fails" 1 "$?"
tr list --provider fake --state bogus >/dev/null; check "bad state rejected" 1 "$?"
tr list --provider fake --limit x >/dev/null; check "bad limit rejected" 1 "$?"
tr create --provider fake >/dev/null; check "write subcommand rejected" 1 "$?"
check "no write function ever called" 0 "$(grep -c WRITE "$ROOT/log")"

# shipped shortcut provider is a stub: list unsupported -> exit 2 (fake `short` makes it available)
mkdir -p "$ROOT/bin"; printf '#!/bin/sh\nexit 0\n' > "$ROOT/bin/short"; chmod +x "$ROOT/bin/short"
(cd "$REPO" && PATH="$ROOT/bin:$PATH" "$TR" list --provider shortcut >/dev/null 2>&1); check "shortcut stub exits 2" 2 "$?"

printf 'tracker.test.sh: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
