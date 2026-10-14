#!/usr/bin/env bash
# wf-context.sh — deterministic facts for the /workflow skill.
#
# The skill's job is judgment: deciding whether a proposed improvement is
# project-local or global, and designing the change. Everything *mechanical* it
# would otherwise re-derive with a dozen tool calls lives here instead, so the
# model spends its tokens on the decision rather than on probing the filesystem.
#
# Same rationale as lib/repo-facts.sh in git-tools: state a convention once, in
# shell, instead of restating it in prose and having the model re-run the probes.
#
# Read-only, no writes, no side effects. Safe to run anywhere.
#
# Makes no network calls of its own — every git query is local-only, which is
# why the default-branch lookup avoids gt::default_branch (see below). The one
# caveat is chezmoi: if the dotfiles source dir ever declares an `archive`-type
# external with an expired refreshPeriod, `chezmoi source-path` will fetch it.
# The current config declares only a `git-repo` external, which is not fetched
# on these read paths.
#
# Usage:
#   wf-context.sh                      # key=value facts about the current repo
#   wf-context.sh srcpath <target>     # chezmoi source path for a target file
#   wf-context.sh --help
#
# `srcpath` exit codes: 0 managed (path on stdout) · 1 healthy chezmoi, file
# genuinely unmanaged (the "new file" case) · 2 chezmoi not installed · 3
# chezmoi can't read its source state — NOT a license to edit the target
# directly.
#
# The subcommand is `srcpath`, deliberately NOT `source`: a bare `source` in an
# argument list trips command-sandbox guards that scan for shell sourcing, which
# would block this script in exactly the isolated sessions that need it.
#
# Output is `key=value`, one per line, shell-safe and stable. Unknown values are
# empty rather than absent, so a consumer can parse without checking for keys.

set -uo pipefail

GIT_TOOLS_DEFAULT="$HOME/Documents/Development/git-tools/main"

# Memo state for wf::chezmoi_healthy. Cleared here so an exported value in the
# caller's environment can't preempt the probe — a sentinel that answers from
# $ENV is worse than no sentinel.
unset _wf_chezmoi_probed _wf_chezmoi_healthy

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; }

# ---- chezmoi ----------------------------------------------------------------
# Resolve the chezmoi SOURCE file for a target path. This is the whole point of
# the "edit the template, not the target" rule: editing ~/.claude/CLAUDE.md
# directly is silently reverted by the next `chezmoi apply` and conflicts when
# dotfiles sync to another machine.
#
# Prints the source path, or nothing + a non-zero rc.
# A .tmpl source matters to the caller: it means the file has conditional
# branches (e.g. {{ if .is_work }}) that an edit may need to respect.
#
#   rc 0  managed; source path on stdout
#   rc 1  chezmoi is healthy and this file genuinely isn't managed — the
#         normal "new file" case
#   rc 2  chezmoi not installed
#   rc 3  chezmoi installed but NOT HEALTHY — it cannot read its source state
#         at all: the source dir is missing/unreadable, or the source-state
#         scaffolding won't load (`.chezmoiignore`, `.chezmoidata.*`,
#         `.chezmoiexternal.*`, a `.chezmoiversion` newer than the binary).
#         Still narrow: a broken *content* template (a syntax error in
#         CLAUDE.md.tmpl) does NOT trip this, because it doesn't stop chezmoi
#         resolving source paths. rc 1 is therefore not evidence that
#         `chezmoi apply` will succeed.
#
# rc 1 also covers a path matched by .chezmoiignore, which is NOT separable
# here: `chezmoi ignored` lists only entries already in the source state, so
# it can't see a would-be new file. The tell is at add time — `chezmoi add` on
# an ignored path prints "warning: ignoring <path>" and exits 0 WITHOUT
# adding. Read its output; see SKILL.md §3.
#
# rc 3 exists because `chezmoi source-path <target>` cannot be trusted to mean
# "not managed": it prints the same "not managed" on stderr and exits 1 for a
# genuinely-unmanaged file AND for a chezmoi that can't read its source state.
# Collapsing those routes the caller to the "new file" branch, where the rule is
# "it's not managed, so edit the target directly" — and editing ~/.claude/*
# directly is the exact thing this skill exists to prevent. It would also be
# silently undone by the next `chezmoi apply` once chezmoi is working again.
#
# See wf::chezmoi_healthy for the discriminator and why it takes two tests.
wf::source_path() {  # <target> → <source path>
  local target="$1" src
  command -v chezmoi >/dev/null || return 2
  # `--` so a target beginning with a dash can't be read as a chezmoi flag:
  # `source-path --source=/tmp` otherwise prints /tmp and exits 0, i.e. the
  # strongest claim this function makes, for something that isn't a file.
  if src="$(chezmoi source-path -- "$target" 2>/dev/null)"; then
    [ -n "$src" ] && printf '%s' "$src"
    return 0
  fi
  wf::chezmoi_healthy || return 3
  return 1
}

