#!/usr/bin/env bash
# Poll the current branch's PR for new unresolved review threads.
# Usage: poll-pr.sh [pr_number]
# Exits 0 when unresolved threads are found; exits 1 on timeout.

INTERVAL=45
TIMEOUT=7200  # 2 hours

PR_NUMBER=${1:-$(gh pr view --json number --jq '.number' 2>/dev/null)}

if [ -z "$PR_NUMBER" ]; then
  echo "No PR found for the current branch."
  exit 2
fi

OWNER=$(gh repo view --json owner --jq '.owner.login')
REPO=$(gh repo view --json name --jq '.name')

echo "Polling PR #$PR_NUMBER ($OWNER/$REPO) every ${INTERVAL}s for up to $((TIMEOUT / 60)) minutes..."

end=$((SECONDS + TIMEOUT))
while [ $SECONDS -lt $end ]; do
  sleep $INTERVAL
  unresolved=$(gh api graphql -f query='
    query($owner: String!, $repo: String!, $pr: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100) {
            nodes { isResolved }
          }
        }
      }
    }
  ' -f owner="$OWNER" -f repo="$REPO" -F pr="$PR_NUMBER" \
    --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length' 2>/dev/null)

  echo "$(date '+%H:%M:%S') — unresolved threads: ${unresolved:-error}"

  if [ -n "$unresolved" ] && [ "$unresolved" -gt 0 ]; then
    echo "New unresolved threads detected ($unresolved)."
    exit 0
  fi
done

echo "No new bot activity after $((TIMEOUT / 60)) minutes. Polling stopped."
exit 1
