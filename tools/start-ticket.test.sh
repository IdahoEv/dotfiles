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
# Never measure the real host: pin a healthy memory reading (guard tests override it).
export MEM_GUARD_HOST_FIXTURE="level=normal free_pct=80" MEM_GUARD_PS_FIXTURE="$ROOT/no-ps"
unset MEM_GUARD_OVERRIDE
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

# ---- chains (comma-separated ids: one worktree, one session) --------------------
CP="$ROOT/chainproviders"; mkdir -p "$CP"
cat > "$CP/fake.sh" <<'P'
provider::available() { return 0; }
provider::fetch() { echo "fetch $1" >> "$FAKE_LOG"; ST_TITLE="Ticket $1"; ST_BODY="body $1"; ST_URL=""; ST_PARENT=""; }
provider::create_worktree() { echo "create $1" >> "$FAKE_LOG"; echo "$FAKE_WT"; }
provider::mark_in_progress() { echo "mark $1" >> "$FAKE_LOG"; }
P
git -C "$ROOT/widgets" worktree add -q "$ROOT/cwt" -b 7-ticket-7
export FAKE_WT="$ROOT/cwt" FAKE_LOG="$ROOT/chain.log"
chain() {  # <ids> [flags…] → stdout; stderr kept in $ROOT/chain.err
  (cd "$ROOT/widgets" && START_TICKET_PROVIDER_DIR="$CP" "$ST" "$@" --provider fake --no-tab 2>"$ROOT/chain.err")
}
: > "$FAKE_LOG"
out="$(chain 7,8,9)"
check "chain: one worktree, named from the head" "create 7" "$(grep '^create' "$FAKE_LOG")"
check "chain: every ticket is marked in progress" "mark 7 mark 8 mark 9" "$(grep '^mark' "$FAKE_LOG" | tr '\n' ' ' | sed 's/ $//')"
check "chain: stdout carries the chain" "7,8,9" "$(get chain <<<"$out")"
check "chain: stdout branch is the head's" "7-ticket-7" "$(get branch <<<"$out")"
check "chain: ids recorded in order" "7,8,9" "$("$TOOLS/workstream.sh" chain-ids --dir "$ROOT/cwt")"
check "chain: .workstream.json written in worktree" "yes" "$([ -f "$ROOT/cwt/.workstream.json" ] && echo yes || echo no)"
kf="$(get kickoff <<<"$out")"
has "chain: kickoff lists the head ticket" "## 7 — Ticket 7" "$kf"
has "chain: kickoff lists the last ticket" "## 9 — Ticket 9" "$kf"
check "chain: kickoff lists tickets in order" "7 8 9" "$(sed -n 's/^## \([0-9]*\) — .*/\1/p' "$kf" | tr '\n' ' ' | sed 's/ $//')"
has "chain: kickoff states the chain" "chain of 3" "$kf"
has "chain: kickoff says plan once" "Plan the whole chain once" "$kf"
has "chain: kickoff asks for per-link review" "--rounds 1" "$kf"
has "chain: kickoff asks for the final review" "up to 5 rounds" "$kf"
has "chain: kickoff has the session open the PR" "/open-pr" "$kf"
has "chain: kickoff covers the draft-PR failure path" "--draft" "$kf"
has "chain: preamble ID is the head" "Ticket 7 on 7-ticket-7." "$kf"

: > "$FAKE_LOG"
out="$(chain 7)"
check "single id: no chain stdout" "" "$(get chain <<<"$out")"
check "single id re-run keeps the chain record" "7,8,9" "$("$TOOLS/workstream.sh" chain-ids --dir "$ROOT/cwt")"
check "single id: kickoff has no chain block" "0" "$(grep -c 'chain of' "$(get kickoff <<<"$out")")"
check "single id: marks only itself" "mark 7" "$(grep '^mark' "$FAKE_LOG")"

