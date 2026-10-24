#!/usr/bin/env bash
# wf-context.sh — deterministic facts for the /workflow skill.
#
# The skill's job is judgment: deciding whether a proposed improvement is
# project-local or global, and designing the change. Everything *mechanical* it
# would otherwise re-derive with a dozen tool calls lives here instead, so the
# model spends its tokens on the decision rather than on probing the filesystem.
#
# Same rationale as tools/lib/repo-facts.sh: state a convention once, in shell,
# instead of restating it in prose and having the model re-run the probes.
#
# Leaves working trees untouched; safe to run anywhere. It does fetch
# remote-tracking refs in the checkouts it reports on, bounded by `timeout 10`
# where that binary exists — stock macOS lacks it, so there the fetch can block
# until git's own network timeout. Offline, the counts just reflect the last
# fetch. The default-branch lookup itself stays local-only, which is why it
# avoids gt::default_branch (see below). One further caveat: if the source dir ever
# declares an `archive`-type external with an expired refreshPeriod,
# `chezmoi source-path` will fetch it; the current config declares no such
# external.
#
# Usage:
#   wf-context.sh                      # key=value facts about the current repo
#   wf-context.sh srcpath <target>     # chezmoi source path for a target file
#   wf-context.sh --help
#
# `srcpath` exit codes: 0 managed (path on stdout; outside a dev worktree that
# path is in the deploy clone, read-only) · 1 in dev mode, a genuinely unmanaged
# file (the "new file" case); elsewhere, "not editable from here" — use a dev
# checkout, or file intake (/workflow §3) · 2 chezmoi not installed · 3 chezmoi
# can't read its source state — NOT a license to edit the target directly.
#
# `dotfiles_source=dev|deploy|none` says which checkout the `chezmoi_source_*`
# facts describe: a dev/ticket worktree (edit here), the deploy clone (pull and
# apply only), or neither (the deploy clone is still the effective source). The
# deploy clone's own state is always reported under `chezmoi_deploy_*`.
#
# The subcommand is `srcpath`, deliberately NOT `source`: a bare `source` in an
# argument list trips command-sandbox guards that scan for shell sourcing, which
# would block this script in exactly the isolated sessions that need it.
#
# Output is `key=value`, one per line, shell-safe and stable. Unknown values are
# empty rather than absent, so a consumer can parse without checking for keys.

set -uo pipefail

GIT_TOOLS_DEFAULT="$HOME/.local/share/chezmoi/tools"

# Memo state. Cleared here so an exported value in the caller's environment
# can't preempt a probe — a sentinel that answers from $ENV is worse than none.
unset _wf_chezmoi_probed _wf_chezmoi_healthy
unset _wf_deploy_probed _wf_deploy_healthy
unset _wf_resolved_top
_wf_deploy_root=""
_wf_source_override=""
_wf_dotfiles_source=""

usage() {
  cat <<'EOF'
wf-context.sh — deterministic facts for /workflow.

Usage:
  wf-context.sh                      # key=value facts about the current repo
  wf-context.sh srcpath <target>     # chezmoi source path for a target file
  wf-context.sh --help

srcpath exit codes: 0 managed · 1 unmanaged (in dev mode: the new-file case;
elsewhere: use a dev checkout, or file intake — /workflow §3) · 2 chezmoi not
installed · 3 chezmoi cannot read its source state — do NOT edit the target
directly.
EOF
}

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
# adding. Read its output; see delivery.md.
#
# rc 3 exists because `chezmoi source-path <target>` cannot be trusted to mean
# "not managed": it prints the same "not managed" on stderr and exits 1 for a
# genuinely-unmanaged file AND for a chezmoi that can't read its source state.
# Collapsing those routes the caller to the "new file" branch, where the rule is
# "it's not managed, so edit the target directly" — and editing ~/.claude/*
# directly is the exact thing this skill exists to prevent. It would also be
# silently undone by the next `chezmoi apply` once chezmoi is working again.
#
# Canonical directory, following macOS's /private symlinks. Empty on failure.
wf::canon_dir() { (cd -P "$1" 2>/dev/null && pwd -P); }

