#!/usr/bin/env bash
# lib/repo-facts.sh — shared, read-only facts about a repo/branch.
#
# Sourced by open-pr.sh, sibling-worktrees.sh, finalize-check.sh, start-ticket.sh
# and worktree-manager.sh so the conventions below live in exactly one place.
# These were previously restated in prose inside .claude/commands/*.md, which
# meant the model re-derived them (and re-ran the probe commands) on every
# invocation.
#
# start-ticket.sh and worktree-manager.sh use only gt::distill_title /
# gt::slug_title — they resolve a ticket id from their argument and a branch
# from the provider, so the branch/default-branch helpers are of no use to them.
#
# Everything here is pure inspection: no network beyond the host CLI fallback
# in gt::default_branch, no writes, no side effects.

# ---- default branch ---------------------------------------------------------
# Resolve origin's default branch name (NOT prefixed with "origin/"). Never
# assume main/master — `development` is common in these repos.
#
# Order: refs/remotes/origin/HEAD (local, instant) → `git remote show origin`
# (network, host-neutral) → the host CLI (GitHub only). Prints nothing and
# returns 1 if none of them answer, so callers can decide whether to ask.
gt::default_branch() {  # [<dir>] → <branch>, or nothing + rc 1
  local dir="${1:-.}" b

  b="$(git -C "$dir" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  b="${b#origin/}"
  if [ -n "$b" ]; then printf '%s' "$b"; return 0; fi

  b="$(git -C "$dir" remote show origin 2>/dev/null \
       | sed -n 's/.*HEAD branch: //p' | head -1)"
  if [ -n "$b" ] && [ "$b" != "(unknown)" ]; then printf '%s' "$b"; return 0; fi

  if command -v gh >/dev/null; then
    b="$(git -C "$dir" rev-parse --show-toplevel >/dev/null 2>&1 \
         && cd "$dir" && gh repo view --json defaultBranchRef \
              -q .defaultBranchRef.name 2>/dev/null || true)"
    if [ -n "$b" ]; then printf '%s' "$b"; return 0; fi
  fi

  return 1
}

# Same, but as a verified remote ref (refs/remotes/origin/<base>), falling back
# to probing the usual names. Used where the caller needs a ref that definitely
# resolves rather than just a name.
#
# LOCAL-ONLY by design: reads refs/remotes/origin/HEAD and probes existing
# remote refs, never `git remote show origin` or a host CLI. sibling-worktrees.sh
# runs this speculatively on every ship and documents that it makes no network
# calls — keep it that way. Staleness here only ever over-reports work.
gt::default_branch_ref() {  # [<dir>] → origin/<branch>, or nothing + rc 1
  local dir="${1:-.}" b
  b="$(git -C "$dir" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  b="${b#origin/}"
  if [ -n "$b" ] && git -C "$dir" rev-parse --verify --quiet "origin/$b" >/dev/null; then
    printf 'origin/%s' "$b"; return 0
  fi
  for b in development main master; do
    if git -C "$dir" rev-parse --verify --quiet "origin/$b" >/dev/null; then
      printf 'origin/%s' "$b"; return 0
    fi
  done
  return 1
}

# ---- ticket id from branch --------------------------------------------------
# The two branch conventions worktree-manager.sh creates:
#   <id>-<slug>                GitHub issues (default)
#   [<prefix>/]sc-<id>/<slug>  Shortcut      (--sc)
# Shortcut is matched first: an sc- id is unambiguous, while the GitHub form is
# just "leading digits" and would also match a branch like "2-sc-5/foo". The
# LAST sc-<id> wins — a follow-up branch can name several — matching
# open-pr-providers' provider::issue_from_branch.
gt::ticket_from_branch() {  # <branch> → id, or nothing
  local b="$1"
  if [[ "$b" =~ .*sc-([0-9]+) ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  elif [[ "$b" =~ ^([1-9][0-9]*)- ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  fi
  return 0
}

# Which dialect the branch uses, so callers can label a ticket ref correctly
# without re-parsing. Prints shortcut | github | unknown.
gt::ticket_scheme() {  # <branch> → shortcut | github | unknown
  local b="$1"
  if   [[ "$b" =~ .*sc-[0-9]+ ]];  then printf 'shortcut'
  elif [[ "$b" =~ ^[1-9][0-9]*- ]]; then printf 'github'
  else printf 'unknown'
  fi
}

# ---- ticket title → short label ---------------------------------------------
# Distill a ticket title down to the few words that actually identify the work,
# for agent-view session names, branch slugs, and worktree directory names.
#
# The problem this solves: a tracker slug is already lossy. Shortcut turns
# "[A/L] Decide PERS data deletion & retention policy (member deletion, ...)"
# into "-a-l--decide-pers-data-deletio", and anything that then truncates THAT
# is truncating a truncation — the reader is left with "a l decide pers data
# deletio", whose only informative word is cut in half. Distilling from the
# title instead keeps the words that distinguish one ticket from another.
#
# The rules, in order, and why each one earns its place:
#   1. Leading [bracketed] tags — track/project markers ([A], [A/L], [ops],
#      [PERS]) that are constant across many tickets, so they never
#      discriminate between two rows in a list.
#   2. (Parentheticals) — in these trackers they elaborate, and the title
#      already stands without them.
#   3. Stopwords and project noise. GT_LABEL_NOISE is the per-repo part: the
#      project's own name is pure overhead in a list where every row shares it.
#   4. A leading activity verb (Design/Decide/Build), but only when something
#      survives it — "what" discriminates better than "how" when the budget is
#      four words, and most tickets in a backlog are Design or Build.
#   5. Keep the LAST n words, not the first. English puts the head of a noun
#      phrase at the end: "unified rewards representation" degrades to
#      "rewards representation", which is still the subject, whereas keeping
#      the front gives "design unified" — the generic half.
#
# Acronyms (APM, ADR, SQL) keep their case; everything else is Title Cased, so
# the result reads as a name rather than a sentence fragment.
#
# Tunable via environment, since the noise list is the only genuinely
# repo-specific part: GT_LABEL_WORDS (default 4), GT_LABEL_NOISE.
GT_LABEL_STOPWORDS=" a an the to for of in on and or with into from at by be is are as that this it "
GT_LABEL_VERBS=" add build create decide define design document enable fix implement investigate make migrate port refactor remove survey update write "

gt::distill_title() {  # <title> [<max-words>] → "Short Label Words"
  local title="$1" maxw="${2:-${GT_LABEL_WORDS:-4}}" w lw i n start
  local noise=" ${GT_LABEL_NOISE:-} "
  local -a kept=() out=()

  # Repeatedly, so "[A] [ops] Thing" loses both tags.
  while [[ "$title" =~ ^[[:space:]]*\[[^]]*\](.*)$ ]]; do title="${BASH_REMATCH[1]}"; done
  title="$(printf '%s' "$title" | sed 's/([^)]*)//g')"
  # Everything outside ASCII alphanumerics becomes a separator: this handles em
  # dashes, ampersands, slashes, dots and snake_case uniformly, so
  # "context_snapshot" and "dd-trace" split into words rather than surviving as
  # punctuation.
  #
  # LC_ALL=C with an explicit A-Za-z0-9 range, NOT '[:alnum:]', because the
  # class is locale-dependent and the result reaches a git ref: under a UTF-8
  # locale "naïve" passes through into a branch name, while under LC_ALL=C each
  # byte of a multibyte character is itself a separator, so "Café" becomes
  # "Caf" — the half-word defect this change exists to remove. A cron caller
  # typically has C and an interactive shell UTF-8, so without pinning it one
  # ticket gets two different names depending on who ran the tool.
  title="$(printf '%s' "$title" | LC_ALL=C tr -c 'A-Za-z0-9' ' ')"

  for w in $title; do
    lw="$(printf '%s' "$w" | tr '[:upper:]' '[:lower:]')"
    [[ "$GT_LABEL_STOPWORDS" == *" $lw "* ]] && continue
    [[ "$noise"             == *" $lw "* ]] && continue
    kept+=("$w")
  done

  if [ "${#kept[@]}" -gt 1 ]; then
    lw="$(printf '%s' "${kept[0]}" | tr '[:upper:]' '[:lower:]')"
    [[ "$GT_LABEL_VERBS" == *" $lw "* ]] && kept=("${kept[@]:1}")
  fi

  n=${#kept[@]}
  [ "$n" -eq 0 ] && return 0
  # Clamp: maxw <= 0 (GT_LABEL_WORDS=0, a negative, or an explicit 0 argument)
  # would leave `out` empty, and on bash 3.2 — which is what /usr/bin/env bash
  # is on macOS — "${out[*]}" on an empty array is an unbound-variable error
  # under `set -u`, aborting the CALLER rather than just producing a bad label.
  # Bash >= 4.4 relaxed that rule, so this does not reproduce under 5.x.
  [ "$maxw" -ge 1 ] 2>/dev/null || maxw=1
  start=$(( n > maxw ? n - maxw : 0 ))
  for ((i = start; i < n; i++)); do
    w="${kept[i]}"
    if [[ "$w" =~ ^[A-Z0-9]{2,}$ ]]; then
      out+=("$w")
    else
      out+=("$(printf '%s' "${w:0:1}" | tr '[:lower:]' '[:upper:]')${w:1}")
    fi
  done
  printf '%s' "${out[*]:-}"
}

# The same distillation, lowercased and hyphenated for a git branch segment or
# a directory name. Branch slugs get a wider budget than display labels: a
# branch name is read deliberately rather than scanned, and `git branch` output
# has no width pressure.
#
# DELIBERATELY ignores $GT_LABEL_OVERRIDE — it calls gt::distill_title, not
# gt::label_from_title. A branch name and a worktree directory are matched
# against later (find_ticket_branch, find_existing_worktree, an open PR, the
# user's shell history), so a name that varies between two runs of the same
# ticket is a defect, not a nicety. The display label has no such constraint:
# nothing matches on it and agent-phase.sh rewrites it every phase change, so
# that is where a caller's judgment is allowed to win. $GT_LABEL_SLUG_OVERRIDE
# exists for a caller that genuinely means to name the branch too.
gt::slug_title() {  # <title> [<max-words>] → "short-label-words"
  local d
  if [ -n "${GT_LABEL_SLUG_OVERRIDE:-}" ]; then
    d="$(gt::sanitize_label "$GT_LABEL_SLUG_OVERRIDE")"
  fi
  [ -n "${d:-}" ] || d="$(gt::distill_title "$1" "${2:-${GT_LABEL_SLUG_WORDS:-5}}")"
  [ -n "$d" ] || return 0
  printf '%s' "$d" | tr '[:upper:]' '[:lower:]' | tr ' ' '-'
}

# ---- caller-supplied label override -----------------------------------------
# gt::distill_title deletes and slices; it never reorders, substitutes, or
# recognizes that two words mean the same thing. That handles the common
# "<verb> <modifier> <head noun>" title shape at zero cost and zero variance,
# and visibly degrades when the subject sits at the FRONT: "Rewards structures
# are wrong in the legacy mapping layer" loses "Rewards", and "Investigate why
# the planner drops subjects" loses "planner".
#
# A model reading the title gets those right. So a caller that has already read
# the title with judgment available — /start, which is a Claude session — may
# hand in a label directly via $GT_LABEL_OVERRIDE, and the distiller becomes the
# fallback for everyone else (`wm --sc` straight from a shell, a cron job, any
# non-Claude caller). An unset, empty, or unusable override silently falls back
# to it.
#
# The override reaches the DISPLAY LABEL only. Branch slugs and worktree
# directory names stay deterministic — see gt::slug_title for why, and
# $GT_LABEL_SLUG_OVERRIDE for the escape hatch. The split is the point: the
# label is what a human scans in the agent view and nothing matches on it, so
# judgment is free there; a branch name is matched against and must be
# reproducible from the ticket id alone.
#
# The override reaches a BRANCH NAME, so it is sanitized rather than trusted:
# word characters and spaces only, collapsed, trimmed, length-capped. A caller
# that sends punctuation, a path separator, or a 200-character sentence gets the
# cleaned version or, if nothing usable survives, the distilled title.
# Default only; the value is re-validated at the point of use (see
# gt::sanitize_label), because a caller can set or change it after this file is
# sourced and a bad value must not reach the `[ -gt ]` test there.
GT_LABEL_MAX_CHARS="${GT_LABEL_MAX_CHARS:-48}"

gt::sanitize_label() {  # <text> → "Safe Label Words", or nothing
  local s="$1"
  # A caller's IFS must not change what this function considers a word: with
  # IFS=, the split below stops splitting on spaces AND "$*" re-joins with a
  # comma, so "  Rewards/Structures  " kept its padding and emerged as
  # "--rewards-structures--" — a leading dash in a branch name and a directory
  # name. Scoped to the function; the caller's IFS is untouched.
  local IFS=$' \t\n'
  # Anything outside ASCII alphanumerics becomes a space, matching
  # gt::distill_title exactly (same LC_ALL=C reasoning as there), so an
  # override and a distilled title can't produce two different character sets
  # in a branch name.
  s="$(printf '%s' "$s" | LC_ALL=C tr -c 'A-Za-z0-9' ' ')"
  # Collapse runs of spaces and trim, via word splitting on the IFS set above.
  # shellcheck disable=SC2086
  set -- $s
  [ "$#" -gt 0 ] || return 0
  s="$*"
  # Validated here rather than at source time: a caller may set or change this
  # after the lib is sourced. A non-numeric value made `[ -gt ]` exit 2, which
  # `if` reads as false — silently skipping the cap entirely and passing an
  # arbitrarily long override into a branch name.
  local maxc="$GT_LABEL_MAX_CHARS"
  [[ "$maxc" =~ ^[1-9][0-9]*$ ]] || maxc=48
  if [ "${#s}" -gt "$maxc" ]; then
    # Cut on a word boundary, never mid-word — a half-word is the exact defect
    # this whole change exists to remove.
    while [ "${#s}" -gt "$maxc" ] && [[ "$s" == *" "* ]]; do
      s="${s% *}"
    done
    [ "${#s}" -le "$maxc" ] || return 0
  fi
  printf '%s' "$s"
}

# The function every consumer should call: override if usable, else distill.
gt::label_from_title() {  # <title> [<max-words>] → "Short Label Words"
  local o
  if [ -n "${GT_LABEL_OVERRIDE:-}" ]; then
    o="$(gt::sanitize_label "$GT_LABEL_OVERRIDE")"
    if [ -n "$o" ]; then printf '%s' "$o"; return 0; fi
  fi
  gt::distill_title "$1" "${2:-}"
}

# ---- per-project config -----------------------------------------------------
# Config that belongs to ONE project but can't live in its repo (the author isn't
# its owner, or it names things that must not reach a public remote) sits in a
# per-machine overlay keyed by the origin remote:
#
#   $GIT_TOOLS_PROJECTS_DIR (default ~/.config/git-tools/projects)/<owner>/<repo>/
#
# Keyed by remote rather than checkout path, so every worktree of a repo — and a
# fresh clone — resolves the same directory with nothing copied into it. The
# projects root may itself be a git repo (project-config.sh store-init) pointed
# at a remote that is private enough for the config.
gt::projects_root() {
  printf '%s' "${GIT_TOOLS_PROJECTS_DIR:-$HOME/.config/git-tools/projects}"
}

# <owner>/<repo> from an origin URL: ssh (git@host:o/r.git), scp-less ssh://,
# and https forms, with a trailing .git stripped. Nothing for an unparseable URL.
gt::repo_key() {  # <url> → "owner/repo", or nothing
  local u="${1%/}" path
  u="${u%.git}"
  case "$u" in
    *://*) path="${u#*://}"; path="${path#*/}" ;;   # drop scheme and host
    *:*)   path="${u#*:}" ;;                        # scp-style: host:owner/repo
    *)     return 0 ;;
  esac
  [[ "$path" =~ ^([^/]+)/([^/]+)$ ]] || return 0
  printf '%s/%s' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
}

# Overlay directory for the repo containing <dir>; nothing without an origin.
# The directory itself may not exist yet — callers test for the files they want.
gt::overlay_dir() {  # [<dir>] → path, or nothing
  local url key
  url="$(git -C "${1:-.}" remote get-url origin 2>/dev/null || true)"
  [ -n "$url" ] || return 0
  key="$(gt::repo_key "$url")"
  [ -n "$key" ] || return 0
  printf '%s/%s' "$(gt::projects_root)" "$key"
}

# The main checkout's root, even from a linked worktree. Nothing outside a repo.
gt::main_root() {  # [<dir>] → path
  local common
  common="$(git -C "${1:-.}" rev-parse --git-common-dir 2>/dev/null || true)"
  [ -n "$common" ] || return 0
  [ "${common#/}" = "$common" ] && common="${1:-.}/$common"
  common="$(cd -P "$common" 2>/dev/null && pwd)" || return 0
  dirname "$common"
}

# Config files for the repo containing <dir>, highest precedence first:
#   <toplevel>/.start-ticket.conf, <main-root>/.start-ticket.conf,
#   <overlay>/start-ticket.conf, ~/.config/start-ticket/config
gt::conf_files() {  # [<dir>] → one path per line
  local dir="${1:-.}" top main ov
  top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null || true)"
  main="$(gt::main_root "$dir")"
  ov="$(gt::overlay_dir "$dir")"
  [ -n "$top" ]  && printf '%s\n' "$top/.start-ticket.conf"
  [ -n "$main" ] && printf '%s\n' "$main/.start-ticket.conf"
  [ -n "$ov" ]   && printf '%s\n' "$ov/start-ticket.conf"
  printf '%s\n' "$HOME/.config/start-ticket/config"
}

# First non-empty `key=` across gt::conf_files: per key, a committed repo file
# beats the overlay, which beats the machine-wide file. rc 1 when unset.
gt::conf_get() {  # <key> [<dir>] → value
  local key="$1" f v
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    v="$(sed -n "s/^${key}=//p" "$f" | head -1)"
    [ -n "$v" ] && { printf '%s' "$v"; return 0; }
  done < <(gt::conf_files "${2:-.}")
  return 1
}

# Whole-file docs (governor.md, kickoff-preamble.md): the repo's .claude/<name>
# if present, else the overlay's <name>. No merging — a committed file replaces
# the overlay's outright. Prints "<path><TAB><repo|overlay>"; rc 1 if neither.
gt::find_doc() {  # <name> [<dir>] → "path\tsource"
  local name="$1" dir="${2:-.}" top ov
  top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -n "$top" ] && [ -f "$top/.claude/$name" ]; then
    printf '%s\trepo' "$top/.claude/$name"; return 0
  fi
  ov="$(gt::overlay_dir "$dir")"
  if [ -n "$ov" ] && [ -f "$ov/$name" ]; then
    printf '%s\toverlay' "$ov/$name"; return 0
  fi
  return 1
}