check "no marker: kickoff has no unattended block" "0" "$(grep -c 'Unattended review' "$(get kickoff <<<"$out")")"
stderr_without_marker="$(cat "$ROOT/chain.err")"
touch "$HOME/.config/github-review-unattended" 2>/dev/null || { mkdir -p "$HOME/.config"; touch "$HOME/.config/github-review-unattended"; }
out="$(chain 7)"
check "marker: unattended kickoff adds nothing to stderr" "$stderr_without_marker" "$(cat "$ROOT/chain.err")"
has "marker: single-ticket kickoff carries the unattended block" "/github-review-comments" "$(get kickoff <<<"$out")"
has "marker: unattended kickoff preserves the literal round-cap option" '`--max-rounds N`' "$(get kickoff <<<"$out")"
has "marker: block forbids merging" "Do not merge" "$(get kickoff <<<"$out")"
out="$(chain 7,8,9)"
has "marker: chain kickoff carries the unattended block" "## Unattended review" "$(get kickoff <<<"$out")"
touch "$HOME/.config/local-review-only"
out="$(chain 7)"
check "local-review-only suppresses the block" "0" "$(grep -c 'Unattended review' "$(get kickoff <<<"$out")")"
rm -f "$HOME/.config/github-review-unattended" "$HOME/.config/local-review-only"
out="$(chain 7,8,9)"

# Four links are fine now; only the label collapses.
git -C "$ROOT/widgets" worktree add -q "$ROOT/cwt4" -b 7-ticket-7b
FAKE_WT="$ROOT/cwt4" chain 7,8,9,10 >/dev/null
check "chain over 3 links is accepted" "7,8,9,10" "$(get chain <<<"$(FAKE_WT="$ROOT/cwt4" chain 7,8,9,10)")"
chain 7,8,7 >/dev/null; rc=$?
check "duplicate ids are refused" "1" "$rc"
chain 7,,8 >/dev/null; rc=$?
check "empty id is refused" "1" "$rc"
: > "$FAKE_LOG"
(cd "$ROOT/widgets" && START_TICKET_PROVIDER_DIR="$CP" "$ST" 7,8 --provider shortcut --no-tab >/dev/null 2>"$ROOT/chain.err"); rc=$?
check "chain with the shortcut provider is refused" "1" "$rc"
has "shortcut refusal is explained" "github" "$ROOT/chain.err"
check "refusals create nothing" "" "$(grep '^create' "$FAKE_LOG")"

# Chained start must fail closed if the workstream record cannot be written.
git init -q -b main "$ROOT/chainfail"
git -C "$ROOT/chainfail" config user.email t@e; git -C "$ROOT/chainfail" config user.name t
echo a > "$ROOT/chainfail/a"; git -C "$ROOT/chainfail" add a; git -C "$ROOT/chainfail" commit -q -m init
git -C "$ROOT/chainfail" worktree add -q "$ROOT/cf_wt" -b 7-ticket-7
: > "$ROOT/chainfail/.git/info/exclude"
chmod 444 "$ROOT/chainfail/.git/info/exclude"
(cd "$ROOT/chainfail" && FAKE_WT="$ROOT/cf_wt" START_TICKET_PROVIDER_DIR="$CP" "$ST" 7,8 --provider fake --no-tab >/dev/null 2>"$ROOT/cf.err"); rc=$?
chmod 644 "$ROOT/chainfail/.git/info/exclude"
check "chain: record write failure fails closed" "1" "$rc"
has "chain: record write failure is explained" "workstream record not written" "$ROOT/cf.err"

