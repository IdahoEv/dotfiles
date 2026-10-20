#!/usr/bin/env bash
# review-state.sh [--pr N] [--local N[*]] — print the review-rounds status line:
#   Code Review Rounds: 2 local*, 1 Copilot, 0 Coderabbit
#
# Rounds = reviews each bot has submitted on the PR. The local count is the
# caller's (it lives in the session, not in GitHub), passed as --local; keep
# its trailing * if a local round is running. A * follows a type's name when a round is
# in flight: Copilot while it is a requested reviewer; CodeRabbit (reviews
# every push on its own) while the head commit is newer than its last review.
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

copilot=0 rabbit=0 star_c="" star_r=""
if [ -n "$pr" ]; then
  rows="$(gh api "repos/{owner}/{repo}/pulls/$pr/reviews" --paginate \
    --jq '.[] | [.user.login, .submitted_at] | @tsv')"
  head_at="$(gh pr view "$pr" --json commits --jq '.commits[-1].committedDate')"
  requested="$(gh pr view "$pr" --json reviewRequests \
    --jq '[.reviewRequests[] | .login // .name // ""] | join(" ")')"

  count() { printf '%s\n' "$rows" | awk -F'\t' -v re="$1" '$1 ~ re {n++} END {print n+0}'; }
  last()  { printf '%s\n' "$rows" | awk -F'\t' -v re="$1" '$1 ~ re && $2 > m {m = $2} END {print m}'; }

  copilot="$(count '^[Cc]opilot')"
  rabbit="$(count '^coderabbitai')"
  case "$requested" in *[Cc]opilot*) star_c="*" ;; esac
  if [ "$rabbit" -gt 0 ] && [[ "$head_at" > "$(last '^coderabbitai')" ]]; then star_r="*"; fi
fi

star_l=""
case "$local_n" in *'*') star_l="*"; local_n="${local_n%'*'}" ;; esac

parts="$local_n local$star_l"
[ "$copilot" -gt 0 ] || [ -n "$star_c" ] && parts="$parts, $copilot Copilot$star_c"
[ "$rabbit" -gt 0 ] || [ -n "$star_r" ] && parts="$parts, $rabbit Coderabbit$star_r"
printf 'Code Review Rounds: %s\n' "$parts"
