# shortcut provider for open-pr.sh   — requires: gh (authed)
#
# Encapsulates Shortcut story PR conventions (mirrors start-ticket-providers/shortcut.sh):
#   - branch convention `sc-<id>-slug` or `<user>/sc-<id>/<slug>` → story id
#   - PR title `sc-<id>: <title>` (ticketless PRs keep the title as given)
#   - PR body footer `Story: [sc-<id>]` (never `Closes #N`, which would close a GitHub issue)
#   - no review triggers: --review is accepted and ignored.

PROVIDER_TRIGGER_MODE="manual"

provider::available() {
  command -v gh >/dev/null && gh auth status >/dev/null 2>&1
}

provider::validate_issue() {  # <id> → 0 if valid Shortcut story id
  [[ "$1" =~ ^(sc-)?[1-9][0-9]*$ ]]
}

provider::issue_from_branch() {  # <branch> → echoes story id(s), or nothing
  local branch="$1"
  if [[ "$branch" =~ (^|/)sc-([1-9][0-9]*)(\+[0-9]+)*(-.+|/.*|$) ]]; then
    printf '%s\n' "${BASH_REMATCH[2]}"
  fi
  return 0
}

provider::pr_title() {  # <issue> <title> → "sc-<id>: <title>" (idempotent)
  local issue="${1#sc-}" t="$2"
  if [ -z "$issue" ] || [[ "$t" =~ ^sc-${issue}:[[:space:]] ]]; then
    printf '%s\n' "$t"
  else
    printf 'sc-%s: %s\n' "$issue" "$t"
  fi
}

provider::pr_body() {  # <issue> → "Story: [sc-<id>]"
  local issue="${1#sc-}"
  printf 'Story: [sc-%s]\n' "$issue"
}

provider::pr_body_footer() {  # <issue> → "Story: [sc-<id>]"
  local issue="${1#sc-}"
  printf 'Story: [sc-%s]\n' "$issue"
}

provider::trigger_reviews() {  # <pr_number> <level>
  echo "open-pr: shortcut provider has no review triggers; --review $2 ignored" >&2
}