# bg launcher: the session name carries every id; claude is a recording stub.
mkdir -p "$ROOT/stubbin"
printf '#!/bin/sh\nprintf "%%s\\n" "$@" > "%s/claude.args"\n' "$ROOT" > "$ROOT/stubbin/claude"; chmod +x "$ROOT/stubbin/claude"
(cd "$ROOT/widgets" && PATH="$ROOT/stubbin:$PATH" START_TICKET_PROVIDER_DIR="$CP" "$ST" 7,8 --provider fake --launcher bg >/dev/null 2>&1)
has "chain: session name joins the ids" "[PLAN] fake-7+8 ticket 7" "$ROOT/claude.args"
git -C "$ROOT/widgets" worktree add -q "$ROOT/swt" -b 7-single
(cd "$ROOT/widgets" && FAKE_WT="$ROOT/swt" PATH="$ROOT/stubbin:$PATH" START_TICKET_PROVIDER_DIR="$CP" "$ST" 7 --provider fake --launcher bg >/dev/null 2>&1)
has "single id: session name unchanged" "[PLAN] fake-7 ticket 7" "$ROOT/claude.args"
(cd "$ROOT/widgets" && PATH="$ROOT/stubbin:$PATH" START_TICKET_PROVIDER_DIR="$CP" FAKE_WT="$ROOT/cwt4" "$ST" 7,8,9,10 --provider fake --launcher bg >/dev/null 2>&1)
has "long chain: session name keeps chain ids" "[PLAN] fake-7+8+9+10 ticket 7" "$ROOT/claude.args"
git -C "$ROOT/widgets" worktree add -q "$ROOT/swt_is" -b Is160-workstream-record
(cd "$ROOT/widgets" && FAKE_WT="$ROOT/swt_is" PATH="$ROOT/stubbin:$PATH" START_TICKET_PROVIDER_DIR="$CP" "$ST" 160 --provider fake --launcher bg >/dev/null 2>&1)
has "Is<N> branch: session name uses resolver key" "[PLAN] fake-160 ticket 160" "$ROOT/claude.args"

# ---- --in-place (cloud sessions: one fixed checkout, no worktree) ---------------
IP="$ROOT/inplaceproviders"; mkdir -p "$IP"
cat > "$IP/fake.sh" <<'P'
provider::available() { return 0; }
provider::fetch() { ST_TITLE="Fake ticket"; ST_BODY="body"; ST_URL=""; ST_PARENT=""; ST_BRANCH="$1-fake-ticket"; }
provider::create_worktree() { echo "create $1" >> "$FAKE_LOG"; echo "$ROOT/should-not-exist"; }
provider::mark_in_progress() { echo "mark $1" >> "$FAKE_LOG"; }
P
mkdir -p "$ROOT/widgets/.workstreams"
cp "$TOOLS/../.workstreams/settings.json" "$ROOT/widgets/.workstreams/settings.json"
git -C "$ROOT/widgets" add .workstreams/settings.json && git -C "$ROOT/widgets" commit -q -m "Add repo ticket config"
git clone -q "$ROOT/widgets" "$ROOT/cloud"
git -C "$ROOT/cloud" checkout -q -b ccr-session
: > "$FAKE_LOG"
out="$(cd "$ROOT/cloud" && START_TICKET_PROVIDER_DIR="$IP" "$ST" 5 --provider fake --in-place --no-tab 2>/dev/null)"
check "in-place: worktree is the current checkout" "$ROOT/cloud" "$(get worktree <<<"$out")"
check "in-place: ticket branch checked out" "5-fake-ticket" "$(git -C "$ROOT/cloud" branch --show-current)"
check "in-place: no worktree created" "" "$(grep '^create' "$FAKE_LOG")"
check "in-place: ticket marked in progress" "mark 5" "$(grep '^mark' "$FAKE_LOG")"
has "in-place: kickoff written" "Fake ticket" "$(get kickoff <<<"$out")"
(cd "$ROOT/cloud" && START_TICKET_PROVIDER_DIR="$IP" "$ST" 5 --provider fake --in-place --no-tab >/dev/null 2>&1); rc=$?
check "in-place: re-run on the ticket branch succeeds" "0" "$rc"
git -C "$ROOT/cloud" checkout -q ccr-session
(cd "$ROOT/cloud" && START_TICKET_PROVIDER_DIR="$IP" "$ST" 5 --provider fake --in-place --no-tab >/dev/null 2>&1); rc=$?
check "in-place: re-run re-checks-out the existing branch" "0 5-fake-ticket" "$rc $(git -C "$ROOT/cloud" branch --show-current)"

