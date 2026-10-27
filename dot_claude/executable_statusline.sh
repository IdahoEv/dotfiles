#!/usr/bin/env bash
# Two-line statusline. Line 1 is project/task info, line 2 is Claude info.
# The layout depends on the session's role, read from its title:
#   "<Project> Governor"      long-running: no phase
#   "[PHASE] <ticket label>"  ticket session (agent-phase.sh writes the prefix)
#   "Workflow"                like a ticket session; phase shown once one is set
#   anything else             plain session: directory and title
input=$(cat)

US=$'\x1f'
IFS=$US read -r cwd name model effort used_pct in_tok pr_num pr_state pr_url h5 d7 sid < <(
  printf '%s' "$input" | jq -r '[
    .workspace.current_dir // "", (.session_name // "" | gsub("[\n\r\u001f]"; " ")), .model.display_name // "",
    .effort.level // "", (.context_window.used_percentage // 0 | floor),
    .context_window.total_input_tokens // 0,
    .pr.number // "", .pr.review_state // "", .pr.url // "",
    (.rate_limits.five_hour.used_percentage // "" | if . == "" then "" else floor end),
    (.rate_limits.seven_day.used_percentage // "" | if . == "" then "" else floor end),
    .session_id // ""] | map(tostring) | join("\u001f")')

used_pct=${used_pct:-0}; in_tok=${in_tok:-0}

DIM=$'\e[38;2;140;140;140m'; RST=$'\e[0m'
GREEN=$'\e[38;2;55;133;4m'; AMBER=$'\e[38;2;169;116;0m'; RED=$'\e[38;2;200;50;50m'
BLUE=$'\e[38;2;0;135;175m'; ORANGE=$'\e[38;2;215;95;0m'
SEP="${DIM} | ${RST}"

join() {  # join the non-empty arguments with the separator
  local out="" p
  for p in "$@"; do [ -n "$p" ] && out="${out:+$out$SEP}$p"; done
  printf '%s' "$out"
}

# ---- git facts ----------------------------------------------------------------
common=$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
project=""
[ -n "$common" ] && project=$(basename "$(dirname "$common")")
# One status call: branch, ahead/behind upstream, modified and untracked counts.
branch="" ahead=0 behind=0 modified=0 untracked=0
while IFS= read -r l; do
  case "$l" in
    "# branch.head "*) branch="${l#\# branch.head }" ;;
    "# branch.ab "*)   read -r _ _ ahead behind <<<"$l"; ahead="${ahead#+}"; behind="${behind#-}" ;;
    "1 "*|"2 "*|"u "*) modified=$((modified + 1)) ;;
    "? "*)             untracked=$((untracked + 1)) ;;
  esac
done < <(git -C "$cwd" --no-optional-locks status --porcelain=v2 --branch 2>/dev/null)
branch_seg=""
if [ -n "$branch" ]; then
  if [ "$modified" -gt 0 ]; then c=$AMBER; else c=$GREEN; fi
  branch_seg="${c} ${branch:0:40}${RST}"
  [ "$ahead" -gt 0 ]     && branch_seg+=" ↑${ahead}"
  [ "$behind" -gt 0 ]    && branch_seg+=" ↓${behind}"
  [ "$modified" -gt 0 ]  && branch_seg+=" ${AMBER}~${modified}${RST}"
  [ "$untracked" -gt 0 ] && branch_seg+=" ${DIM}?${untracked}${RST}"
fi
project_seg=""; [ -n "$project" ] && project_seg="${BLUE}${project}${RST}"
short_path=$(printf '%s' "$cwd" | awk -F/ '{if (NF <= 4) {print $0} else {printf "~/…"; for (i=NF-1; i<=NF; i++) {if ($i != "") printf "/%s", $i}}}' | sed "s|^$HOME|~|")

# ---- role and phase from the title ---------------------------------------------
phase="" title="$name"
if [[ "$title" =~ ^\[(PLAN|WIP|REVIEW|REVIEWED|MERGED|DONE)\] ]]; then
  phase="${BASH_REMATCH[1]}"; title="${title#"${BASH_REMATCH[0]}"}"
fi
title="${title#\[PR\]}"; title="${title# }"
role=plain
case "$title" in
  *\ Governor) role=governor ;;
  Workflow)    role=workflow ;;
  *) [ -n "$phase" ] && role=ticket ;;
