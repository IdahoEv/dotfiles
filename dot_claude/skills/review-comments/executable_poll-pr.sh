#!/usr/bin/env bash
# Poll the current branch's PR for new review activity from anyone other than the
# PR author — a submitted review, an inline review comment, or an issue comment.
#
# The old version only watched for *unresolved inline review threads*, which
# silently missed:
#   - reviews whose findings live in the review body (Copilot "Suppressed
#     comments", CodeRabbit "Outside diff range comments")
#   - top-level summary-only reviews
#   - plain PR issue comments
# It now snapshots the latest non-author activity timestamp at startup and fires
# when anything newer appears (and still fires immediately on an unresolved thread).
#
# It also detects AI-reviewer SIGN-OFF: the latest non-author activity is a review
# whose body carries a known all-clear marker (Copilot "Merge recommended" /
# "No issues found", CodeRabbit "Merge approved" / "Verified successful", an
# APPROVED state from any reviewer) AND there are no unresolved threads. That
# exits 3 so the caller can announce "ready to merge" instead of treating every
# exit-0 event as complaints. Findings-in-body reviews (Suppressed/Outside-diff)
# don't match the markers, so they still exit 0.
#
# Sign-off markers can be extended per repo/session via POLL_SIGNOFF_PATTERNS
# (an extended-regex, alternation already included; it is ORed with the defaults),
# e.g. for a future @claude reviewer:
#   POLL_SIGNOFF_PATTERNS='@claude.*approved' poll-pr.sh
#
# Usage: poll-pr.sh [pr_number]
# Exits 0 when new activity (possible complaints) is found; 1 on timeout;
# 2 on setup error; 3 when AI reviewers have signed off (all-clear, no
# unresolved threads).

INTERVAL=45
TIMEOUT=7200  # 2 hours

PR_NUMBER=${1:-$(gh pr view --json number --jq '.number' 2>/dev/null)}
if [ -z "$PR_NUMBER" ]; then
  echo "No PR found for the current branch."
  exit 2
fi

OWNER=$(gh repo view --json owner --jq '.owner.login')
REPO=$(gh repo view --json name --jq '.name')

# Known all-clear markers across AI reviewers. Bodies are matched case-blind.
DEFAULT_SIGNOFF='merge recommended|no issues found|merge approved|verified successful|ready to merge|lgtm'
SIGNOFF_RE="${DEFAULT_SIGNOFF}|${POLL_SIGNOFF_PATTERNS:-}"

# One query for everything we care about.
read -r -d '' QUERY <<'GQL'
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      author { login }
      reviews(last: 40) { nodes { author { login } submittedAt state body } }
      comments(last: 40) { nodes { author { login } createdAt } }
      reviewThreads(first: 100) {
        nodes {
          isResolved
          comments(first: 1) { nodes { author { login } createdAt } }
        }
      }
    }
  }
}
GQL

# Prints: "<latest-non-author-ISO-timestamp-or-empty> <unresolved-thread-count> <signoff-flag>"
# signoff-flag is 1 only when the single latest non-author item is a review that
# is APPROVED-state or whose body matches a sign-off marker.
snapshot() {
  gh api graphql -f query="$QUERY" -f owner="$OWNER" -f repo="$REPO" -F pr="$PR_NUMBER" --jq '
    .data.repository.pullRequest as $pr
    | ($pr.author.login) as $me
    | [
        ($pr.reviews.nodes[]  | select(.author.login != $me) | {ts: .submittedAt, kind: "review", state: .state, body: (.body // "")}),
        ($pr.comments.nodes[] | select(.author.login != $me) | {ts: .createdAt, kind: "comment"}),
        ($pr.reviewThreads.nodes[].comments.nodes[] | select(.author.login != $me) | {ts: .createdAt, kind: "thread"})
      ]
    | map(select(.ts != null))
    | (sort_by(.ts) | last // {ts: "", kind: "none"}) as $latest
    | ([$pr.reviewThreads.nodes[] | select(.isResolved == false)] | length) as $unresolved
    | (if $latest.kind == "review" and ($latest.state == "APPROVED") then 1
       elif $latest.kind == "review"
         and ($latest.body | test("'"$SIGNOFF_RE"'"; "i"))
       then 1 else 0 end) as $signoff
    | "\($latest.ts) \($unresolved) \($signoff)"
  ' 2>/dev/null
}

baseline=$(snapshot)
base_ts=$(echo "$baseline" | awk '{print $1}')
echo "Polling PR #$PR_NUMBER ($OWNER/$REPO) every ${INTERVAL}s for up to $((TIMEOUT / 60)) min."
echo "Baseline latest non-author activity: ${base_ts:-<none>}"

newer_than_baseline() {
  # $1 = candidate timestamp
  [ -n "$1" ] && [ "$1" != "$base_ts" ] && { [ -z "$base_ts" ] || [[ "$1" > "$base_ts" ]]; }
}

end=$((SECONDS + TIMEOUT))
while [ $SECONDS -lt $end ]; do
  sleep $INTERVAL
  cur=$(snapshot)
  cur_ts=$(echo "$cur" | awk '{print $1}')
  unresolved=$(echo "$cur" | awk '{print $2}')
  signoff=$(echo "$cur" | awk '{print $3}')

  echo "$(date '+%H:%M:%S') — latest: ${cur_ts:-<none>}  unresolved threads: ${unresolved:-error}  signoff: ${signoff:-?}"

  # Sign-off: fresh all-clear review and nothing left unresolved.
  if [ "$signoff" = "1" ] && newer_than_baseline "$cur_ts" \
     && [ -n "$unresolved" ] && [ "$unresolved" -eq 0 ] 2>/dev/null; then
    echo "AI reviewers signed off ($cur_ts), no unresolved threads — ready to merge."
    exit 3
  fi

  if newer_than_baseline "$cur_ts"; then
    echo "New review activity detected: $cur_ts"
    exit 0
  fi

  if [ -n "$unresolved" ] && [ "$unresolved" -gt 0 ] 2>/dev/null; then
    echo "Unresolved review threads present ($unresolved)."
    exit 0
  fi
done

echo "No new review activity after $((TIMEOUT / 60)) minutes. Polling stopped."
exit 1
