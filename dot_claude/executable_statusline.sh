#!/usr/bin/env bash
input=$(cat)

cwd=$(printf '%s' "$input" | jq -r '.workspace.current_dir')
used_pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // 0')
in_tok=$(printf '%s' "$input" | jq -r '.context_window.total_input_tokens // 0')
user=$(whoami)

short_path=$(printf '%s' "$cwd" | awk -F/ '{if (NF <= 4) {print $0} else {printf "~/…"; for (i=NF-1; i<=NF; i++) {if ($i != "") printf "/%s", $i}}}' | sed "s|^$HOME|~|")

git_info=""
if git -C "$cwd" rev-parse --git-dir > /dev/null 2>&1; then
  branch=$(git -C "$cwd" --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null | head -c 25)
  if ! git -C "$cwd" --no-optional-locks diff --quiet 2>/dev/null; then
    git_color="\033[38;2;169;116;0m"
  else
    git_color="\033[38;2;55;133;4m"
  fi
  git_info=" ${git_color} ${branch}\033[0m"
fi

in_tok_k=$(awk -v t="$in_tok" 'BEGIN{printf "%.0fk", t/1000}')

printf "\033[38;2;215;95;0m \033[0m"
printf "\033[38;2;78;78;78m ${user}\033[0m"
printf "\033[38;2;0;135;175m ${short_path}\033[0m"
printf "${git_info}"
printf "\033[38;2;140;140;140m · ctx ${in_tok_k} (${used_pct}%%)\033[0m"
