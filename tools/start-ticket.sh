#!/usr/bin/env bash
# start-ticket.sh — spin up a worktree + Claude session for a tracker ticket.
#
#   start-ticket.sh <id> [--provider github|shortcut] [--no-tab] [--launcher iterm|bg|none]
#   start-ticket.sh <id> --print-title            # read-only: title + proposed label
#   start-ticket.sh --tab-only <worktree> <kickoff> [--launcher iterm|bg|none]
#   start-ticket.sh --session [<topic>] [--about <text>] [--launcher iterm|bg|none]
#
# --session opens a non-ticket discussion session (/discuss): no ticket, branch
# or worktree. It launches in the main checkout (for a bare repo, the worktree
# holding the default branch), named "[TALK] <topic>", with a kickoff built
# from the project preamble plus session-kickoff.md, whose rules move the
# session onto a ticket worktree when the user asks for code.
#
# Resolves a ticket (GitHub issue or Shortcut story) to a branch, creates a
# worktree via worktree-manager.sh, marks the ticket in progress, writes a
# kickoff prompt, and starts a Claude session for it with a "launcher":
#   iterm (default)  a 2-pane iTerm tab: claude on top with the prompt typed in
#                    but unsubmitted; a shell on the bottom.
#   bg               a background session for Claude Code's agent view
#                    (`claude agents`): claude --bg --name "<label>" "<kickoff>".
#                    The kickoff is SUBMITTED immediately, so it starts in plan
#                    mode by default to keep a review gate (see bg_permission_mode).
#   none             worktree + kickoff only (same as --no-tab).
#
# Launcher is chosen by, in order: --launcher flag → $START_TICKET_LAUNCHER →
# `launcher=` in .start-ticket.conf / ~/.config/start-ticket/config → iterm (none off macOS).
# Put `launcher=bg` in the per-machine ~/.config/start-ticket/config to opt in.
#
# Run from anywhere inside the target repo. Provider is chosen by, in order:
#   --provider flag → .start-ticket.conf (provider=…) → autodetect (gh vs short).
#
# Env knobs: START_TICKET_CLAUDE_DELAY (secs before typing the prompt, default 3),
#   START_TICKET_TAB_MAXLEN (default 30), START_TICKET_PROVIDER_DIR,
#   START_TICKET_BG_MAXLEN (agent-view row name length, default 70),
#   START_TICKET_BG_PERMISSION_MODE or `bg_permission_mode=` in the conf files
#   (bg launcher only; default "plan"; "default" passes no --permission-mode).
#
# Session/tab names are distilled from the ticket TITLE (gt::distill_title in
# lib/repo-facts.sh), not from the branch — see make_label. Tune with
# `label_noise=` in .start-ticket.conf (words this repo repeats in every title,
# e.g. its own name) or GT_LABEL_WORDS (how many words to keep, default 4).
#
# A caller that can read the title with judgment available (the /start command,
# which is a Claude session) should pass the label in $GT_LABEL_OVERRIDE; it is
# sanitized and used verbatim, and anything unusable falls back to the
# distiller. Use --print-title to fetch a title without creating anything.
#
# That override reaches the session/tab label ONLY. The branch slug and worktree
# directory stay deterministic, since both are matched against later; override
# them deliberately with $GT_LABEL_SLUG_OVERRIDE if you really mean to.
#
# Providers: <script-dir>/start-ticket-providers/<name>.sh (override with
# $START_TICKET_PROVIDER_DIR), each defining:
#   provider::available
#   provider::fetch <id>              → sets ST_TITLE ST_BODY ST_URL ST_PARENT ST_BRANCH
#   provider::create_worktree <id>    → echoes worktree path (last line)
#   provider::post_worktree <id> <wt> → optional; re-populate ST_* from files in <wt>
#   provider::mark_in_progress <id>

set -euo pipefail

die() { printf 'start-ticket: %s\n' "$*" >&2; exit 1; }

# Literal (non-regex) replace of every <from> with <to> in <string>. Pure bash
# so values containing '/', '&', '\' etc. can't corrupt or abort the result the
# way `sed`/`awk` substitution would.
subst() {  # <string> <from> <to>
  local s="$1" from="$2" to="$3" out=""
  while [ "$s" != "${s#*"$from"}" ]; do
    out+="${s%%"$from"*}$to"
    s="${s#*"$from"}"
  done
  printf '%s%s' "$out" "$s"
}