esac

# ---- PR (OSC 8 link; iTerm needs Cmd+Option+click while Claude Code has the mouse)
pr_seg=""
if [ -n "$pr_num" ]; then
  pr_seg="PR #${pr_num}${pr_state:+ ${pr_state//_/ }}"
  [ -n "$pr_url" ] && pr_seg=$'\e]8;;'"${pr_url}"$'\a'"${pr_seg}"$'\e]8;;\a'
fi

# ---- review rounds ---------------------------------------------------------------
# Rounds need GitHub calls (seconds), so refresh in the background and show the
# last result; a slow script would be cancelled by the next update. Local rounds
# come from the file github-review-state.sh --set-local writes, so a change there also
# triggers a refresh.
rounds_seg=""
gitdir=$(git -C "$cwd" rev-parse --absolute-git-dir 2>/dev/null)
rounds_file="$gitdir/local-review-rounds"
if [ -n "$pr_num" ] || [ -f "$rounds_file" ]; then
  key="${sid:-$(printf '%s' "$gitdir" | cksum | cut -d' ' -f1)}"
  cache="${TMPDIR:-/tmp}/statusline-rounds-$key"
  if [ ! -f "$cache" ] || [ -n "$(find "$cache" -mmin +1 2>/dev/null)" ] || [ "$rounds_file" -nt "$cache" ]; then
    # mkdir is an atomic lock; one older than a minute belongs to a dead refresh.
    [ -n "$(find "$cache.lock" -maxdepth 0 -mmin +1 2>/dev/null)" ] && rmdir "$cache.lock" 2>/dev/null
    if mkdir "$cache.lock" 2>/dev/null; then
      # On failure (offline, rate-limited) touch the cache so the retry waits out
      # the staleness window instead of firing on every render.
      ( trap 'rm -f "$cache.tmp"; rmdir "$cache.lock"' EXIT
        cd "$cwd" && ~/.claude/skills/github-review-procedure/github-review-state.sh --bare ${pr_num:+--pr "$pr_num"} \
          > "$cache.tmp" 2>/dev/null && mv "$cache.tmp" "$cache" || touch "$cache"
      ) </dev/null >/dev/null 2>&1 &
    fi
  fi
  rounds=$(cat "$cache" 2>/dev/null)
  [ -n "$rounds" ] && rounds_seg="reviews: ${rounds}"
fi

# ---- line 1 --------------------------------------------------------------------------
phase_seg=""; [ -n "$phase" ] && phase_seg="${ORANGE}[${phase}]${RST}"
case "$role" in
  governor) line1=$(join "$project_seg" "Governor" "$branch_seg" "$pr_seg" "$rounds_seg") ;;
  ticket|workflow)
            line1=$(join "$project_seg" "$branch_seg" "$phase_seg" "$pr_seg" "$rounds_seg") ;;
  *)        line1=$(join "${BLUE}${short_path}${RST}" "$branch_seg" "$title" "$pr_seg" "$rounds_seg") ;;
esac

# ---- line 2 --------------------------------------------------------------------------
if   [ "$used_pct" -ge 90 ]; then bc=$RED
elif [ "$used_pct" -ge 70 ]; then bc=$AMBER
else bc=$GREEN; fi
filled=$((used_pct / 10)); [ "$filled" -gt 10 ] && filled=10
printf -v on '%*s' "$filled" ''; printf -v off '%*s' $((10 - filled)) ''
bar="${bc}${on// /█}${DIM}${off// /░}${RST} ${used_pct}% ($(awk -v t="$in_tok" 'BEGIN{printf "%.0fk", t/1000}'))"

limit_seg() {  # <label> <pct>
  [ -z "$2" ] && return
  local c=$DIM; [ "$2" -ge 80 ] && c=$AMBER; [ "$2" -ge 95 ] && c=$RED
  printf '%s%s %s%%%s' "$c" "$1" "$2" "$RST"
}
limits=$(join "$(limit_seg 5h "$h5")" "$(limit_seg 7d "$d7")")

line2=$(join "$model" "${effort:+effort $effort}" "$bar" "$limits")

printf '%s\n%s' "$line1" "$line2"
