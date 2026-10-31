#!/usr/bin/env bash
# open-pr.test.sh — behavioral checks for open-pr.sh provider resolution,
# the github provider, and ticketless mode.
#
#   open-pr.test.sh
#
# Plain script, exits non-zero on failure (see lib/repo-facts.test.sh). `gh` is
# a stub that records `pr create` args; git talks to a throwaway bare origin,
# and HOME is a temp dir so ~/.config can't leak in.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/open-pr-test.XXXXXX")"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME"
mkdir -p "$ROOT/bin"
export GH_LOG="$ROOT/gh.log"

cat > "$ROOT/bin/gh" <<'STUB'
#!/usr/bin/env bash
case "$1 $2" in
  "auth status") exit 0 ;;
  "pr list")     [ -n "${GH_EXISTING_PR:-}" ] && echo "$GH_EXISTING_PR"; exit 0 ;;
  "pr create")
    shift 2
    while [ $# -gt 0 ]; do
      case "$1" in
        --title) printf '%s' "$2" > "$GH_LOG.title"; shift 2 ;;
        --body)  printf '%s' "$2" > "$GH_LOG.body"; shift 2 ;;
        --body-file) cp "$2" "$GH_LOG.body"; shift 2 ;;
        --draft) : > "$GH_LOG.draft"; shift ;;
        *) shift ;;
      esac
    done
    echo created >> "$GH_LOG" ;;
  "pr view")
    case "$*" in
      *number*) echo 1 ;;
      *url*)    echo https://example.test/pr/1 ;;
      *title*)  cat "$GH_LOG.title" 2>/dev/null || echo "existing title" ;;
    esac ;;
  *) echo "gh $*" >> "$GH_LOG" ;;
esac
STUB
chmod +x "$ROOT/bin/gh"
export PATH="$ROOT/bin:$PATH"

# Fresh repo + origin on <branch>; leaves cwd inside it.
new_repo() {  # <branch> [conf-contents]
  rm -rf "$ROOT/origin.git" "$ROOT/repo" "$GH_LOG"*
  git init -q --bare "$ROOT/origin.git"
  git init -q -b main "$ROOT/repo"
  cd "$ROOT/repo" || exit 1
  git config user.email t@t; git config user.name t
  git remote add origin "$ROOT/origin.git"
  git commit -q --allow-empty -m init
  git push -q origin main
  git checkout -q -b "$1"
  git commit -q --allow-empty -m work
  [ -n "${2:-}" ] && printf '%s\n' "$2" > .start-ticket.conf
  return 0
}

run() { "$TOOLS/open-pr.sh" "$@" 2>&1; }
title() { cat "$GH_LOG.title"; }
body()  { cat "$GH_LOG.body" 2>/dev/null; }

# ---- github provider --------------------------------------------------------
new_repo 42-foo
out="$(run --title "Add foo" --review none)"
check "github: default provider"      "provider=github" "$(grep '^provider=' <<<"$out")"
check "github: plain title"           "Add foo" "$(title)"
check "github: default body"          "Closes #42" "$(body)"

printf 'Summary\n' > "$ROOT/b.md"
new_repo 42-foo
run --title "Add foo" --body-file "$ROOT/b.md" --review none >/dev/null
check "github: footer appended"       "Closes #42" "$(body | tail -1)"
new_repo 42-foo
printf 'Summary\n\nCloses #42\n' > "$ROOT/b.md"
run --title "Add foo" --body-file "$ROOT/b.md" --review none >/dev/null
check "github: footer not duplicated" "1" "$(body | grep -c 'Closes #42')"

new_repo 42-foo
run --title "Add foo" --review copilot >/dev/null
check "github: no review triggers"    "created" "$(cat "$GH_LOG")"
check "github: warns review ignored"  "1" "$(run --title "Add foo" --review copilot | grep -c 'review triggers')"

new_repo 42-foo
out="$(GH_EXISTING_PR=9 run --review none)"
check "existing PR reused, no title"  "pr_action=reused" "$(grep '^pr_action=' <<<"$out")"
check "existing PR: nothing created"  "" "$(cat "$GH_LOG" 2>/dev/null)"

# ---- ticketless -------------------------------------------------------------
new_repo scratch
out="$(run --title "Quick fix" --review none)"; rc=$?
check "ticketless: exits 0"           "0" "$rc"
check "ticketless: title as given"    "Quick fix" "$(title)"
check "ticketless: empty body"        "" "$(body)"
new_repo scratch
printf 'Just a summary\n' > "$ROOT/b.md"
run --title "Quick fix" --body-file "$ROOT/b.md" --review none >/dev/null
check "ticketless: body untouched"    "Just a summary" "$(body)"
new_repo scratch
run --title "Quick fix" --issue 7 --review none >/dev/null
check "--issue on unnumbered branch"  "Closes #7" "$(body)"