# The ticket branch starts from the default branch, not from a session branch carrying other commits.
git -C "$ROOT/cloud" checkout -q ccr-session
git -C "$ROOT/cloud" branch -q -D 5-fake-ticket
git -C "$ROOT/cloud" commit -q --allow-empty -m "unrelated session work"
(cd "$ROOT/cloud" && START_TICKET_PROVIDER_DIR="$IP" "$ST" 5 --provider fake --in-place --no-tab >/dev/null 2>&1)
check "in-place: new ticket branch starts at the default branch" "0" "$(git -C "$ROOT/cloud" rev-list origin/main..HEAD | wc -l | tr -d ' ')"
# A branch that exists only on origin is continued, not forked.
git -C "$ROOT/widgets" branch 6-fake-ticket
git -C "$ROOT/widgets" checkout -q 6-fake-ticket && git -C "$ROOT/widgets" commit -q --allow-empty -m "remote ticket work" && git -C "$ROOT/widgets" checkout -q main
(cd "$ROOT/cloud" && START_TICKET_PROVIDER_DIR="$IP" "$ST" 6 --provider fake --in-place --no-tab >/dev/null 2>&1)
check "in-place: origin-only ticket branch is tracked" "origin/6-fake-ticket" "$(git -C "$ROOT/cloud" rev-parse --abbrev-ref 6-fake-ticket@{upstream})"
# Uncommitted changes block the switch.
git -C "$ROOT/cloud" checkout -q ccr-session
echo dirty >> "$ROOT/cloud/.claude/kickoff-preamble.md"
(cd "$ROOT/cloud" && START_TICKET_PROVIDER_DIR="$IP" "$ST" 7 --provider fake --in-place --no-tab >/dev/null 2>"$ROOT/dirty.err"); rc=$?
check "in-place: dirty tree is refused" "1 ccr-session" "$rc $(git -C "$ROOT/cloud" branch --show-current)"
has "in-place: dirty refusal is explained" "commit, stash or remove" "$ROOT/dirty.err"
git -C "$ROOT/cloud" checkout -q -- .
echo stray > "$ROOT/cloud/stray.txt"
(cd "$ROOT/cloud" && START_TICKET_PROVIDER_DIR="$IP" "$ST" 7 --provider fake --in-place --no-tab >/dev/null 2>&1); rc=$?
check "in-place: untracked files are refused too" "1 ccr-session" "$rc $(git -C "$ROOT/cloud" branch --show-current)"
rm -f "$ROOT/cloud/stray.txt"

# ---- github-mcp provider (cloud: gh unauthenticated, tickets handed over as JSON) ----
git clone -q "$ROOT/widgets" "$ROOT/mcpcloud"
git -C "$ROOT/mcpcloud" checkout -q -b ccr-session
MD="$ROOT/mcp-handoff"; mkdir -p "$MD"
printf '{"number":12,"title":"Cloud ticket","body":"head body","state":"OPEN","url":"https://github.com/acme/widgets/issues/12","labels":["bug"],"parent":9}\n' > "$MD/12.json"
printf '{"number":13,"title":"Second ticket","body":"tail body","state":"OPEN","url":"https://github.com/acme/widgets/issues/13","labels":[],"parent":null}\n' > "$MD/13.json"
printf '{"number":14,"title":"Done","body":"x","state":"CLOSED","url":"","labels":[],"parent":null}\n' > "$MD/14.json"
NOGH="$ROOT/nogh"; mkdir -p "$NOGH"
printf '#!/bin/sh\nexit 1\n' > "$NOGH/gh"; chmod +x "$NOGH/gh"
mcp() {  # <env-assignments-free> args… → stdout; stderr in $ROOT/mcp.err
  (cd "$ROOT/mcpcloud" && PATH="$NOGH:$PATH" "$ST" "$@" --in-place --no-tab 2>"$ROOT/mcp.err")
}

out="$(START_TICKET_MCP_DIR="$MD" mcp 12)"; rc=$?
check "mcp: exits 0 with no gh and no conf" "0" "$rc"
check "mcp: autodetected from START_TICKET_MCP_DIR" "github-mcp" "$(get provider <<<"$out")"
check "mcp: ticket branch checked out" "Is12-cloud-ticket" "$(git -C "$ROOT/mcpcloud" branch --show-current)"
check "mcp: in-progress is left for the caller to repair" "unknown" "$(get ticket_in_progress <<<"$out")"
check "mcp: parent carried" "9" "$(get ticket_parent <<<"$out")"
has "mcp: kickoff has the title" "Cloud ticket" "$(get kickoff <<<"$out")"
has "mcp: kickoff has the body" "head body" "$(get kickoff <<<"$out")"
has "mcp: kickoff has the url" "issues/12" "$(get kickoff <<<"$out")"
has "mcp: kickoff carries the plan-gate sequence" "Plan approval authorizes everything below" "$(get kickoff <<<"$out")"
has "mcp: kickoff says stop before merge" "Stop before merge" "$(get kickoff <<<"$out")"
check "mcp: no design gate without the key" "0" "$(grep -c 'Design gate' "$(get kickoff <<<"$out")" || true)"