# ---- resolve our own dir (following symlinks) -----------------------------
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
# shellcheck source=lib/repo-facts.sh
. "$SCRIPT_DIR/lib/repo-facts.sh"
# Provider lookup (first dir containing <name>.sh wins):
#   1. $START_TICKET_PROVIDER_DIR (explicit override)
#   2. <main-repo-root>/.project-overlays/start-ticket-providers  (per-repo)
#   3. ~/.config/project-overlays/.start-ticket-providers          (per-machine)
#   4. this repo's start-ticket-providers/                         (shipped defaults)
# Same layering as open-pr.sh's find_provider_file.
find_provider_file() {  # <name> → path, or empty
  local name="$1" main_root common pd f
  common="$(git rev-parse --git-common-dir 2>/dev/null || true)"
  if [ -n "$common" ]; then
    common="$(cd -P "$common" 2>/dev/null && pwd)" && main_root="$(dirname "$common")" || main_root=""
  fi
  for pd in "${START_TICKET_PROVIDER_DIR:-}" \
            "${main_root:-}/.project-overlays/start-ticket-providers" \
            "$HOME/.config/project-overlays/.start-ticket-providers" \
            "$SCRIPT_DIR/start-ticket-providers"; do
    [ -n "$pd" ] || continue
    f="$pd/$name.sh"
    [ -f "$f" ] && { printf '%s' "$f"; return 0; }
  done
  return 0
}

conf_get() {  # <key> → value; precedence is gt::conf_get's (repo, overlay, machine)
  gt::conf_get "$1"
}

# setting <conf-key> <ENV_VAR> <default>: env var → conf file → default.
setting() {
  local v="${!2:-}"
  [ -n "$v" ] || v="$(conf_get "$1" || true)"
  printf '%s' "${v:-$3}"
}

# Words that are noise in THIS repo's ticket titles — typically the project's
# own name, which every ticket repeats and which therefore tells the reader
# nothing when they're scanning a list of them. Set `label_noise=billing core` in
# .start-ticket.conf. Consumed by gt::distill_title.
GT_LABEL_NOISE="$(setting label_noise GT_LABEL_NOISE "")"
export GT_LABEL_NOISE

