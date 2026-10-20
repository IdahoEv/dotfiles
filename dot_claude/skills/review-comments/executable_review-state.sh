#!/usr/bin/env bash
# review-state.sh [--pr N] [--local N[*]] — print the review-rounds status line:
#   Code Review Rounds: 2 local*, 1 Copilot, 0 Coderabbit
#
# Rounds = reviews each bot has submitted on the PR, not counting "job was not
# started" billing notices (keep UNAVAILABLE_RE in step with poll-pr.sh). The
# local count is the caller's (it lives in the session, not in GitHub), passed
# as --local; keep its trailing * if a local round is running. A * follows a
# type's name when a round is in flight: Copilot while its latest review request
# is newer than its latest review or notice (requests to bots are not in
# reviewRequests, only in the timeline); CodeRabbit (reviews every push on its
# own) while the head commit is newer than its last review.
# A bot is omitted until it has a completed or running round (0 without a * is hidden).
set -euo pipefail

pr="" local_n="0"
while [ $# -gt 0 ]; do
  case "$1" in
    --pr)    pr="${2:?--pr needs a value}"; shift 2 ;;
    --local) local_n="${2:?--local needs a value}"; shift 2 ;;
    *) echo "usage: review-state.sh [--pr N] [--local N[*]]" >&2; exit 1 ;;
  esac
done
[ -n "$pr" ] || pr="$(gh pr view --json number --jq .number 2>/dev/null || true)"

UNAVAILABLE_RE='job was not started because|spending limit needs to be increased'

copilot=0 rabbit=0 star_c="" star_r=""
if [ -n "$pr" ]; then
  # Real reviews only; notices are kept separately so they can end a running round.
  rows="$(gh api "repos/{owner}/{repo}/pulls/$pr/reviews" --paginate \
    --jq ".[] | select((.body // \"\") | test(\"$UNAVAILABLE_RE\"; \"i\") | not) | [.user.login, .submitted_at] | @tsv")"
  notices="$(gh api "repos/{owner}/{repo}/pulls/$pr/reviews" --paginate \
    --jq ".[] | select((.body // \"\") | test(\"$UNAVAILABLE_RE\"; \"i\")) | [.user.login, .submitted_at] | @tsv")"
  head_at="$(gh pr view "$pr" --json commits --jq '.commits[-1].committedDate')"
  requested_at="$(gh api graphql -f query='
    query($o: String!, $r: String!, $n: Int!) {
      repository(owner: $o, name: $r) { pullRequest(number: $n) {
        timelineItems(last: 30, itemTypes: [REVIEW_REQUESTED_EVENT, REVIEW_REQUEST_REMOVED_EVENT]) {
          nodes { __typename
            ... on ReviewRequestedEvent { createdAt requestedReviewer { ... on Bot { login } } }
            ... on ReviewRequestRemovedEvent { createdAt requestedReviewer { ... on Bot { login } } } } } } } }' \
    -f o="$(gh repo view --json owner --jq .owner.login)" -f r="$(gh repo view --json name --jq .name)" -F n="$pr" \
    --jq '[.data.repository.pullRequest.timelineItems.nodes[]
           | select(.requestedReviewer.login // "" | test("^[Cc]opilot"))]
          | last | if . == null or .__typename != "ReviewRequestedEvent" then "" else .createdAt end')"

  count() { printf '%s\n' "$rows" | awk -F'\t' -v re="$1" '$1 ~ re {n++} END {print n+0}'; }
  last()  { printf '%s\n' "$rows" | awk -F'\t' -v re="$1" '$1 ~ re && $2 > m {m = $2} END {print m}'; }

  copilot="$(count '^[Cc]opilot')"
  rabbit="$(count '^coderabbitai')"
  # A notice also answers a request, so it counts as the latest outcome.
  answered="$(printf '%s\n%s\n' "$rows" "$notices" | awk -F'\t' '$1 ~ /^[Cc]opilot/ && $2 > m {m = $2} END {print m}')"
  if [ -n "$requested_at" ] && [[ "$requested_at" > "$answered" ]]; then star_c="*"; fi
  if [ "$rabbit" -gt 0 ] && [[ "$head_at" > "$(last '^coderabbitai')" ]]; then star_r="*"; fi
fi

star_l=""
case "$local_n" in *'*') star_l="*"; local_n="${local_n%'*'}" ;; esac

parts="$local_n local$star_l"
[ "$copilot" -gt 0 ] || [ -n "$star_c" ] && parts="$parts, $copilot Copilot$star_c"
[ "$rabbit" -gt 0 ] || [ -n "$star_r" ] && parts="$parts, $rabbit Coderabbit$star_r"
printf 'Code Review Rounds: %s\n' "$parts"