git -C "$ROOT/mcpcloud" checkout -q ccr-session
mkdir -p "$HOME/.config/start-ticket"
printf 'design_gate=new or changed visuals, layout or style\n' > "$HOME/.config/start-ticket/config"
out="$(START_TICKET_MCP_DIR="$MD" mcp 12)"
has "mcp: design_gate key adds the design pause" "Design gate" "$(get kickoff <<<"$out")"
has "mcp: design gate carries the project criteria" "new or changed visuals" "$(get kickoff <<<"$out")"
rm -f "$HOME/.config/start-ticket/config"
git -C "$ROOT/mcpcloud" checkout -q ccr-session
out="$(START_TICKET_MCP_DIR="$MD" mcp 12,13)"; rc=$?
check "mcp chain: exits 0" "0" "$rc"
check "mcp chain: stdout carries the chain" "12,13" "$(get chain <<<"$out")"
check "mcp chain: kickoff lists both tickets" "12 13" "$(sed -n 's/^## \([0-9]*\) — .*/\1/p' "$(get kickoff <<<"$out")" | tr '\n' ' ' | sed 's/ $//')"

git -C "$ROOT/mcpcloud" checkout -q ccr-session
START_TICKET_MCP_DIR="$MD" mcp 99 >/dev/null; rc=$?
check "mcp: missing handoff file fails" "1" "$rc"
has "mcp: missing handoff names the id" "99" "$ROOT/mcp.err"
has "mcp: missing handoff names the fix" "/start" "$ROOT/mcp.err"
START_TICKET_MCP_DIR="$MD" mcp 14 >/dev/null; rc=$?
check "mcp: closed issue is refused" "1" "$rc"
has "mcp: closed issue is explained" "not OPEN" "$ROOT/mcp.err"
START_TICKET_MCP_DIR="$MD" mcp '../mcp-handoff/12' >/dev/null; rc=$?
check "mcp: path-like id is refused" "1" "$rc"
has "mcp: path-like id is explained" "invalid ticket id" "$ROOT/mcp.err"
check "mcp: refusals leave the session branch" "ccr-session" "$(git -C "$ROOT/mcpcloud" branch --show-current)"

printf '{"number":15,"title":"Object labels","body":"b","state":"OPEN","url":"","labels":[{"name":"Enhancement"}],"parent":null}\n' > "$MD/15.json"
git -C "$ROOT/mcpcloud" checkout -q ccr-session
mkdir -p "$HOME/.config/start-ticket"
printf 'branch.template={type}/{key}-{desc}\n' > "$HOME/.config/start-ticket/config"
out="$(START_TICKET_MCP_DIR="$MD" mcp 15)"
rm -f "$HOME/.config/start-ticket/config"
check "mcp: object-form labels set the branch type" "feat/Is15-object-labels" "$(git -C "$ROOT/mcpcloud" branch --show-current)"

# Neither path available: one message naming both fixes.
# Autodetect falls through to Shortcut when `short` is on PATH, so this case only
# applies on hosts without it.
if command -v short >/dev/null; then
  echo "SKIP no-handoff autodetect cases (short is installed on this host)"
else
mcp 12 >/dev/null; rc=$?
check "no gh auth, no handoff: fails" "1" "$rc"
check "no gh auth, no handoff: one error line" "1" "$(wc -l < "$ROOT/mcp.err" | tr -d ' ')"
has "unavailable message names gh auth login" "gh auth login" "$ROOT/mcp.err"
has "unavailable message names the MCP path" "--provider github-mcp" "$ROOT/mcp.err"
fi
(cd "$ROOT/mcpcloud" && PATH="$NOGH:$PATH" "$ST" 12 --provider github --in-place --no-tab >/dev/null 2>"$ROOT/mcp.err"); rc=$?
check "explicit github with unauthed gh: fails" "1" "$rc"
has "explicit github failure uses the same message" "--provider github-mcp" "$ROOT/mcp.err"