# make_label <branch> <maxlen> [pretty] → short tab / agent-view row label.
# Branch "<n>-<slug>" -> "Is<n> <slug>"; Shortcut "<user>/sc-<id>/<slug>" ->
# "Sc<id> <slug>". The ticket number is ALWAYS kept; the slug is truncated.
# "Is" (not "#") disambiguates issue numbers from PR numbers at a glance,
# since GitHub shares one number sequence between the two. With "pretty",
# hyphens in the slug become spaces (more readable in agent-view rows).
#
# The slug is distilled from $ST_TITLE when the provider supplied one, and only
# falls back to the branch segment when it didn't. That ordering is the whole
# point: the branch segment is itself a lossy tracker slug, so truncating it
# truncates a truncation — Shortcut's "-core--decide-billing-data-deletio"
# becomes the useless "core decide billing data deletio", while the title it
# came from distills to "Data Deletion Retention Policy". See gt::distill_title.
make_label() {
  local branch="$1" maxlen="$2" pretty="${3:-}" num="" slug="$1" distilled=""
  if [[ "$branch" =~ ^([0-9]+)-(.+)$ ]]; then
    num="Is${BASH_REMATCH[1]}"
    slug="${BASH_REMATCH[2]}"
  elif [[ "$branch" =~ (^|/)sc-([0-9]+)/(.+)$ ]]; then
    num="Sc${BASH_REMATCH[2]}"
    slug="${BASH_REMATCH[3]}"
  fi
  if [ -n "${ST_TITLE:-}" ] || [ -n "${GT_LABEL_OVERRIDE:-}" ]; then
    distilled="$(gt::label_from_title "${ST_TITLE:-}")"
    [ -n "$distilled" ] && slug="$distilled"
  fi
  # Only the branch-derived slug needs de-hyphenating; a distilled title is
  # already spaced words.
  [ -n "$pretty" ] && [ -z "$distilled" ] && slug="${slug//-/ }"
  if [ -n "$num" ]; then
    # Reserve room for "IsN " and the ellipsis when truncating the slug.
    local budget=$((maxlen - ${#num} - 2))
    slug="$(fit "$slug" "$budget" "$distilled")"
    printf '%s %s' "$num" "$slug"
  else
    slug="$(fit "$slug" "$maxlen" "$distilled")"
    printf '%s' "$slug"
  fi
}

# fit <text> <maxlen> [whole_words] → text trimmed to maxlen.
# With <whole_words> non-empty, drop trailing WORDS until it fits rather than
# cutting mid-word: at the iTerm tab width (30) a distilled label like
# "Data Deletion Retention Policy" otherwise lands as "Data Deletion Retent…",
# where the truncated word is the one carrying the meaning. Dropping to
# "Data Deletion…" costs a word but keeps every word it shows readable.
# Falls back to a character cut if even the first word is too long.
fit() {
  local text="$1" maxlen="$2" whole="${3:-}"
  [ "${#text}" -le "$maxlen" ] && { printf '%s' "$text"; return; }
  if [ -n "$whole" ]; then
    local trimmed="$text"
    while [ -n "$trimmed" ] && [ "${#trimmed}" -gt "$((maxlen - 1))" ]; do
      [[ "$trimmed" == *" "* ]] || break
      trimmed="${trimmed% *}"
    done
    if [ -n "$trimmed" ] && [ "${#trimmed}" -le "$((maxlen - 1))" ]; then
      printf '%s…' "$trimmed"; return
    fi
  fi
  printf '%s…' "${text:0:$((maxlen - 1))}"
}

# Tries each clipboard tool in turn (a tool on PATH can still fail, e.g. xclip
# with no DISPLAY on WSL); returns 1 if none succeeds.
copy_to_clipboard() {  # <file>
  local f="$1" t
  for t in pbcopy wl-copy "xclip -selection clipboard" clip.exe; do
    command -v "${t%% *}" >/dev/null && $t < "$f" 2>/dev/null && return 0
  done
  return 1
}

# ---- iTerm tab ---------------------------------------------------------------
# Opens a new iTerm tab, split into two horizontal panes:
#   top    — `claude` (bare); the kickoff prompt is typed into its input via a
#            bracketed paste after START_TICKET_CLAUDE_DELAY seconds, left
#            UNSUBMITTED for review.
#   bottom — a plain shell in the worktree.
# The kickoff is also put on the clipboard as a fallback (paste with ⌘V).
# Tab name = "Is<n> <slug>" where the ticket number is ALWAYS kept and the slug is
# truncated instead (to START_TICKET_TAB_MAXLEN). The name is re-asserted after
# commands are written so iTerm's automatic title updates don't clobber it.
open_tab() {  # <worktree> <kickoff> [<label>]
  local wt="$1" kf="$2" label="${3:-}"
  if [ -n "$label" ]; then
    label="$(fit "$label" "${START_TICKET_TAB_MAXLEN:-30}" words)"
  else
    local branch; branch="$(git -C "$wt" branch --show-current 2>/dev/null || basename "$wt")"
    label="$(make_label "$branch" "${START_TICKET_TAB_MAXLEN:-30}")"
  fi

  local delay="${START_TICKET_CLAUDE_DELAY:-3}"

  local copied=""
  copy_to_clipboard "$kf" && copied=1

  if [ "${TERM_PROGRAM:-}" != "iTerm.app" ] && [ "${LC_TERMINAL:-}" != "iTerm2" ]; then
    if [ -n "$copied" ]; then
      printf '\nNot in iTerm. Kickoff is on the clipboard and at %s\n  cd %q && claude   # then paste the kickoff\n' "$kf" "$wt"
    else
      printf '\nNot in iTerm. Kickoff is at %s\n  cd %q && claude   # then paste the kickoff\n' "$kf" "$wt"
    fi
    return
  fi

  osascript - "$wt" "$kf" "$label" "$delay" "$(cat "$kf")" <<'OSA'
on run argv
  set wt to item 1 of argv
  set kf to item 2 of argv
  set tabName to item 3 of argv
  set startDelay to (item 4 of argv) as integer
  set promptText to item 5 of argv
  set ESC to (ASCII character 27)
  tell application "iTerm2"
    tell current window
      try
        set newTab to (create tab with profile "Ticket")
      on error
        -- "Ticket" dynamic profile not loaded yet. Install it via
        -- setup-ticket-profile.sh (writes the DynamicProfiles JSON; iTerm
        -- picks it up live), but fall back rather than fail outright.
        set newTab to (create tab with default profile)
      end try
      tell newTab
        set topPane to current session
        tell topPane
          set name to tabName
          write text "cd " & quoted form of wt & " && claude"
          -- Re-assert the name after launching: shells/Claude may set their own
          -- title, which would bury the ticket number.
          set name to tabName
          try
            set botPane to (split horizontally with profile "Ticket")
          on error
            set botPane to (split horizontally with default profile)
          end try
        end tell
        tell botPane
          set name to tabName
          write text "cd " & quoted form of wt & " && clear"
          write text "printf '%s\\n' '──── kickoff (typed into Claude above, unsubmitted; also on clipboard) ────'"
          write text "(command -v bat >/dev/null && bat --style=plain --paging=never " & quoted form of kf & " || cat " & quoted form of kf & ")"
          write text "printf '\\n%s\\n' '────' 'Looks good: click Claude above, press Enter.' 'Edit first: $EDITOR " & kf & " ; pbcopy < " & kf & " ; clear Claude input; paste; Enter.'"
        end tell
        delay startDelay
        tell topPane
          write text (ESC & "[200~" & promptText & ESC & "[201~") newline false
          select
          -- Final re-assert after the kickoff is typed: Claude's session-start
          -- title update lands around here.
          set name to tabName
        end tell
      end tell
    end tell
  end tell
end run
OSA
}

# ---- background session (Claude Code agent view) -----------------------------
# Starts `claude --bg` in the worktree so the session shows up as a row in
# `claude agents`, named "[PLAN] Is<n> <slug>" (hyphens → spaces,
# START_TICKET_BG_MAXLEN long). The "[PLAN]" prefix is the ticket's workflow
# phase; the session advances it itself (agent-phase.sh) as the ticket moves
# plan → wip → review → merged → done, giving the agent view a third state axis
# beyond `status` (idle/busy) and `state` (working/blocked/done). It starts at
# PLAN because the bg launcher submits the kickoff immediately in plan mode, so
# the session's first act is always to propose rather than edit.
# Because the worktree already exists (worktree-manager.sh made it),
# Claude Code uses it as-is rather than creating its own under .claude/worktrees/,
# so .worktree-sync seeding is preserved and /finalize's cleanup still applies.
# Unlike the iTerm launcher, the kickoff is submitted immediately; the default
# permission mode is therefore "plan" (Claude proposes before editing).
# claude's own output goes to stderr to keep this script's stdout parseable.
open_bg() {  # <worktree> <kickoff> [<label>]
  local wt="$1" kf="$2" label="${3:-}"
  command -v claude >/dev/null || die "claude CLI not found (needed by the bg launcher)"
  if [ -z "$label" ]; then
    local branch; branch="$(git -C "$wt" branch --show-current 2>/dev/null || basename "$wt")"
    label="$(make_label "$branch" "${START_TICKET_BG_MAXLEN:-70}" pretty)"
    # The phase prefix is budgeted outside make_label's maxlen: truncating the
    # slug is fine, truncating "[PLAN]" would defeat the point of the label.
    label="[PLAN] $label"
  fi
  local perm; perm="$(setting bg_permission_mode START_TICKET_BG_PERMISSION_MODE plan)"
  local args=(--bg --name "$label")
  [ "$perm" = "default" ] || args+=(--permission-mode "$perm")

  printf 'start-ticket: dispatching background session "%s" (permission mode: %s)\n' "$label" "$perm" >&2
  if ! ( cd "$wt" && claude "${args[@]}" "$(cat "$kf")" ) >&2; then
    local retry_args; retry_args="$(printf '%q ' "${args[@]}")"
    printf 'start-ticket: `claude --bg` failed. If it mentioned workspace trust, run `cd %q && claude` once to accept the trust dialog, then retry:\n  cd %q && claude %s"$(cat %q)"\n' \
      "$wt" "$wt" "$retry_args" "$kf" >&2
    return 1
  fi
}

launch_session() {  # <worktree> <kickoff> [<label>] — uses the resolved $launcher
  local tab_label="${3:-}"
  case "$launcher" in
    iterm) open_tab "$1" "$2" "${tab_label#\[TALK\] }" ;;
    bg)    open_bg  "$1" "$2" "${3:-}" ;;
    none)  : ;;
  esac
}