# True when chezmoi can actually read its source state. Memoized: the probe
# costs a process spawn and several callers ask.
#
# `_wf_chezmoi_probed` is a separate flag rather than testing the value for
# emptiness, and both are unset at startup (see below), so a variable inherited
# from the caller's environment cannot decide this. The whole point of the
# function is to be the thing that can't be fooled.
#
# Two tests, because neither alone is sufficient:
#
#   -d on the source root     catches a missing/bogus source dir — for which
#                             `chezmoi managed` still exits 0, listing nothing.
#   `chezmoi managed`'s EXIT  catches a source dir that exists but whose source
#   STATUS (not its output)   *state* won't load: a broken `.chezmoiignore`,
#                             `.chezmoidata.yaml`, `.chezmoiexternal.toml`, or
#                             a `.chezmoiversion` newer than the binary. Each
#                             aborts `source-path <target>` for EVERY file
#                             while the root still exists.
#
# Reading `managed`'s status rather than its output is what makes this safe for
# a freshly-`chezmoi init`ed source dir: empty but healthy, it lists nothing and
# exits 0, so it is correctly healthy and rc 1 ("new file") is the right answer.
wf::chezmoi_healthy() {
  if [ "${_wf_chezmoi_probed:-}" != yes ]; then
    local root
    root="$(chezmoi source-path 2>/dev/null)"
    if [ -n "$root" ] && [ -d "$root" ] \
       && chezmoi managed >/dev/null 2>&1; then
      _wf_chezmoi_healthy=yes
    else
      _wf_chezmoi_healthy=no
    fi
    _wf_chezmoi_probed=yes
  fi
  [ "$_wf_chezmoi_healthy" = yes ]
}

