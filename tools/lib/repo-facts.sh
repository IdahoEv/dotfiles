#!/usr/bin/env bash
# lib/repo-facts.sh — shared, read-only facts about a repo/branch.
#
# Bash facade over lib/repo_facts.py: each gt:: function forwards to the
# repo-facts CLI (one python3 start, ~20 ms per call) until its last bash
# consumer is ported. The design rationale that used to live here — branch
# conventions, label distillation rules, the overlay layout, config
# precedence — is documented in repo_facts.py itself.
#
# Sourced by open-pr.sh, sibling-worktrees.sh, finalize-check.sh,
# start-ticket.sh, worktree-manager.sh, workflow-session.sh, session-label.sh,
# project-config.sh, lib/telemetry.sh and wf-context.sh.
#
# repo_key / ticket_from_branch / ticket_scheme stay native bash:
# telemetry's wf::emit calls all three per event, and it runs from
# wf-event.sh --hook on session lifecycle hooks — the hot path where three
# CLI forks per event would roughly triple the budget. They port together
# with telemetry (spike step 6); repo_facts_test.py covers the same value
# matrix for the Python implementations, and its Facade class exercises
# this file: env forwarding, exit codes, and the native ticket functions.

_GT_CLI="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/repo-facts.sh"

# An in-process implementation reads the label/overlay knobs as plain shell
# variables, exported or not; the CLI is a child process and only sees
# exported ones (worktree-manager assigns GT_LABEL_NOISE without export).
# Forward them all, set or not — every knob treats "" as unset on both sides.
_gt() {
  GT_LABEL_NOISE="${GT_LABEL_NOISE:-}" \
  GT_LABEL_WORDS="${GT_LABEL_WORDS:-}" \
  GT_LABEL_SLUG_WORDS="${GT_LABEL_SLUG_WORDS:-}" \
  GT_LABEL_MAX_CHARS="${GT_LABEL_MAX_CHARS:-}" \
  GT_LABEL_OVERRIDE="${GT_LABEL_OVERRIDE:-}" \
  GT_LABEL_SLUG_OVERRIDE="${GT_LABEL_SLUG_OVERRIDE:-}" \
  PROJECT_OVERLAYS_DIR="${PROJECT_OVERLAYS_DIR:-}" \
  GIT_TOOLS_PROJECTS_DIR="${GIT_TOOLS_PROJECTS_DIR:-}" \
  "$_GT_CLI" "$@"
}

gt::default_branch()       { _gt default-branch "$@"; }
gt::default_branch_ref()   { _gt default-branch-ref "$@"; }
gt::distill_title()        { _gt distill-title "$@"; }
gt::slug_title()           { _gt slug-title "$@"; }
gt::sanitize_label()       { _gt sanitize-label "$@"; }
gt::label_from_title()     { _gt label-from-title "$@"; }
gt::overlays_root()        { _gt overlays-root "$@"; }
gt::overlay_dir()          { _gt overlay-dir "$@"; }
gt::overlay_claude_dir()   { _gt overlay-claude-dir "$@"; }
gt::overlay_claude_files() { _gt overlay-claude-files "$@"; }
gt::main_root()            { _gt main-root "$@"; }
gt::conf_files()           { _gt conf-files "$@"; }
gt::conf_get()             { _gt conf-get "$@"; }
gt::find_doc()             { _gt find-doc "$@"; }

# <owner>/<repo> (or <group>/<sub>/<repo>) from an origin URL: scp-style ssh,
# ssh:// and https forms, trailing .git stripped. The host is not part of the
# key. Nothing for an unparseable URL. A "." or ".." segment is rejected: a
# hostile or typo'd remote ("../r") must not point the overlay outside the
# root. Native bash — see the header for why this one is not delegated.
gt::repo_key() {  # <url> → "owner/repo", or nothing
  local u="${1%/}" path
  u="${u%.git}"
  case "$u" in
    *://*) path="${u#*://}"; path="${path#*/}" ;;   # drop scheme and host
    *:*)   path="${u#*:}" ;;                        # scp-style: host:owner/repo
    *)     return 0 ;;
  esac
  # Two or more segments (GitLab subgroups nest); a "." or ".." segment would let
  # a hostile or typo'd remote ("../r") point the overlay outside the root.
  [[ "$path" =~ ^[^/]+(/[^/]+)+$ ]] || return 0
  [[ "/$path/" == */./* || "/$path/" == */../* ]] && return 0
  printf '%s' "$path"
}

# Ticket id / scheme: read .workstream.json first when <dir> is given, then
# accept both resolver key prefixes (Is<N>[+<N>...]-, sc-<N>[+<N>...]-) and
# legacy forms (<N>-slug, [<prefix>/]sc-<id>/<slug>). Native bash (header).
gt::ticket_from_branch() {  # <branch> [<dir>] → id, or nothing
  local b="$1" dir="${2:-}" rec="" id=""
  if [ -n "$dir" ] && [ -f "$dir/.workstream.json" ]; then
    rec="$dir/.workstream.json"
    if command -v jq >/dev/null 2>&1; then
      id="$(jq -r '.tickets[0].id // empty' "$rec" 2>/dev/null || true)"
      if [ -n "$id" ]; then
        printf '%s' "$id"
        return 0
      fi
    fi
  fi
  if [[ "$b" =~ sc-[0-9]+.*sc-([0-9]+) ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  elif [[ "$b" =~ (^|/)(Is|sc-)([0-9]+)(\+[0-9]+)*(-|/|$) ]]; then
    printf '%s' "${BASH_REMATCH[3]}"
  elif [[ "$b" =~ .*sc-([0-9]+) ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  elif [[ "$b" =~ ^([1-9][0-9]*)- ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  fi
  return 0
}

# Which dialect the workstream or branch uses: shortcut | github | unknown.
gt::ticket_scheme() {  # <branch> [<dir>] → shortcut | github | unknown
  local b="$1" dir="${2:-}" rec="" prov=""
  if [ -n "$dir" ] && [ -f "$dir/.workstream.json" ]; then
    rec="$dir/.workstream.json"
    if command -v jq >/dev/null 2>&1; then
      prov="$(jq -r 'if (.tickets | length) > 0 then (.ticket_provider // "github") else empty end' "$rec" 2>/dev/null || true)"
      if [ -n "$prov" ]; then
        if [ "$prov" = "shortcut" ]; then printf 'shortcut'
        else printf 'github'
        fi
        return 0
      fi
    fi
  fi
  if   [[ "$b" =~ (^|/)sc-[0-9]+(\+[0-9]+)*(-|/|$) ]]; then printf 'shortcut'
  elif [[ "$b" =~ (^|/)Is[0-9]+(\+[0-9]+)*(-|/|$) ]];  then printf 'github'
  elif [[ "$b" =~ .*sc-[0-9]+ ]];                  then printf 'shortcut'
  elif [[ "$b" =~ ^[1-9][0-9]*- ]];                 then printf 'github'
  else printf 'unknown'
  fi
}