# A fresh checkout uses the tracked provider config even if `gh repo view` fails.
cp "$IP/fake.sh" "$IP/github.sh"
printf '#!/bin/sh\nexit 1\n' > "$ROOT/stubbin/gh"; chmod +x "$ROOT/stubbin/gh"
out="$(cd "$ROOT/cloud" && PATH="$ROOT/stubbin:$PATH" START_TICKET_PROVIDER_DIR="$IP" \
  "$ST" 8 --in-place --no-tab 2>"$ROOT/cloud-provider.err")"; rc=$?
check "in-place: configured start succeeds without --provider" "0" "$rc"
check "in-place: tracked config selects GitHub" "github" "$(get provider <<<"$out")"

# ---- clipboard fallback (open_tab via --tab-only, not in iTerm) ----------------
CB="$ROOT/clip"; mkdir -p "$CB/bin" "$CB/sys"
for t in git cat dirname basename sed tr wc mktemp rm date grep awk head cut sort uname env bash; do
  p="$(command -v "$t")" && ln -sf "$p" "$CB/sys/$t"
done
printf 'kickoff text\n' > "$CB/kf"
stub_clip() {  # <name>
  printf '#!/bin/sh\ncat > "%s/%s.out"\n' "$CB" "$1" > "$CB/bin/$1"; chmod +x "$CB/bin/$1"
}
tab_only() {  # PATH-dir-list → stdout
  (cd "$ROOT/widgets" && env -u TERM_PROGRAM -u LC_TERMINAL PATH="$1" "$ST" --tab-only "$ROOT/wt" "$CB/kf" --launcher iterm 2>/dev/null)
}
out="$(tab_only "$CB/sys")"
has "no clipboard tool: prints kickoff path" "Kickoff is at $CB/kf" <(printf '%s' "$out")
check "no clipboard tool: does not claim clipboard" "" "$(grep -F 'on the clipboard' <<<"$out")"
stub_clip xclip
out="$(tab_only "$CB/bin:$CB/sys")"
has "xclip fallback receives kickoff" "kickoff text" "$CB/xclip.out"
has "xclip fallback claims clipboard" "on the clipboard" <(printf '%s' "$out")
stub_clip wl-copy
tab_only "$CB/bin:$CB/sys" >/dev/null
has "wl-copy preferred over xclip" "kickoff text" "$CB/wl-copy.out"
printf '#!/bin/sh\nexit 1\n' > "$CB/bin/wl-copy"; printf '#!/bin/sh\nexit 1\n' > "$CB/bin/xclip"
stub_clip clip.exe
out="$(tab_only "$CB/bin:$CB/sys")"
has "failing wl-copy/xclip fall through to clip.exe" "kickoff text" "$CB/clip.exe.out"

# ---- setup-ticket-profile.sh off macOS ----------------------------------------
mkdir -p "$CB/uname-bin"
printf '#!/bin/sh\necho Linux\n' > "$CB/uname-bin/uname"; chmod +x "$CB/uname-bin/uname"
out="$(PATH="$CB/uname-bin:$PATH" "$TOOLS/setup-ticket-profile.sh" 2>&1)"; rc=$?
check "profile setup exits 0 on Linux" "0" "$rc"
check "profile setup creates no ~/Library" "no" "$([ -e "$HOME/Library" ] && echo yes || echo no)"