wf::chezmoi_facts() {
  local root managed="no" claude_md_src="" tmpl="no" dirty=""

  if ! command -v chezmoi >/dev/null; then
    printf 'chezmoi_available=no\nchezmoi_manages_claude=unknown\n'
    return
  fi
  printf 'chezmoi_available=yes\n'

  # Installed is not the same as working. Everything below reads source state;
  # if chezmoi can't see its source dir, every answer is a false negative, so
  # say so once up front rather than emitting a page of misleading "no"s.
  if wf::chezmoi_healthy; then
    printf 'chezmoi_healthy=yes\n'
  else
    printf 'chezmoi_healthy=no\n'
  fi

  root="$(chezmoi source-path 2>/dev/null)"
  printf 'chezmoi_source_root=%s\n' "$root"

  # Is ~/.claude under chezmoi's control at all?
  if chezmoi managed 2>/dev/null | grep -qxF '.claude'; then managed="yes"; fi
  printf 'chezmoi_manages_claude=%s\n' "$managed"

  claude_md_src="$(wf::source_path "$HOME/.claude/CLAUDE.md" || true)"
  printf 'chezmoi_claude_md_source=%s\n' "$claude_md_src"
  case "$claude_md_src" in *.tmpl) tmpl="yes" ;; esac
  printf 'chezmoi_claude_md_is_template=%s\n' "$tmpl"

  # settings.json may be a `modify_` source: a SCRIPT that rewrites the target,
  # not the target's contents. Editing it as if it were JSON corrupts it. Report
  # the kind so the prompt doesn't have to carry the rule.
  local settings_src settings_kind="plain"
  settings_src="$(wf::source_path "$HOME/.claude/settings.json" || true)"
  printf 'chezmoi_settings_source=%s\n' "$settings_src"
  case "$(basename "${settings_src:-}")" in
    modify_*) settings_kind="modify" ;;
    "")       settings_kind="unmanaged" ;;
  esac
  printf 'chezmoi_settings_source_kind=%s\n' "$settings_kind"

  # Uncommitted changes already sitting in the dotfiles repo. If this is "yes",
  # anything we add lands on top of someone else's in-flight work — say so
  # before editing rather than after.
  # rev-parse, not `[ -d "$root/.git" ]`: in a linked worktree .git is a FILE
  # (as this script notes for the project case), and the -d test would report
  # an empty count — which SKILL.md reads as "no dotfiles work in flight".
  if [ -n "$root" ] && git -C "$root" rev-parse --git-dir >/dev/null 2>&1; then
    dirty="$(git -C "$root" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  fi
  printf 'chezmoi_source_dirty_files=%s\n' "${dirty:-}"
}

