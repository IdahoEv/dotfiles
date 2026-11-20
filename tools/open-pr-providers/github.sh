# github provider for open-pr.sh   — requires: gh (authed)
#
# The generic default for any GitHub repo (mirrors start-ticket-providers/github.sh):
#   - branch convention `<NNN>-slug`  → issue number NNN
#   - PR title `Is<NNN>: <title>` (ticketless PRs keep the title as given)
#   - PR body footer `Closes #NNN`
#   - review: request-review.sh requests Copilot (and claude.yml for
#     copilot+claude) on PR open; skipped for --review none and, by default,
#     on machines with ~/.config/local-review-only (review bots run there).

PROVIDER_TRIGGER_MODE="manual"

provider::available() {
  command -v gh >/dev/null && gh auth status >/dev/null 2>&1
}

provider::validate_issue() {  # <id> → 0 if valid GitHub issue number
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

provider::issue_from_branch() {  # <branch> → echoes issue number, or nothing
  local branch="$1"
  if [[ "$branch" =~ (^|/)Is([1-9][0-9]*)(\+[0-9]+)*(-.+|/.*|$) ]]; then
    printf '%s\n' "${BASH_REMATCH[2]}"
  elif [[ "$branch" =~ ^([1-9][0-9]*)-.+$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  fi
  return 0
}

provider::pr_title() {  # <issue> <title> → "Is<NNN>: <title>" (idempotent)
  local issue="$1" t="$2"
  if [ -z "$issue" ] || [[ "$t" =~ ^Is${issue}:[[:space:]] ]]; then
    printf '%s\n' "$t"
  else
    printf 'Is%s: %s\n' "$issue" "$t"
  fi
}

provider::pr_body() {  # <issue> → "Closes #NNN" (default body, no --body-file)
  printf 'Closes #%s\n' "$1"
}

provider::pr_body_footer() {  # <issue> → "Closes #NNN", appended to a drafted body
  printf 'Closes #%s\n' "$1"
}

provider::trigger_reviews() {  # <pr_number> <level> → 0 if requested
  # open-pr.sh only calls this when review != none, which already covers the
  # work-machine marker (~/.config/local-review-only → default --review none).
  "${OPEN_PR_REQUEST_REVIEW:-$SCRIPT_DIR/request-review.sh}" --pr "$1" --level "$2" >/dev/null \
    || { echo "open-pr: review request failed for #$1 (--review $2); request it manually" >&2; return 1; }
}