# ---- mem-guard on the launch path ---------------------------------------------
rm -f "$ROOT/claude.args"
mem_tab() {  # <host fixture> [extra env...] → rc; stderr in $ROOT/mem.err
  (cd "$ROOT/widgets" && env MEM_GUARD_HOST_FIXTURE="$1" "${@:2}" PATH="$ROOT/stubbin:$PATH" \
    "$ST" --tab-only "$ROOT/wt" "$CB/kf" --launcher bg >/dev/null 2>"$ROOT/mem.err")
}
mem_tab "level=critical free_pct=3"; rc=$?
check "blocked by mem-guard: tab-only exits non-zero" "1" "$rc"
has "blocked by mem-guard: says so" "launch blocked by mem-guard" "$ROOT/mem.err"
check "blocked by mem-guard: nothing launched" "no" "$([ -e "$ROOT/claude.args" ] && echo yes || echo no)"
mem_tab "level=critical free_pct=3" MEM_GUARD_OVERRIDE=1; rc=$?
check "override: tab-only launches" "0 yes" "$rc $([ -e "$ROOT/claude.args" ] && echo yes || echo no)"
has "override: announced" "OVERRIDE" "$ROOT/mem.err"
rm -f "$ROOT/claude.args"
(cd "$ROOT/widgets" && MEM_GUARD_HOST_FIXTURE="level=critical free_pct=3" PATH="$ROOT/stubbin:$PATH" START_TICKET_PROVIDER_DIR="$CP" "$ST" 7 --provider fake --launcher bg >/dev/null 2>"$ROOT/mem.err"); rc=$?
check "blocked ticket start exits non-zero" "1" "$rc"
check "blocked ticket start: no session launched" "no" "$([ -e "$ROOT/claude.args" ] && echo yes || echo no)"
(cd "$ROOT/widgets" && MEM_GUARD_HOST_FIXTURE="level=critical free_pct=3" START_TICKET_PROVIDER_DIR="$CP" PATH="$ROOT/stubbin:$PATH" "$ST" 7 --provider fake --no-tab --launcher bg >/dev/null 2>"$ROOT/mem.err"); rc=$?
check "--no-tab launches nothing so is not guarded (--tab-only is the gate)" "0" "$rc"
(cd "$ROOT/widgets" && MEM_GUARD_HOST_FIXTURE="level=critical free_pct=3" "$ST" --session "mem topic" --launcher none >/dev/null 2>&1); rc=$?
check "launcher none is never guarded" "0" "$rc"
(cd "$ROOT/widgets" && MEM_GUARD_HOST_FIXTURE="level=critical free_pct=3" START_TICKET_PROVIDER_DIR="$CP" "$ST" 7 --provider fake --print-title >/dev/null 2>&1); rc=$?
check "print-title is read-only and never guarded" "0" "$rc"
(cd "$ROOT/widgets" && START_TICKET_MEM_GUARD="$ROOT/nope" PATH="$ROOT/stubbin:$PATH" "$ST" --tab-only "$ROOT/wt" "$CB/kf" --launcher bg >/dev/null 2>"$ROOT/mem.err"); rc=$?
check "missing guard script does not block" "0" "$rc"
has "missing guard script is reported" "launching without a memory check" "$ROOT/mem.err"

# ---- --no-tab + --tab-only preserves GT_LABEL_OVERRIDE from .workstream.json ----
rm -f "$ROOT/claude.args"
out_lbl="$(cd "$ROOT/widgets" && FAKE_WT="$ROOT/swt" GT_LABEL_OVERRIDE="Custom Row Label" \
  START_TICKET_PROVIDER_DIR="$CP" "$ST" 7 --provider fake --no-tab 2>/dev/null)"
wt_lbl="$(printf '%s\n' "$out_lbl" | awk -F= '$1=="worktree"{print $2}')"
kf_lbl="$(printf '%s\n' "$out_lbl" | awk -F= '$1=="kickoff"{print $2}')"
(cd "$ROOT/widgets" && env -u GT_LABEL_OVERRIDE MEM_GUARD_OVERRIDE=1 \
  PATH="$ROOT/stubbin:$PATH" "$ST" --tab-only "$wt_lbl" "$kf_lbl" --launcher bg >/dev/null 2>&1)
has "--tab-only preserves model-written label" "[PLAN] fake-7 custom row label" "$ROOT/claude.args"

# ---- agy-tmux launcher & auto-selection ---------------------------------------
AT_STUB="$ROOT/stub-agy-tmux.sh"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" > "%s/agy-tmux.args"\n' "$ROOT" > "$AT_STUB"
chmod +x "$AT_STUB"

TMUX_DASH_STUB="$ROOT/stub-tmux-dash.sh"
printf '#!/bin/sh\necho 1\n' > "$TMUX_DASH_STUB"
chmod +x "$TMUX_DASH_STUB"

