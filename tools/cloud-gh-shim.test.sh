#!/usr/bin/env bash
# Checks cloud-gh-shim.py against a fake REST-only gh: the GraphQL-backed
# subcommands the workflow uses must be answered over `gh api`, anything else
# must reach the real gh untouched.
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
shim="$tools_dir/cloud-gh-shim.py"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

cat > "$tmp/gh" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
if [[ "$1" != api ]]; then echo "REAL-GH $*"; exit 0; fi
shift
method=GET; path=""
while (($#)); do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    --paginate|--jq) [[ "$1" == --jq ]] && shift; shift ;;
    -f|-F) shift 2 ;;
    *) path="$1"; shift ;;
  esac
done
case "$method $path" in
  "GET user") echo '{"login":"me"}' ;;
  "GET repos/acme/widgets") echo '{"name":"widgets","owner":{"login":"acme"},"default_branch":"trunk","html_url":"https://github.com/acme/widgets"}' ;;
  "GET repos/acme/widgets/issues/7") echo '{"number":7,"title":"Fix it","body":"b","state":"open","html_url":"u7","assignees":[{"login":"me"}],"sub_issues_summary":{"total":2,"completed":1}}' ;;
  "GET repos/acme/widgets/issues/7/parent") echo '{"number":3,"title":"Epic"}' ;;
  "GET repos/acme/widgets/issues/7/sub_issues?per_page=100") echo '[{"number":8,"title":"S","state":"open"}]' ;;
  "GET repos/acme/widgets/pulls?head=acme%3A7-fix&state=all&per_page=100") echo '[{"number":12,"state":"closed","merged_at":"2026-01-01T00:00:00Z","merge_commit_sha":"abc","html_url":"pu","title":"T","node_id":"PR_x","head":{"ref":"7-fix","sha":"h1"},"base":{"ref":"trunk"}}]' ;;
  "GET repos/acme/widgets/pulls?head=acme%3A7-fix&state=closed&per_page=100") echo '[{"number":12,"state":"closed","merged_at":"2026-01-01T00:00:00Z","merge_commit_sha":"abc","html_url":"pu","title":"T","node_id":"PR_x","head":{"ref":"7-fix","sha":"h1"},"base":{"ref":"trunk"}}]' ;;
  "GET repos/acme/widgets/pulls?head=acme%3A7-fix&state=open&per_page=100") echo '[]' ;;
  "GET repos/acme/widgets/pulls/12") echo '{"number":12,"state":"closed","merged_at":"2026-01-01T00:00:00Z","merge_commit_sha":"abc","html_url":"pu","title":"T","node_id":"PR_x","head":{"ref":"7-fix","sha":"h1"},"base":{"ref":"trunk"}}' ;;
  "GET repos/acme/widgets/pulls/12/commits") echo '[{"sha":"c1","commit":{"committer":{"date":"2026-01-01T00:00:00Z"}}}]' ;;
  "POST repos/acme/widgets/pulls") echo '{"html_url":"https://github.com/acme/widgets/pull/13"}' ;;
  "GET repos/acme/widgets/issues/9/parent") echo "HTTP 404: Not Found" >&2; exit 1 ;;
  "GET repos/acme/widgets/issues/9") echo '{"number":9,"title":"T","body":"","state":"open","html_url":"u9","assignees":[]}' ;;
  "GET repos/acme/widgets/issues/9/sub_issues?per_page=100") echo '[]' ;;
  "GET repos/acme/widgets/issues/10") echo '{"number":10,"title":"T","body":"","state":"open","html_url":"u10","assignees":[]}' ;;
  "GET repos/acme/widgets/issues/10/parent") echo "HTTP 502: Bad Gateway" >&2; exit 1 ;;
  POST*|PATCH*) echo '{}' ;;
  *) echo "unexpected: $method $path" >&2; exit 1 ;;
esac
FAKE
chmod +x "$tmp/gh"

export FAKE_LOG="$tmp/log" GH_SHIM_REAL="$tmp/gh" GH_REPO=acme/widgets
: > "$FAKE_LOG"
g() { python3 -I "$shim" "$@"; }

[[ "$(g repo view --json owner --jq .owner.login)" == acme ]] || fail "repo view owner"
[[ "$(g repo view --json defaultBranchRef -q .defaultBranchRef.name)" == trunk ]] || fail "repo view default branch"
[[ "$(g repo view --json name --jq .name)" == widgets ]] || fail "repo view name"
pass "repo view answers owner, name and default branch over REST"