# ---- discussion session (--session) ------------------------------------------
# The main checkout, or for a bare repo (the dotfiles dev copy) the worktree
# holding the default branch; else the current checkout.
session_dir() {
  local common main b wt="" line cur=""
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
    || die "not inside a git repo"
  if [ "$(git -C "$common" rev-parse --is-bare-repository)" != true ]; then
    gt::main_root
    return 0
  fi
  b="$(gt::default_branch 2>/dev/null || git -C "$common" symbolic-ref --short HEAD 2>/dev/null || true)"
  if [ -n "$b" ]; then
    while IFS= read -r line; do
      case "$line" in
        "worktree "*) cur="${line#worktree }" ;;
        "branch refs/heads/$b") wt="$cur"; break ;;
      esac
    done < <(git -C "$common" worktree list --porcelain)
  fi
  [ -n "$wt" ] && { printf '%s' "$wt"; return 0; }
  git rev-parse --show-toplevel 2>/dev/null || die "bare repo with no worktree for '$b'"
}

# Personal, project-scoped Claude assets from the overlay's claude/ dir, as a
# kickoff section. Empty (and so omitted) when the repo defines none.
personal_assets_block() {  # <dir> → markdown, or empty
  local dir="$1" f out=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -n "$out" ] || out="$(printf '\n## Personal project Claude assets\n\nThese live in the per-project overlay, outside this checkout. Invoke them without copying files: an agent — launch it as a `general-purpose` agent with the file body as its brief, honoring any `model` frontmatter; a command or skill — read the file and follow it inline. When the repo itself defines a same-named agent/command/skill, that one wins.\n')"$'\n\n'
    out="${out}- ${f}"$'\n'
  done < <(gt::overlay_claude_files "" "$dir")
  printf '%s' "$out"
}