TMUX_PLAIN_STUB="$ROOT/stub-tmux-plain.sh"
printf '#!/bin/sh\necho ""\n' > "$TMUX_PLAIN_STUB"
chmod +x "$TMUX_PLAIN_STUB"

rm -f "$ROOT/agy-tmux.args" "$ROOT/claude.args"
(cd "$ROOT/widgets" && START_TICKET_AGY_TMUX="$AT_STUB" PATH="$ROOT/stubbin:$PATH" \
  "$ST" --tab-only "$ROOT/wt" "$CB/kf" --launcher agy-tmux >/dev/null 2>&1)
has "explicit --launcher agy-tmux calls --window" "--window $ROOT/wt $CB/kf" "$ROOT/agy-tmux.args"

mkdir -p "$HOME/.config/start-ticket"
printf 'launcher=bg\n' > "$HOME/.config/start-ticket/config"

rm -f "$ROOT/agy-tmux.args" "$ROOT/claude.args"
(cd "$ROOT/widgets" && ANTIGRAVITY_AGENT=1 TMUX="stub,1,0" TMUX_PANE="%1" \
  AGY_TMUX_TMUX_BIN="$TMUX_DASH_STUB" START_TICKET_AGY_TMUX="$AT_STUB" PATH="$ROOT/stubbin:$PATH" \
  "$ST" --tab-only "$ROOT/wt" "$CB/kf" >/dev/null 2>&1)
has "agy inside @agy_dashboard=1 auto-selects agy-tmux over bg config" "--window $ROOT/wt $CB/kf" "$ROOT/agy-tmux.args"
check "agy inside @agy_dashboard=1 does not invoke claude" "no" "$([ -e "$ROOT/claude.args" ] && echo yes || echo no)"

rm -f "$ROOT/agy-tmux.args" "$ROOT/claude.args"
(cd "$ROOT/widgets" && env -u ANTIGRAVITY_AGENT TMUX="stub,1,0" TMUX_PANE="%1" \
  AGY_TMUX_TMUX_BIN="$TMUX_DASH_STUB" START_TICKET_AGY_TMUX="$AT_STUB" PATH="$ROOT/stubbin:$PATH" \
  "$ST" --tab-only "$ROOT/wt" "$CB/kf" >/dev/null 2>&1)
check "claude inside @agy_dashboard=1 keeps bg launcher" "yes" "$([ -e "$ROOT/claude.args" ] && echo yes || echo no)"
check "claude inside @agy_dashboard=1 does not invoke agy-tmux" "no" "$([ -e "$ROOT/agy-tmux.args" ] && echo yes || echo no)"

rm -f "$ROOT/agy-tmux.args" "$ROOT/claude.args"
(cd "$ROOT/widgets" && ANTIGRAVITY_AGENT=1 TMUX="stub,1,0" TMUX_PANE="%1" \
  AGY_TMUX_TMUX_BIN="$TMUX_PLAIN_STUB" START_TICKET_AGY_TMUX="$AT_STUB" PATH="$ROOT/stubbin:$PATH" \
  "$ST" --tab-only "$ROOT/wt" "$CB/kf" >/dev/null 2>&1)
check "agy in non-dashboard tmux does not auto-select agy-tmux" "no" "$([ -e "$ROOT/agy-tmux.args" ] && echo yes || echo no)"

rm -f "$ROOT/agy-tmux.args" "$HOME/.config/start-ticket/config"
(cd "$ROOT/widgets" && MEM_GUARD_HOST_FIXTURE="level=critical free_pct=3" \
  START_TICKET_AGY_TMUX="$AT_STUB" PATH="$ROOT/stubbin:$PATH" \
  "$ST" --tab-only "$ROOT/wt" "$CB/kf" --launcher agy-tmux >/dev/null 2>"$ROOT/mem.err"); rc=$?
check "mem-guard blocks agy-tmux launcher" "1" "$rc"
check "blocked agy-tmux never invokes agy-tmux.sh" "no" "$([ -e "$ROOT/agy-tmux.args" ] && echo yes || echo no)"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