# ---- chains (several issues, one PR) ------------------------------------------
chain_file() { printf '%s\n' "$@" > "$(git rev-parse --absolute-git-dir)/chain"; }
new_repo 42-foo
run --title "Add foo" --issue 42,43,44 --review none >/dev/null
check "--issue list: one Closes per issue" "Closes #42 Closes #43 Closes #44" "$(body | tr '\n' ' ' | sed 's/ $//')"
check "--issue list: title uses the head"  "Add foo" "$(title)"
new_repo 42-foo; chain_file 42 43
run --title "Add foo" --review none >/dev/null
check "chain file: Closes for every ticket" "Closes #42 Closes #43" "$(body | tr '\n' ' ' | sed 's/ $//')"
new_repo 42-foo; chain_file 42 43
printf 'Summary\n\nCloses #43\n' > "$ROOT/b.md"
run --title "Add foo" --body-file "$ROOT/b.md" --review none >/dev/null
check "chain: body-file footers appended, none duplicated" "Closes #42 Closes #43" "$(body | grep '^Closes' | sort | tr '\n' ' ' | sed 's/ $//')"
new_repo 42-foo; chain_file 42 43
run --title "Add foo" --issue 42 --review none >/dev/null
check "--issue beats the chain file" "Closes #42" "$(body)"
new_repo 42-foo
run --title "Add foo" --issue 42,x --review none >/dev/null; rc=$?
check "bad id in --issue list is refused" "1" "$rc"
new_repo 42-foo
run --title "Add foo" --draft --review none >/dev/null
check "--draft passed to gh pr create" "yes" "$([ -e "$GH_LOG.draft" ] && echo yes || echo no)"
new_repo 42-foo
run --title "Add foo" --review none >/dev/null
check "no --draft by default" "no" "$([ -e "$GH_LOG.draft" ] && echo yes || echo no)"

# ---- provider resolution ----------------------------------------------------
resolved() {  # <branch> <conf> [args…] → provider= line
  local b="$1" c="$2"; shift 2
  new_repo "$b" "$c"
  run --title "T" --review none "$@" | sed -n 's/^provider=//p'
}
check "conf openpr_provider=kardashev" "kardashev" "$(resolved 42-foo 'openpr_provider=kardashev')"
new_repo 42-foo 'openpr_provider=kardashev'; run --title "T" --review none >/dev/null
check "kardashev: Is<NNN> title"       "Is42: T" "$(title)"
check "kardashev: Closes body"         "Closes #42" "$(body)"
check "start-ticket provider=github"   "github" "$(resolved 42-foo 'provider=github')"
check "start-ticket provider=shortcut" "github" "$(resolved 42-foo 'provider=shortcut')"
check "openpr_provider beats provider" "kardashev" "$(resolved 42-foo $'provider=github\nopenpr_provider=kardashev')"
check "--provider beats conf"          "github" "$(resolved 42-foo 'openpr_provider=kardashev' --provider github)"

# ---- telemetry --------------------------------------------------------------
export WF_TELEMETRY_LOG="$ROOT/events.jsonl"
# Events need an owner/repo origin. The URL is display-only: pushes are routed
# to the local bare repo by repo-local config, so nothing reaches the network.
new_repo() {  # <branch>
  rm -rf "$ROOT/origin.git" "$ROOT/repo" "$GH_LOG"*
  git init -q --bare "$ROOT/origin.git"
  git init -q -b main "$ROOT/repo"
  cd "$ROOT/repo" || exit 1
  git config user.email t@t; git config user.name t
  git remote add origin git@github.com:acme/widgets.git
  git config remote.origin.pushurl "$ROOT/origin.git"
  git commit -q --allow-empty -m init
  git push -q origin main
  git checkout -q -b "$1"
  git commit -q --allow-empty -m work
}
new_repo 42-foo; rm -f "$WF_TELEMETRY_LOG"
run --title "Add foo" --review none >/dev/null
check "pr.open ok event" "pr.open ok 1 created" \
  "$(tail -1 "$WF_TELEMETRY_LOG" | jq -r '"\(.event) \(.outcome) \(.pr_number) \(.pr_action)"')"
check "pr.open has duration" "number" "$(tail -1 "$WF_TELEMETRY_LOG" | jq -r '.duration_ms | type')"
new_repo 42-foo; rm -f "$WF_TELEMETRY_LOG"
run --review none >/dev/null
check "pr.open failure recorded" "fail 1" \
  "$(tail -1 "$WF_TELEMETRY_LOG" | jq -r '"\(.outcome) \(.exit_code)"')"
rm -f "$WF_TELEMETRY_LOG"; run --review bogus >/dev/null
check "usage error not recorded" "absent" "$([ -e "$WF_TELEMETRY_LOG" ] && echo present || echo absent)"
unset WF_TELEMETRY_LOG

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