[[ "$(g issue view 7 --json number,title,body,state,url | jq -r '"\(.number) \(.title) \(.state)"')" == "7 Fix it OPEN" ]] || fail "issue view fields"
[[ "$(g issue view 7 --json parent --jq '.parent.number // empty')" == 3 ]] || fail "issue parent"
[[ "$(g issue view 7 --json assignees --jq '.assignees[].login')" == me ]] || fail "issue assignees"
[[ "$(g issue view 7 --json title,subIssuesSummary,subIssues -q '"\(.subIssuesSummary.completed)/\(.subIssuesSummary.total) \(.subIssues.nodes[] | select(.state=="OPEN") | .number)"')" == "1/2 8" ]] || fail "sub-issue summary"
pass "issue view maps REST fields to gh's JSON shape"

g issue edit 7 --add-assignee @me; g issue comment 7 --body hi; g issue close 7 --comment done
grep -q 'api -X POST repos/acme/widgets/issues/7/assignees' "$FAKE_LOG" || fail "assign"
grep -q 'api -X POST repos/acme/widgets/issues/7/comments' "$FAKE_LOG" || fail "comment"
grep -q 'api -X PATCH repos/acme/widgets/issues/7' "$FAKE_LOG" || fail "close"
pass "issue edit/comment/close write over REST"

[[ "$(g pr list --head 7-fix --state all --json number,state,mergedAt,mergeCommit,headRefOid,baseRefName | jq -r '.[0] | "\(.number) \(.state) \(.mergeCommit.oid) \(.headRefOid) \(.baseRefName)"')" == "12 MERGED abc h1 trunk" ]] || fail "pr list state all"
[[ -z "$(g pr list --head 7-fix --json number --jq '.[0].number // empty')" ]] || fail "open-only pr list should skip the merged PR"
[[ "$(g pr view 12 --json url --jq .url)" == pu ]] || fail "pr view url"
[[ "$(g pr view 12 --json id --jq .id)" == PR_x ]] || fail "pr view node id"
[[ "$(g pr view 12 --json commits --jq '.commits[-1].committedDate')" == 2026-01-01T00:00:00Z ]] || fail "pr view commits"
pass "pr list/view report state, merge commit, head, node id and commits"

( cd "$tmp" && git init -q -b 7-fix . && [[ "$(g pr view --json number --jq .number)" == 12 ]] ) || fail "pr view with no argument uses the current branch"
[[ "$(g pr create --title T --head 7-fix --body b)" == https://github.com/acme/widgets/pull/13 ]] || fail "pr create prints the URL"
g pr create --title T --head 7-fix --draft --body-file <(echo b) >/dev/null
g pr edit 12 --title New
grep -q 'api -X PATCH repos/acme/widgets/pulls/12' "$FAKE_LOG" || fail "pr edit"
pass "pr create/edit and no-argument pr view work over REST"

[[ "$(g issue view 9 --json parent --jq '.parent')" == null ]] || fail "a 404 parent means no parent"
if g issue view 10 --json parent >/dev/null 2>&1; then fail "a non-404 error must not read as 'no parent'"; fi
if g issue view 7 --json bogusfield >/dev/null 2>&1; then fail "unknown --json fields must fail"; fi
if g issue view '1/../x' >/dev/null 2>&1; then fail "non-numeric ids must be refused"; fi
if g issue view 1 -R 'a/b/../c' >/dev/null 2>&1; then fail "odd repo slugs must be refused"; fi
g pr comment 12 --body hello; grep -q 'api -X POST repos/acme/widgets/issues/12/comments' "$FAKE_LOG" || fail "pr comment"
[[ "$(g pr list --head 7-fix --state all --json number --jq length)" == 1 ]] || fail "fixture sanity: merged PR is listed under all"
[[ -z "$(g pr list --head 7-fix --state closed --json number --jq '.[0].number // empty')" ]] || fail "--state closed must exclude merged PRs"
pass "404 means absent, other errors are fatal; unknown fields, odd ids and slugs fail; pr comment and closed-state work"

g auth status | grep -q 'Logged in as me' || fail "auth status"
[[ "$(g workflow view x)" == "REAL-GH workflow view x" ]] || fail "unknown commands pass through"
[[ "$(g api repos/acme/widgets)" == *'"widgets"'* ]] || fail "gh api passes through"
if g issue view 7 --bogus 2>/dev/null; then fail "unsupported options must be refused, not guessed"; fi
pass "auth status is REST-backed; everything else passes through; unsupported flags fail loudly"