# The deploy clone's source root, always via chezmoi's default source. This is
# the machine's pull/apply checkout, not necessarily the working copy being
# edited.
#
# Resolved once in main. Callers read it through command substitution, so a
# probe here would run in a subshell and its memo would be discarded — a
# process spawn per call, not one.
wf::init_deploy_root() {
  _wf_deploy_root=""
  if command -v chezmoi >/dev/null; then
    _wf_deploy_root="$(command chezmoi source-path 2>/dev/null || true)"
  fi
}

wf::deploy_root() {
  printf '%s' "${_wf_deploy_root:-}"
}

# chezmoi against the effective source: the current worktree in `dev` mode,
# the default source otherwise.
wf::chezmoi() {
  if [ -n "${_wf_source_override:-}" ]; then
    command chezmoi -S "$_wf_source_override" "$@"
  else
    command chezmoi "$@"
  fi
}

wf::git_common_dir() {  # <repo-dir> → canonical common dir, or empty
  local d
  d="$(git -C "$1" rev-parse --git-common-dir 2>/dev/null)" || return 1
  [ -n "$d" ] || return 1
  case "$d" in /*) ;; *) d="$1/$d" ;; esac
  wf::canon_dir "$d"
}

# Which copy of the dotfiles source this session should consider authoritative:
#
#   dev     a dev/ticket worktree (or the bare layout's main) — edit here
#   deploy  the chezmoi deploy clone itself — pull/apply only, never edit
#   none    not the dotfiles repo — the deploy clone is still the source for
#           reference, but edits do not happen from here
#
# The normal layout is two SEPARATE clones, so equal git common dirs cannot
# identify a dev worktree; the `.chezmoiignore` + `dot_claude/` markers do.
# Common-dir equality is checked first only because it also holds if a future
# deploy clone is a linked worktree of the dev repo.
wf::resolve_dotfiles_source() {
  _wf_dotfiles_source=none
  _wf_source_override=""
  local top deploy deploy_c top_c conventional
  top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$top" ] || return 0
  top="$(wf::canon_dir "$top")"
  _wf_resolved_top="$top"
  deploy="$(wf::deploy_root)"
  if [ -n "$deploy" ]; then
    deploy="$(wf::canon_dir "$deploy")"
    if [ "$top" = "$deploy" ]; then
      _wf_dotfiles_source=deploy
      return 0
    fi
    deploy_c="$(wf::git_common_dir "$deploy")"
    top_c="$(wf::git_common_dir "$top")"
    if [ -n "$deploy_c" ] && [ "$deploy_c" = "$top_c" ]; then
      _wf_dotfiles_source=dev
      _wf_source_override="$top"
      return 0
    fi
  fi
  # Without a working chezmoi, the markers below cannot tell the deploy clone
  # from a dev worktree — and mislabelling the deploy clone `dev` invites edits
  # to the one checkout that must stay untouched. Its conventional path still
  # distinguishes it.
  if [ -z "$deploy" ]; then
    conventional="${CHEZMOI_SOURCE_DIR:-$HOME/.local/share/chezmoi}"
    if [ -d "$conventional" ] \
       && [ "$top" = "$(wf::canon_dir "$conventional")" ]; then
      _wf_dotfiles_source=deploy
      return 0
    fi
  fi
  if [ -f "$top/.chezmoiignore" ] && [ -d "$top/dot_claude" ]; then
    _wf_dotfiles_source=dev
    _wf_source_override="$top"
  fi
}

# Source path in the deploy clone, regardless of the effective source. Used
# only to explain a dev-mode rc 1: the branch may simply not carry the file.
wf::deploy_source_path() {  # <target> → <path>, or empty
  local root
  root="$(wf::deploy_root)"
  [ -n "$root" ] || return 0
  command chezmoi -S "$root" source-path -- "$1" 2>/dev/null || true
}

# See wf::chezmoi_healthy for the discriminator and why it takes two tests.
wf::source_path() {  # <target> → <source path>
  local target="$1" src
  command -v chezmoi >/dev/null || return 2
  # `--` so a target beginning with a dash can't be read as a chezmoi flag:
  # `source-path --source=/tmp` otherwise prints /tmp and exits 0, i.e. the
  # strongest claim this function makes, for something that isn't a file.
  if src="$(wf::chezmoi source-path -- "$target" 2>/dev/null)"; then
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
wf::source_readable() {  # <source-dir|""> — "" means chezmoi's default source
  local dir="${1:-}" root
  command -v chezmoi >/dev/null || return 1
  if [ -n "$dir" ]; then
    [ -d "$dir" ] || return 1
    command chezmoi -S "$dir" managed >/dev/null 2>&1
  else
    root="$(command chezmoi source-path 2>/dev/null)" || return 1
    [ -n "$root" ] && [ -d "$root" ] || return 1
    command chezmoi managed >/dev/null 2>&1
  fi
}

wf::chezmoi_healthy() {  # effective source (the worktree in `dev` mode)
  if [ "${_wf_chezmoi_probed:-}" != yes ]; then
    # Pass the resolved root: `""` would make source_readable spawn
    # `chezmoi source-path` again, in every non-dev run.
    if wf::source_readable "${_wf_source_override:-$(wf::deploy_root)}"; then
      _wf_chezmoi_healthy=yes
    else
      _wf_chezmoi_healthy=no
    fi
    _wf_chezmoi_probed=yes
  fi
  [ "$_wf_chezmoi_healthy" = yes ]
}

# The deploy clone has its own source state: in `dev` mode a broken worktree
# must not be reported as a broken install, and vice versa.
wf::chezmoi_deploy_healthy() {
  if [ "${_wf_deploy_probed:-}" != yes ]; then
    if wf::source_readable "$(wf::deploy_root)"; then
      _wf_deploy_healthy=yes
    else
      _wf_deploy_healthy=no
    fi
    _wf_deploy_probed=yes
  fi
  [ "$_wf_deploy_healthy" = yes ]
}

# Local-only default branch: origin/HEAD when it resolves, else
# gt::default_branch_ref's fixed-order probe. Prints "<branch>\t<source>" so the
# caller gets the provenance too (the probe is a guess; see §1).
wf::default_branch() {  # <dir> → "<branch>\t<source>"
  local dir="$1" default src="origin_head"
  default="$(git -C "$dir" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null)"
  default="${default#refs/remotes/origin/}"
  # A symref can outlive its target; verify the full ref path (a tag named
  # origin/<x> would also satisfy a bare test).
  if [ -n "$default" ] \
     && ! git -C "$dir" rev-parse --verify -q \
          "refs/remotes/origin/$default" >/dev/null; then
    default=""
  fi
  if [ -z "$default" ] && declare -f gt::default_branch_ref >/dev/null 2>&1; then
    default="$(gt::default_branch_ref "$dir" 2>/dev/null || true)"
    default="${default#origin/}"
    [ -n "$default" ] && src="probe"
  fi
  [ -n "$default" ] || src=none
  printf '%s\t%s\n' "$default" "$src"
}

# Split wf::default_branch's output. `read` cannot do this: with no branch the
# line starts with a tab, and read collapses leading IFS whitespace — turning
# "\tnone" into default="none". Expansion preserves the empty field.
wf::default_branch_parts() {  # <dir> → sets _wf_default_branch, _wf_default_source
  local out
  out="$(wf::default_branch "$1")"
  _wf_default_branch="${out%%$'\t'*}"
  case "$out" in
    *$'\t'*) _wf_default_source="${out#*$'\t'}" ;;
    *)       _wf_default_source="" ;;
  esac
}

# Dirty / ahead / behind / pull.rebase for one checkout. Compares against
# origin/<default>, NOT @{upstream}: a fresh ticket worktree has no upstream, and
# the question these facts answer is "is this checkout in step with the remote",
# not "with its own remote branch". Counts are omitted (never zeroed) when no
# comparison can be made.
wf::repo_sync_facts() {  # <key-prefix> <git-dir|"">
  local p="$1" root="$2" counts="" default ahead behind status n
  if [ -n "$root" ] && git -C "$root" rev-parse --git-dir >/dev/null 2>&1; then
    # A failed status (corrupt index, unreadable tree) is unknown, not clean —
    # zero would read as "safe to pull into".
    if status="$(git -C "$root" status --porcelain 2>/dev/null)"; then
      case "$status" in
        "") n=0 ;;
        *)  n="$(printf '%s\n' "$status" | wc -l | tr -d ' ')" ;;
      esac
      printf '%s_dirty_files=%s\n' "$p" "$n"
    else
      printf '%s_dirty_files=\n' "$p"
    fi
    local bound=""
    command -v timeout >/dev/null && bound="timeout 10"   # absent on stock macOS
    # shellcheck disable=SC2086  # $bound is intentionally word-split
    GIT_TERMINAL_PROMPT=0 $bound git -C "$root" fetch --quiet >/dev/null 2>&1 || true
    wf::default_branch_parts "$root"
    default="$_wf_default_branch"
    # Both a symbolic ref and a surviving tag can name origin/<default>; only a
    # real remote-tracking ref is a valid comparison base.
    if [ -n "$default" ] \
       && git -C "$root" rev-parse --verify -q "refs/remotes/origin/$default" >/dev/null; then
      printf '%s_compare_ref=origin/%s\n' "$p" "$default"
      # origin/<default>...HEAD: left counts what the remote has that we lack.
      if read -r behind ahead <<<"$(git -C "$root" rev-list --left-right --count \
        "refs/remotes/origin/$default...HEAD" 2>/dev/null)"; then
        [ -n "${behind:-}" ] && [ -n "${ahead:-}" ] \
          && printf '%s_ahead_origin=%s\n%s_behind_origin=%s\n' "$p" "$ahead" "$p" "$behind"
      fi
    else
      printf '%s_compare_ref=\n' "$p"
      if read -r ahead behind <<<"$(git -C "$root" rev-list --left-right --count \
        'HEAD...@{upstream}' 2>/dev/null)"; then
        [ -n "${ahead:-}" ] && [ -n "${behind:-}" ] \
          && printf '%s_ahead_origin=%s\n%s_behind_origin=%s\n' "$p" "$ahead" "$p" "$behind"
      fi
    fi
    printf '%s_pull_rebase=%s\n' "$p" \
      "$(git -C "$root" config --type=bool --get pull.rebase 2>/dev/null || echo unset)"
  else
    printf '%s_dirty_files=\n%s_compare_ref=\n%s_pull_rebase=\n' "$p" "$p" "$p"
  fi
}

wf::chezmoi_facts() {
  local src_root deploy_root deploy_branch="" managed="no" claude_md_src="" tmpl="no"
  local settings_src settings_kind="plain" deploy_facts

  if command -v chezmoi >/dev/null; then
    printf 'chezmoi_available=yes\n'
  else
    printf 'chezmoi_available=no\n'
  fi
  printf 'dotfiles_source=%s\n' "$_wf_dotfiles_source"

  if ! command -v chezmoi >/dev/null; then
    # Health is unknown, not bad: an absent binary says nothing about the clone.
    # The checkout itself is still known when resolve identified it, and the
    # branch/dirty/behind facts are git-derived.
    deploy_root=""
    if [ "$_wf_dotfiles_source" = deploy ]; then deploy_root="${_wf_resolved_top:-}"; fi
    printf 'chezmoi_manages_claude=unknown\nchezmoi_deploy_root=%s\n' "$deploy_root"
    if [ -n "$deploy_root" ]; then
      deploy_branch="$(git -C "$deploy_root" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    fi
    printf 'chezmoi_deploy_branch=%s\nchezmoi_deploy_healthy=\n' "$deploy_branch"
    deploy_facts="$(wf::repo_sync_facts chezmoi_deploy "$deploy_root")"
    printf '%s\n' "$deploy_facts"
    # Losing the git-derived counts would hide a stale base at the one moment
    # the session cannot check anything else.
    if [ -n "${_wf_source_override:-}" ]; then
      printf 'chezmoi_source_root=%s\n' "$_wf_source_override"
      wf::repo_sync_facts chezmoi_source "$_wf_source_override"
    elif [ -n "$deploy_root" ]; then
      printf 'chezmoi_source_root=%s\n' "$deploy_root"
      printf '%s\n' "$deploy_facts" | sed 's/^chezmoi_deploy_/chezmoi_source_/'
    fi
    return
  fi

  # Installed is not the same as working. Everything below reads source state;
  # if chezmoi can't see its source dir, every answer is a false negative, so
  # say so once up front rather than emitting a page of misleading "no"s.
  if wf::chezmoi_healthy; then
    printf 'chezmoi_healthy=yes\n'
  else
    printf 'chezmoi_healthy=no\n'
  fi

  deploy_root="$(wf::deploy_root)"
  src_root="${_wf_source_override:-$deploy_root}"
  printf 'chezmoi_source_root=%s\n' "$src_root"

  # Is ~/.claude under chezmoi's control at all?
  if wf::chezmoi managed 2>/dev/null | grep -qxF '.claude'; then managed="yes"; fi
  printf 'chezmoi_manages_claude=%s\n' "$managed"

  claude_md_src="$(wf::source_path "$HOME/.claude/CLAUDE.md" || true)"
  printf 'chezmoi_claude_md_source=%s\n' "$claude_md_src"
  case "$claude_md_src" in *.tmpl) tmpl="yes" ;; esac
  printf 'chezmoi_claude_md_is_template=%s\n' "$tmpl"

  # settings.json may be a `modify_` source: a SCRIPT that rewrites the target,
  # not the target's contents. Editing it as if it were JSON corrupts it. Report
  # the kind so the prompt doesn't have to carry the rule.
  settings_src="$(wf::source_path "$HOME/.claude/settings.json" || true)"
  printf 'chezmoi_settings_source=%s\n' "$settings_src"
  case "$(basename "${settings_src:-}")" in
    modify_*) settings_kind="modify" ;;
    "")       settings_kind="unmanaged" ;;
  esac
  printf 'chezmoi_settings_source_kind=%s\n' "$settings_kind"

  # The deploy clone, reported separately: after a merge it is what needs the
  # pull + apply, whatever branch this session's worktree is on.
  printf 'chezmoi_deploy_root=%s\n' "$deploy_root"
  if [ -n "$deploy_root" ]; then
    deploy_branch="$(git -C "$deploy_root" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  fi
  printf 'chezmoi_deploy_branch=%s\n' "$deploy_branch"
  if wf::chezmoi_deploy_healthy; then
    printf 'chezmoi_deploy_healthy=yes\n'
  else
    printf 'chezmoi_deploy_healthy=no\n'
  fi
  deploy_facts="$(wf::repo_sync_facts chezmoi_deploy "$deploy_root")"
  printf '%s\n' "$deploy_facts"
  # Outside `dev` mode the effective source IS the deploy clone. Scan it once
  # and re-prefix the lines: a second call would repeat the fetch and the full
  # status scan on every orient in an ordinary project.
  if [ "$src_root" = "$deploy_root" ]; then
    printf '%s\n' "$deploy_facts" | sed 's/^chezmoi_deploy_/chezmoi_source_/'
  else
    wf::repo_sync_facts chezmoi_source "$src_root"
  fi
}

# ---- project ----------------------------------------------------------------
wf::project_facts() {
  local top branch default default_source ahead behind dirty status n cfg

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
  # two minutes offline. The bounded `git fetch` in wf::repo_sync_facts is a
  # separate, intended call; nothing here may add another.
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

  # Expansion, not `read`: with no default branch the line begins with a tab,
  # which read would eat (see wf::default_branch_parts).
  wf::default_branch_parts "$top"
  default="$_wf_default_branch"
  default_source="$_wf_default_source"
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

  # Unknown, not clean, when status can't run (same hazard as repo_sync_facts).
  if status="$(git -C "$top" status --porcelain 2>/dev/null)"; then
    case "$status" in
      "") n=0 ;;
      *)  n="$(printf '%s\n' "$status" | wc -l | tr -d ' ')" ;;
    esac
    printf 'working_tree_dirty_files=%s\n' "$n"
  else
    printf 'working_tree_dirty_files=\n'
  fi

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
    srcpath) [ $# -ge 2 ] || { echo "wf-context.sh srcpath <target>" >&2; exit 2; } ;;
    "") ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac

  wf::init_deploy_root
  wf::resolve_dotfiles_source

  if [ "${1:-}" = srcpath ]; then
    local target="$2" rc=0 deploy_src
    wf::source_path "$target" || rc=$?
    case "$rc" in
      0)
        # Stdout stays a bare path for callers; the warning goes to stderr so
        # a non-dev session does not mistake a deploy-clone path for edit access.
        if [ -z "${_wf_source_override:-}" ]; then
          echo "this path is in the deploy clone: pull/apply only — author edits in a dotfiles dev checkout, or file intake for a global change (delivery.md, /workflow §3)." >&2
        fi
        printf '\n'; exit 0 ;;
      2) echo "chezmoi not installed" >&2; exit 2 ;;
      3)
        if [ -n "${_wf_source_override:-}" ]; then
          echo "chezmoi cannot read the source state of $_wf_source_override: one of .chezmoiignore, .chezmoidata.*, .chezmoiexternal.* or .chezmoiversion there won't parse. Do NOT treat $target as unmanaged or edit it directly, and do not duplicate the file into the deploy clone. Note that chezmoi doctor only inspects the default source, not this worktree." >&2
        else
          echo "chezmoi is installed but cannot read the source state of $(wf::deploy_root). Do NOT treat $target as unmanaged and do NOT edit it directly — fix chezmoi first: chezmoi doctor." >&2
        fi
        exit 3 ;;
      *)
        if [ -n "${_wf_source_override:-}" ]; then
          if wf::chezmoi_deploy_healthy; then
            deploy_src="$(wf::deploy_source_path "$target")"
            if [ -n "$deploy_src" ]; then
              echo "not managed in this worktree ($_wf_source_override); the deploy source has it at $deploy_src — the branch may simply not carry this file." >&2
            else
              echo "not chezmoi-managed in this worktree ($_wf_source_override). New file: create the source directly, or derive its name with: chezmoi -S \"$_wf_source_override\" add $target. If chezmoi IGNORES this path, add warns and exits 0 without adding: read its output before reporting it added." >&2
            fi
          else
            echo "not managed in this worktree ($_wf_source_override), and the deploy source cannot be read — whether the file already exists on main is unknown. Fix the deploy source (delivery.md, rc 3) before creating a new file here." >&2
          fi
        elif [ "$_wf_dotfiles_source" = deploy ]; then
          echo "not chezmoi-managed, and this is the deploy clone: author it in a dev checkout (delivery.md), not here — do not run chezmoi add against it." >&2
        else
          echo "not chezmoi-managed, and this is not the dotfiles repo: a global change is an intake issue in the dotfiles repo, not an edit here — /workflow §3 covers intake." >&2
        fi
        exit 1 ;;
    esac
  fi

  wf::project_facts
  wf::worktree_facts
  wf::chezmoi_facts
  wf::tool_facts
}

main "$@"