# ---- project ----------------------------------------------------------------
wf::project_facts() {
  local top branch default ahead behind dirty cfg

  top="$(git rev-parse --show-toplevel 2>/dev/null)"
  if [ -z "$top" ]; then
    printf 'in_git_repo=no\n'
    return
  fi
  printf 'in_git_repo=yes\n'
  printf 'repo_root=%s\n' "$top"
  printf 'repo_name=%s\n' "$(basename "$top")"

  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
  printf 'branch=%s\n' "$branch"

  # A linked worktree has .git as a FILE, not a directory.
  if [ -f "$top/.git" ]; then
    printf 'is_linked_worktree=yes\n'
  else
    printf 'is_linked_worktree=no\n'
  fi

  # Never assume main/master — these repos use `development`.
  #
  # Deliberately NOT gt::default_branch: it falls through to
  # `git remote show origin` and `gh repo view` when refs/remotes/origin/HEAD is
  # unset — untimed network calls that would make this script hang for 30s to
  # two minutes offline, breaking the "No network" guarantee in the header.
  #
  # refs/remotes/origin/HEAD is the only LOCAL source that actually knows which
  # branch origin considers default, so ask it directly and report whether it
  # answered. gt::default_branch_ref's probe loop is the fallback, but it tries
  # development → main → master in fixed order with no reference to the remote:
  # in a repo carrying both `development` and `master` where the true default is
  # `master` (wellth-api-v3's shape), it confidently returns `development`. That
  # is a guess, and commits_behind/ahead_default would be measured against the
  # wrong base, so label it as one rather than passing it off as fact.
  # Source unconditionally — the ticket parse below needs gt::ticket_from_branch
  # whether or not the default-branch fallback is reached.
  if [ -r "$GIT_TOOLS_DEFAULT/lib/repo-facts.sh" ]; then
    # shellcheck source=/dev/null
    . "$GIT_TOOLS_DEFAULT/lib/repo-facts.sh"
  fi

  local default_source="origin_head"
  # Full ref, not --short: `--short` abbreviates only as far as stays
  # unambiguous, so one stray local `origin/master` branch or tag makes it
  # return `remotes/origin/master`, which `${default#origin/}` doesn't strip.
  # The answer was authoritative and would silently decay into a probe guess.
  default="$(git -C "$top" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null)"
  default="${default#refs/remotes/origin/}"
  # A symref can outlive its target (upstream branch renamed/deleted). Verify
  # against the full ref path — bare `origin/<x>` also resolves a TAG named
  # `origin/<x>`, which would confirm a default branch that doesn't exist.
  if [ -n "$default" ] \
     && ! git -C "$top" rev-parse --verify -q \
          "refs/remotes/origin/$default" >/dev/null; then
    default=""
  fi
  if [ -z "$default" ] && declare -f gt::default_branch_ref >/dev/null 2>&1; then
    default="$(gt::default_branch_ref "$top" 2>/dev/null || true)"
    default="${default#origin/}"
    [ -n "$default" ] && default_source="probe"
  fi
  [ -n "${default:-}" ] || default_source="none"
  printf 'default_branch=%s\ndefault_branch_source=%s\n' \
    "${default:-}" "$default_source"

  # Full ref path again: a tag named `origin/<default>` would otherwise satisfy
  # this and the counts below would be measured against the tag.
  if [ -n "${default:-}" ] \
     && git -C "$top" rev-parse --verify -q \
          "refs/remotes/origin/$default" >/dev/null; then
    read -r behind ahead <<<"$(git -C "$top" rev-list --left-right --count \
      "refs/remotes/origin/${default}...HEAD" 2>/dev/null)"
    # Omit rather than emit empty when rev-list fails (unborn/orphan HEAD).
    # An empty value reads as zero; an absent key reads as unknown.
    if [ -n "${behind:-}" ] && [ -n "${ahead:-}" ]; then
      printf 'commits_behind_default=%s\ncommits_ahead_default=%s\n' "$behind" "$ahead"
    fi
  fi

  dirty="$(git -C "$top" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  printf 'working_tree_dirty_files=%s\n' "$dirty"

  # Project-level Claude config. A symlinked .claude/ is the trap: edits made
  # "in the worktree" actually land in the main checkout and escape the branch.
  if [ -L "$top/.claude" ]; then
    printf 'project_claude_dir=symlink\nproject_claude_symlink_target=%s\n' \
      "$(readlink "$top/.claude")"
  elif [ -d "$top/.claude" ]; then
    printf 'project_claude_dir=dir\n'
  else
    printf 'project_claude_dir=none\n'
  fi
  [ -f "$top/CLAUDE.md" ] && printf 'project_claude_md=yes\n' || printf 'project_claude_md=no\n'

  # worktree-manager.sh symlinks the WHOLE .claude/ only when it is untracked.
  # When .claude/ is committed it symlinks just settings.local.json — the quiet
  # version of the same trap, invisible to the check above.
  if [ -L "$top/.claude/settings.local.json" ]; then
    printf 'project_claude_settings_local=symlink\n'
  elif [ -f "$top/.claude/settings.local.json" ]; then
    printf 'project_claude_settings_local=file\n'
  else
    printf 'project_claude_settings_local=none\n'
  fi

  # Standing ticket, by precedence: marker file → ticket id in the branch name.
  # The branch fallback is deterministic parsing, so it belongs here rather than
  # in the prompt — asking about a ticket that names itself in the branch is the
  # kind of question that makes a skill annoying enough to stop using.
  cfg="$top/.claude/workflow-config.json"
  if [ -r "$cfg" ]; then
    printf 'workflow_config=%s\n' "$cfg"
    printf 'standing_ticket=%s\n' "$(wf::json_str "$cfg" standing_ticket)"
    printf 'standing_ticket_source=marker\n'
    printf 'ticket_provider=%s\n' "$(wf::json_str "$cfg" provider)"
    printf 'workflow_branch_prefix=%s\n' "$(wf::json_str "$cfg" branch_prefix)"
  else
    local from_branch="" scheme=""
    if declare -f gt::ticket_from_branch >/dev/null 2>&1; then
      from_branch="$(gt::ticket_from_branch "$branch")"
      scheme="$(gt::ticket_scheme "$branch")"
    fi
    printf 'workflow_config=\nworkflow_branch_prefix=\n'
    printf 'standing_ticket=%s\n' "$from_branch"
    printf 'standing_ticket_source=%s\n' "$([ -n "$from_branch" ] && echo branch || echo none)"
    printf 'ticket_provider=%s\n' "$([ "$scheme" = unknown ] && echo "" || echo "$scheme")"
  fi
}