run_session() {  # <topic> <about>
  local topic about="$2" dir repo label slug kf
  topic="$(gt::sanitize_label "$1")"
  dir="$(session_dir)"
  repo="$(basename "$(gt::main_root "$dir")")"
  label="[TALK] ${topic:-$repo Discussion}"
  slug="$(gt::slug_title "${topic:-discussion}")"
  local _tmp="${TMPDIR:-/tmp}"; kf="${_tmp%/}/${repo}-session-${slug:-discussion}.md"
  {
    printf 'Discussion session for `%s` in `%s` (no ticket). Topic: %s.\n' \
      "$repo" "$dir" "${topic:-open}"
    [ -n "$about" ] && printf '\n%s\n' "$about"
    if _doc="$(gt::find_doc kickoff-preamble.md "$dir")"; then
      local pre; pre="$(cat "${_doc%%$'\t'*}")"
      pre="$(subst "$pre" '{{ID}}' '')"
      pre="$(subst "$pre" '{{BRANCH}}' '')"
      pre="$(subst "$pre" '{{PARENT}}' '')"
      printf '\n%s\n' "$pre"
    fi
    printf '%s' "$(personal_assets_block "$dir")"
    printf '\n%s\n' "$(cat "$SCRIPT_DIR/session-kickoff.md")"
    printf '\nCosmetic, before your first reply: run `session-label.sh --color project` (skip if not found; silent outside a background session).\n'
  } > "$kf"
  printf 'dir=%s\nkickoff=%s\nlabel=%s\n' "$dir" "$kf" "$label"
  launch_session "$dir" "$kf" "$label"
}

