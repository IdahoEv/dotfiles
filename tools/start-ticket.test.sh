#!/usr/bin/env bash
# start-ticket.test.sh — behavioral checks for start-ticket.sh --session (the
# non-ticket discussion launch behind /discuss).
#
#   start-ticket.test.sh
#
# Plain script, exits non-zero on failure. HOME is a temp dir so the real
# ~/.config can't leak in; --launcher none so nothing is opened.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ST="$TOOLS/start-ticket.sh"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

has() {  # <description> <needle> <file>
  if grep -qF -- "$2" "$3" 2>/dev/null; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  %s does not contain: [%s]\n' "$1" "$3" "$2" >&2
  fi
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/start-ticket-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME"
export TMPDIR="$ROOT/tmp"; mkdir -p "$TMPDIR"
unset GIT_TOOLS_PROJECTS_DIR CLAUDE_JOB_DIR START_TICKET_LAUNCHER GT_LABEL_OVERRIDE
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

get() { sed -n "s/^$1=//p"; }   # <key> on stdin → value
session() { (cd "$1" && shift && "$ST" --session "$@" --launcher none 2>/dev/null); }

# ---- normal repo + linked worktree -------------------------------------------
git init -q -b main "$ROOT/widgets"
mkdir -p "$ROOT/widgets/.claude"
printf '## Working agreement\n\nTicket {{ID}} on {{BRANCH}}.\n' > "$ROOT/widgets/.claude/kickoff-preamble.md"
git -C "$ROOT/widgets" add -A && git -C "$ROOT/widgets" commit -q -m init
git -C "$ROOT/widgets" worktree add -q "$ROOT/wt" -b feature
branches_before="$(git -C "$ROOT/widgets" branch --list | wc -l)"

out="$(session "$ROOT/widgets" "Bg Cost")"
check "dir is the main checkout" "$ROOT/widgets" "$(get dir <<<"$out")"
check "label carries [TALK] and the topic" "[TALK] Bg Cost" "$(get label <<<"$out")"
kf="$(get kickoff <<<"$out")"
has "kickoff names the topic" "Topic: Bg Cost" "$kf"
has "kickoff carries the preamble" "## Working agreement" "$kf"
has "kickoff has ticket placeholders emptied" "Ticket  on ." "$kf"
has "kickoff carries the session rules" "Let's code this" "$kf"
has "kickoff carries the color step" "session-label.sh --color project" "$kf"
check "no branch created" "$branches_before" "$(git -C "$ROOT/widgets" branch --list | wc -l)"
check "no worktree created" "2" "$(git -C "$ROOT/widgets" worktree list | wc -l | tr -d ' ')"

out="$(session "$ROOT/wt" "Bg Cost")"
check "from a linked worktree, dir is still the main checkout" "$ROOT/widgets" "$(get dir <<<"$out")"

out="$(session "$ROOT/widgets")"
check "no topic → <repo> Discussion" "[TALK] widgets Discussion" "$(get label <<<"$out")"

out="$(session "$ROOT/widgets" "Cost: bg/launcher?")"
check "topic punctuation is sanitized" "[TALK] Cost bg launcher" "$(get label <<<"$out")"

out="$(session "$ROOT/widgets" "Bg Cost" --about "How much does a bg launch cost?")"
has "--about text reaches the kickoff" "How much does a bg launch cost?" "$(get kickoff <<<"$out")"

# ---- bare repo with a main worktree (the dotfiles layout) --------------------
git clone -q --bare "$ROOT/widgets" "$ROOT/gadgets/.git"
git -C "$ROOT/gadgets/.git" worktree add -q "$ROOT/gadgets/main" main
git -C "$ROOT/gadgets/.git" worktree add -q "$ROOT/gadgets/topic" -b topic

out="$(session "$ROOT/gadgets/topic" "Bare Check")"
check "bare repo → the default branch's worktree" "$ROOT/gadgets/main" "$(get dir <<<"$out")"

# ---- telemetry --------------------------------------------------------------
export WF_TELEMETRY_LOG="$ROOT/events.jsonl"
STP="$ROOT/providers"; mkdir -p "$STP"
cat > "$STP/fake.sh" <<'P'
provider::available() { return 0; }
provider::fetch() { ST_TITLE="Fake ticket"; ST_BODY="body"; ST_URL=""; ST_PARENT=""; }
provider::create_worktree() { [ -n "$FAKE_WT" ] || return 1; echo "$FAKE_WT"; }
provider::mark_in_progress() { return 0; }
P
git -C "$ROOT/widgets" remote add origin git@github.com:acme/widgets.git
start() { (cd "$ROOT/widgets" && START_TICKET_PROVIDER_DIR="$STP" "$ST" 7 --provider fake --no-tab "$@" >/dev/null 2>&1); }
FAKE_WT="$ROOT/wt" start
ev() { tail -1 "$WF_TELEMETRY_LOG" | jq -r "$1"; }
check "ticket.start keyed by the ticket, not the branch" "ticket.start acme/widgets#7 ok no-tab" \
  "$(ev '"\(.event) \(.run_id) \(.outcome) \(.mode)"')"
FAKE_WT="" start
check "failed start recorded" "fail 1" "$(ev '"\(.outcome) \(.exit_code)"')"
n="$(wc -l < "$WF_TELEMETRY_LOG")"
(cd "$ROOT/widgets" && START_TICKET_PROVIDER_DIR="$STP" "$ST" 7 --provider fake --print-title >/dev/null 2>&1)
check "--print-title records nothing" "$n" "$(wc -l < "$WF_TELEMETRY_LOG")"

n="$(wc -l < "$WF_TELEMETRY_LOG")"
# provider never resolved (no gh, no short, no conf) → the failure must not be
# filed under a guessed scheme; the event is dropped instead.
(cd "$ROOT/widgets" && PATH=/usr/bin:/bin START_TICKET_PROVIDER_DIR="$STP" "$ST" 8 --no-tab >/dev/null 2>&1)
check "unresolved provider records nothing" "$n" "$(wc -l < "$WF_TELEMETRY_LOG")"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
