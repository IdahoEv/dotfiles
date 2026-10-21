# github provider for open-pr.sh   — requires: gh (authed)
#
# The generic default for any GitHub repo (mirrors start-ticket-providers/github.sh):
#   - branch convention `<NNN>-slug`  → issue number NNN
#   - PR title is used as given (no ticket prefix)
#   - PR body footer `Closes #NNN`
#   - no review triggers: --review is accepted and ignored. Repos that want
#     Copilot/claude.yml wiring use the kardashev provider or their own.

PROVIDER_TRIGGER_MODE="manual"

provider::available() {
  command -v gh >/dev/null && gh auth status >/dev/null 2>&1
}

provider::issue_from_branch() {  # <branch> → echoes issue number, or nothing
  local branch="$1"
  if [[ "$branch" =~ ^([1-9][0-9]*)-.+$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  fi
  return 0
}

provider::pr_title() {  # <issue> <title> → title unchanged
  printf '%s\n' "$2"
}

provider::pr_body() {  # <issue> → "Closes #NNN" (default body, no --body-file)
  printf 'Closes #%s\n' "$1"
}

provider::pr_body_footer() {  # <issue> → "Closes #NNN", appended to a drafted body
  printf 'Closes #%s\n' "$1"
}

provider::trigger_reviews() {  # <pr_number> <level>
  :
}