# ---- args ------------------------------------------------------------------
id="" provider="" mode="full" launcher_flag="" tab_wt="" tab_kf="" about=""
while [ $# -gt 0 ]; do
  case "$1" in
    --provider) provider="${2:?--provider needs a value}"; shift 2 ;;
    --no-tab)   mode="no-tab"; shift ;;
    --print-title) mode="print-title"; shift ;;
    --session)  mode="session"; shift ;;
    --about)    about="${2:?--about needs a value}"; shift 2 ;;
    --tab-only) mode="tab-only"
                tab_wt="${2:?--tab-only needs <worktree> <kickoff>}"
                tab_kf="${3:?--tab-only needs <worktree> <kickoff>}"
                shift 3 ;;
    --launcher) launcher_flag="${2:?--launcher needs a value}"; shift 2 ;;
    -h|--help)  sed -n '2,/^$/p' "$0"; exit 0 ;;
    -*)         die "unknown flag: $1" ;;
    *)          id="$1"; shift ;;
  esac
done

# --tab-only runs from wherever the caller is: move into the worktree so the
# per-repo .start-ticket.conf resolves, after making the kickoff path absolute.
if [ "$mode" = "tab-only" ]; then
  tab_kf="$(cd "$(dirname "$tab_kf")" && pwd)/$(basename "$tab_kf")"
  cd "$tab_wt" || die "worktree not found: $tab_wt"
fi

launcher="$launcher_flag"
default_launcher=iterm
[ "$(uname)" = Darwin ] || default_launcher=none
[ -n "$launcher" ] || launcher="$(setting launcher START_TICKET_LAUNCHER "$default_launcher")"
case "$launcher" in
  iterm|bg|none) ;;
  *) die "unknown launcher '$launcher' (expected iterm, bg, or none)" ;;
esac

# shellcheck source=lib/telemetry.sh
. "$SCRIPT_DIR/lib/telemetry.sh"

# ticket.start (worktree + tracker) and session.launch (--tab-only), failures
# included. The id and scheme are passed explicitly because the ticket branch
# may not exist yet when this fires — but only once the provider is known:
# before that, guessing github would file the failure under a wrong run id.
wf_t0="" wf_event="" wf_dir="."
on_exit() {
  local rc=$? scheme=github
  [ -n "$wf_t0" ] || return 0
  [ "${provider:-}" = shortcut ] && scheme=shortcut
  wf::emit --dir "$wf_dir" "$wf_event" ${id:+${provider:+"ticket=$id" "scheme=$scheme"}} \
    "outcome=$([ "$rc" -eq 0 ] && echo ok || echo fail)" "exit_code=$rc" \
    "duration_ms=$(( $(wf::mono_ms) - wf_t0 ))" "mode=$mode" "launcher=$launcher" \
    "provider=${provider:-}" "ticket_in_progress=${ticket_in_progress:-}"
  return 0
}
trap on_exit EXIT
case "$mode" in
  full|no-tab) wf_t0="$(wf::mono_ms)" wf_event=ticket.start ;;
  tab-only)    wf_t0="$(wf::mono_ms)" wf_event=session.launch ;;
esac

if [ "$mode" = "tab-only" ]; then
  launch_session "$tab_wt" "$tab_kf"
  exit 0
fi

if [ "$mode" = "session" ]; then
  run_session "$id" "$about"
  exit 0
fi

[ -n "$id" ] || die "usage: start-ticket.sh <id> [--provider github|shortcut] [--no-tab|--print-title] [--launcher iterm|bg|none]"

# ---- repo + provider -----------------------------------------------------
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repo"
repo_root="$(git rev-parse --show-toplevel)"
_url="$(git remote get-url origin 2>/dev/null || true)"
if [ -n "$_url" ]; then repo_name="$(basename "${_url%.git}")"; else repo_name="$(basename "$repo_root")"; fi

[ -n "$provider" ] || provider="$(conf_get provider || true)"
if [ -z "$provider" ]; then
  if command -v gh >/dev/null && gh repo view >/dev/null 2>&1; then provider=github
  elif command -v short >/dev/null; then provider=shortcut
  else die "no ticket provider detected — set 'provider=' in .start-ticket.conf or pass --provider"
  fi
fi

pf="$(find_provider_file "$provider")"
[ -n "$pf" ] || die "no provider script for '$provider' (searched: START_TICKET_PROVIDER_DIR, <repo>/.project-overlays/start-ticket-providers, ~/.config/project-overlays/.start-ticket-providers, workflow-tools/start-ticket-providers)"
# shellcheck source=/dev/null
source "$pf"

WORKTREE_MANAGER="$(command -v worktree-manager.sh || echo "$SCRIPT_DIR/worktree-manager.sh")"
[ -x "$WORKTREE_MANAGER" ] || die "worktree-manager.sh not found / not executable"
export WORKTREE_MANAGER