# Pull one string field out of a flat JSON object. jq when available; a sed
# fallback keeps the script useful on a box without it.
# STRING values only, and newlines stripped: the result is printed straight
# into the key=value stream, so a value containing a newline would inject
# fabricated fact lines (`standing_ticket=sc-1\nchezmoi_healthy=yes`), and an
# object value would spill pretty-printed JSON across several.
wf::json_str() {  # <file> <key> → <value>
  local f="$1" k="$2"
  if command -v jq >/dev/null; then
    jq -r --arg k "$k" \
      'if (.[$k] | type) == "string" then .[$k] else "" end' "$f" 2>/dev/null \
      | tr -d '\n'
  else
    sed -n "s/.*\"$k\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$f" \
      | head -1 | tr -d '\n'
  fi
}

# ---- worktrees --------------------------------------------------------------
# Which sibling worktrees exist, so the skill can tell "a worktree for the
# standing ticket already exists" from "one must be created".
wf::worktree_facts() {
  local n
  n="$(git worktree list 2>/dev/null | grep -cv '(bare)')"
  printf 'worktree_count=%s\n' "${n:-0}"
  # $0-with-prefix-stripped rather than $2: a path containing a space would
  # otherwise be truncated to a directory that doesn't exist. A detached
  # worktree emits no `branch` record, so flush on the blank separator line
  # too — otherwise worktree_count disagrees with the lines below it and the
  # skill concludes a worktree is missing.
  # ...and the bare root is excluded, matching worktree_count above.
  git worktree list --porcelain 2>/dev/null \
    | awk 'function flush() { if (p != "" && !bare) print "worktree=" p "::" b
                              p=""; b=""; bare=0 }
           /^worktree /{ flush(); p=$0; sub(/^worktree /,"",p) }
           /^bare$/    { bare=1 }
           /^branch /  { b=$0; sub(/^branch refs\/heads\//,"",b) }
           /^detached/ { b="(detached)" }
           END         { flush() }'
}

# ---- tooling ----------------------------------------------------------------
wf::tool_facts() {
  printf 'git_tools_dir=%s\n' "$([ -d "$GIT_TOOLS_DEFAULT" ] && printf '%s' "$GIT_TOOLS_DEFAULT")"
  local t
  for t in start-ticket.sh worktree-manager.sh open-pr.sh agent-phase.sh; do
    command -v "$t" >/dev/null \
      && printf 'tool_%s=on_path\n' "${t%.sh}" \
      || printf 'tool_%s=%s\n' "${t%.sh}" "$([ -x "$GIT_TOOLS_DEFAULT/$t" ] && echo "git_tools_only" || echo "missing")"
  done
}

main() {
  case "${1:-}" in
    -h|--help|help) usage; exit 0 ;;
    srcpath)
      [ $# -ge 2 ] || { echo "wf-context.sh srcpath <target>" >&2; exit 2; }
      local rc=0
      wf::source_path "$2" || rc=$?
      case "$rc" in
        0) printf '\n'; exit 0 ;;
        2) echo "chezmoi not installed" >&2; exit 2 ;;
        3) echo "chezmoi is installed but cannot read its source state. Do NOT treat $2 as unmanaged and do NOT edit it directly — fix chezmoi first: chezmoi doctor" >&2; exit 3 ;;
        *) echo "not chezmoi-managed (new file — use: chezmoi add $2). If chezmoi IGNORES this path, add warns and exits 0 without adding: read its output before reporting it added." >&2; exit 1 ;;
      esac ;;
    "") ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac

  wf::project_facts
  wf::worktree_facts
  wf::chezmoi_facts
  wf::tool_facts
}

main "$@"
