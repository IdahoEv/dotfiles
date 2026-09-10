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
# Usage: poll-pr.sh [pr_number]
# Exits 0 when new activity is found; 1 on timeout; 2 on setup error.

INTERVAL=45
TIMEOUT=7200  # 2 hours

PR_NUMBER=${1:-$(gh pr view --json number --jq '.number' 2>/dev/null)}
if [ -z "$PR_NUMBER" ]; then
  echo "No PR found for the current branch."
  exit 2
fi

OWNER=$(gh repo view --json owner --jq '.owner.login')
REPO=$(gh repo view --json name --jq '.name')

# One query for everything we care about.
read -r -d '' QUERY <<'GQL'
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      author { login }
      reviews(last: 40) { nodes { author { login } submittedAt } }
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

# Prints: "<latest-non-author-ISO-timestamp-or-empty> <unresolved-thread-count>"
snapshot() {
  gh api graphql -f query="$QUERY" -f owner="$OWNER" -f repo="$REPO" -F pr="$PR_NUMBER" --jq '
    .data.repository.pullRequest as $pr
    | ($pr.author.login) as $me
    | [
        ($pr.reviews.nodes[]        | select(.author.login != $me) | .submittedAt),
        ($pr.comments.nodes[]       | select(.author.login != $me) | .createdAt),
        ($pr.reviewThreads.nodes[].comments.nodes[] | select(.author.login != $me) | .createdAt)
      ]
    | map(select(. != null))
    | ((sort | last) // "") as $latest
    | ([$pr.reviewThreads.nodes[] | select(.isResolved == false)] | length) as $unresolved
    | "\($latest) \($unresolved)"
  ' 2>/dev/null
}

baseline=$(snapshot)
base_ts=${baseline% *}
echo "Polling PR #$PR_NUMBER ($OWNER/$REPO) every ${INTERVAL}s for up to $((TIMEOUT / 60)) min."
echo "Baseline latest non-author activity: ${base_ts:-<none>}"

end=$((SECONDS + TIMEOUT))
while [ $SECONDS -lt $end ]; do
  sleep $INTERVAL
  cur=$(snapshot)
  cur_ts=${cur% *}
  unresolved=${cur##* }

  echo "$(date '+%H:%M:%S') — latest: ${cur_ts:-<none>}  unresolved threads: ${unresolved:-error}"

  if [ -n "$cur_ts" ] && [ "$cur_ts" != "$base_ts" ] && { [ -z "$base_ts" ] || [[ "$cur_ts" > "$base_ts" ]]; }; then
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
