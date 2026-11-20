#!/usr/bin/env bash
# Two-line AGY CLI statusline mirroring ~/.claude/statusline.sh.
# Line 1: project/repo, git branch + status, agent state, review rounds.
# Line 2: model, context window bar, sandbox/subagent indicators.
input=$(cat)

US=$'\x1f'
IFS=$US read -r cwd model used_pct state sandbox tasks pr_num pr_state pr_url sid < <(
  printf '%s' "$input" | jq -r '[
    .workspace.current_dir // .current_dir // "",
    .model.display_name // "",
    (.context_window.used_percentage // 0 | floor),
    .agent_state // "",
    (if (.sandbox | type) == "object" and (.sandbox.enabled != null) then .sandbox.enabled else "" end),
    (.task_count // (if (.subagents | type) == "array" then (.subagents | length) elif (.subagents | type) == "number" then .subagents else "" end)),
    .pr.number // "", .pr.review_state // "", .pr.url // "",
    .session_id // ""
  ] | map(tostring | gsub("[[:cntrl:]]"; "")) | join("\u001f")' 2>/dev/null || printf '\x1f\x1f0\x1f\x1f\x1f\x1f\x1f\x1f\x1f'
)

cwd="${cwd:-$PWD}"
[[ "$used_pct" =~ ^[0-9]+$ ]] || used_pct=0

DIM=$'\e[38;2;140;140;140m'; RST=$'\e[0m'
GREEN=$'\e[38;2;55;133;4m'; AMBER=$'\e[38;2;169;116;0m'; RED=$'\e[38;2;200;50;50m'
BLUE=$'\e[38;2;0;135;175m'; ORANGE=$'\e[38;2;215;95;0m'
SEP="${DIM} | ${RST}"

join() {
  local out="" p
  for p in "$@"; do [ -n "$p" ] && out="${out:+$out$SEP}$p"; done
  printf '%s' "$out"
}

# ---- git facts ----------------------------------------------------------------
common=$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
project=""
[ -n "$common" ] && project=$(basename "$(dirname "$common")")

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
  branch_seg="${c}${branch:0:40}${RST}"
  [ "$ahead" -gt 0 ]     && branch_seg+=" ↑${ahead}"
  [ "$behind" -gt 0 ]    && branch_seg+=" ↓${behind}"
  [ "$modified" -gt 0 ]  && branch_seg+=" ${AMBER}~${modified}${RST}"
  [ "$untracked" -gt 0 ] && branch_seg+=" ${DIM}?${untracked}${RST}"
fi

project_seg=""; [ -n "$project" ] && project_seg="${BLUE}${project}${RST}"
short_path=$(printf '%s' "$cwd" | awk -F/ '{if (NF <= 4) {print $0} else {printf "~/…"; for (i=NF-1; i<=NF; i++) {if ($i != "") printf "/%s", $i}}}' | sed "s|^$HOME|~|")

state_seg=""
case "$state" in
  thinking|working|running) state_seg="${ORANGE}[${state}]${RST}" ;;
  error)                    state_seg="${RED}[${state}]${RST}" ;;
  "")                       ;;
  *)                        state_seg="${DIM}[${state}]${RST}" ;;
esac

pr_seg=""
if [ -n "$pr_num" ]; then
  pr_seg="PR #${pr_num}${pr_state:+ ${pr_state//_/ }}"
  [ -n "$pr_url" ] && pr_seg=$'\e]8;;'"${pr_url}"$'\a'"${pr_seg}"$'\e]8;;\a'
fi

# ---- review rounds ------------------------------------------------------------
rounds_seg=""
gitdir=$(git -C "$cwd" rev-parse --absolute-git-dir 2>/dev/null || true)
rounds_file="${gitdir:+$gitdir/local-review-rounds}"
if [ -n "$pr_num" ] || { [ -n "$rounds_file" ] && [ -f "$rounds_file" ]; }; then
  key=$(printf '%s' "${sid:-$gitdir}" | cksum | cut -d' ' -f1)
  cache="${TMPDIR:-/tmp}/agy-statusline-rounds-$key"
  if [ ! -f "$cache" ] || [ -n "$(find "$cache" -mmin +1 2>/dev/null)" ] || [ "$rounds_file" -nt "$cache" ]; then
    [ -n "$(find "$cache.lock" -maxdepth 0 -mmin +1 2>/dev/null)" ] && rmdir "$cache.lock" 2>/dev/null
    if mkdir "$cache.lock" 2>/dev/null; then
      ( trap 'rm -f "$cache.tmp"; rmdir "$cache.lock"' EXIT
        cd "$cwd" && ~/.claude/skills/github-review-procedure/github-review-state.sh --bare ${pr_num:+--pr "$pr_num"} \
          > "$cache.tmp" 2>/dev/null && mv "$cache.tmp" "$cache" || touch "$cache"
      ) </dev/null >/dev/null 2>&1 &
    fi
  fi
  rounds=$(cat "$cache" 2>/dev/null || true)
  [ -n "$rounds" ] && rounds_seg="reviews: ${rounds}"
fi

# ---- line 1 -------------------------------------------------------------------
if [ -n "$project_seg" ]; then
  line1=$(join "$project_seg" "$branch_seg" "$state_seg" "$pr_seg" "$rounds_seg")
else
  line1=$(join "${BLUE}${short_path}${RST}" "$branch_seg" "$state_seg" "$pr_seg" "$rounds_seg")
fi

# ---- line 2 -------------------------------------------------------------------
if   [ "$used_pct" -ge 90 ]; then bc=$RED
elif [ "$used_pct" -ge 70 ]; then bc=$AMBER
else bc=$GREEN; fi
filled=$((used_pct / 10)); [ "$filled" -gt 10 ] && filled=10
printf -v on '%*s' "$filled" ''; printf -v off '%*s' $((10 - filled)) ''
bar="${bc}${on// /█}${DIM}${off// /░}${RST} ${used_pct}%"

sandbox_seg=""
[ "$sandbox" = "false" ] && sandbox_seg="${AMBER}no-sandbox${RST}"

tasks_seg=""
[ -n "$tasks" ] && [ "$tasks" != "0" ] && tasks_seg="${DIM}tasks: ${tasks}${RST}"

line2=$(join "$model" "$bar" "$sandbox_seg" "$tasks_seg")

printf '%s\n%s' "$line1" "$line2"