provider::available || die "provider '$provider' unavailable (CLI missing or not authed)"

# ---- run ---------------------------------------------------------------
ST_TITLE="" ST_BODY="" ST_URL="" ST_PARENT="" ST_BRANCH="" ST_REF=""
provider::fetch "$id"
: "${ST_REF:=${provider} ticket ${id}}"
printf 'start-ticket: %s #%s — %s\n' "$provider" "$id" "${ST_TITLE:-?}" >&2

# --print-title: resolve the ticket and stop. Lets a caller that wants to supply
# its own label (GT_LABEL_OVERRIDE) read the title FIRST — the branch and the
# worktree dir are both named during create_worktree below, so an override
# decided afterwards would come too late for either of them. Read-only: no
# worktree, no state change, nothing marked in progress.
if [ "$mode" = "print-title" ]; then
  # proposed_slug is what the branch and worktree dir WILL be named: it ignores
  # GT_LABEL_OVERRIDE by design, so printing it here tells the caller the slug
  # is not theirs to choose (short of GT_LABEL_SLUG_OVERRIDE).
  printf 'title=%s\nproposed_label=%s\nproposed_slug=%s\n' \
    "$ST_TITLE" "$(gt::distill_title "$ST_TITLE")" "$(gt::slug_title "$ST_TITLE")"
  exit 0
fi

wt="$(provider::create_worktree "$id" | tail -1)"
[ -d "$wt" ] || die "worktree not created (got '$wt')"
branch="$(git -C "$wt" branch --show-current)"
wf_dir="$wt"

declare -f provider::post_worktree >/dev/null && provider::post_worktree "$id" "$wt"
provider::mark_in_progress "$id" || echo "start-ticket: WARN mark_in_progress failed" >&2

# mark_in_progress is best-effort and some tracker CLIs fail while exiting 0, so
# read the state back here rather than making the caller verify. ticket_state is
# what the tracker ACTUALLY reports; ticket_in_progress says whether that counts
# as started. ticket_in_progress=no means /start must repair it (Shortcut: via
# the MCP tools — its CLI's state-set is broken).
ticket_state="" ticket_in_progress="unknown"
if declare -f provider::read_state >/dev/null; then
  if ticket_state="$(provider::read_state "$id")"; then
    ticket_in_progress="yes"
  else
    ticket_in_progress="no"
  fi
fi

# ---- kickoff ---------------------------------------------------------
_tmp="${TMPDIR:-/tmp}"; kickoff="${_tmp%/}/${repo_name}-kickoff-${id}.md"
{
  printf 'Working on %s in this worktree. Branch `%s` is checked out.\n\n' \
    "$ST_REF" "$branch"
  printf '## %s — %s\n\n%s\n' "$id" "${ST_TITLE:-untitled}" "${ST_BODY:-(no description)}"
  [ -n "$ST_URL" ] && printf '\n<%s>\n' "$ST_URL"
  # The repo's own preamble wins outright; else the per-project overlay's.
  if _doc="$(gt::find_doc kickoff-preamble.md "$repo_root")"; then
    pre="${_doc%%$'\t'*}"
    printf '\n'
    _pre="$(cat "$pre")"
    _pre="$(subst "$_pre" '{{ID}}' "$id")"
    _pre="$(subst "$_pre" '{{BRANCH}}' "$branch")"
    _pre="$(subst "$_pre" '{{PARENT}}' "$ST_PARENT")"
    printf '%s\n' "$_pre"
  fi
  printf '%s' "$(personal_assets_block "$repo_root")"
  printf '\nCosmetic, after the plan is proposed: run `session-label.sh --color project` (skip if not found; silent outside a background session).\n'
} > "$kickoff"

# stdout: parseable by callers
printf 'worktree=%s\nkickoff=%s\nbranch=%s\nprovider=%s\n' "$wt" "$kickoff" "$branch" "$provider"
printf 'ticket_state=%s\nticket_in_progress=%s\nticket_parent=%s\n' \
  "$ticket_state" "$ticket_in_progress" "$ST_PARENT"
[ "$mode" = "no-tab" ] && exit 0
launch_session "$wt" "$kickoff"
