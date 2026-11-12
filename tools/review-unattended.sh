#!/usr/bin/env bash
# review-unattended.sh — per-machine switch and round counter for the
# unattended GitHub review loop.
#
#   review-unattended.sh active       exit 0 when unattended mode applies
#   review-unattended.sh next-round   count a round; prints round=<n> (plus last=1 on the final round), exit 1 past the cap
#   review-unattended.sh reset        clear the round counter
#
# Unattended mode needs ~/.config/github-review-unattended and no
# ~/.config/local-review-only. REVIEW_UNATTENDED_MAX may lower the cap of 5, never raise it.

set -uo pipefail

die() { echo "review-unattended: $*" >&2; exit 2; }

max="${REVIEW_UNATTENDED_MAX:-5}"
case "$max" in ''|*[!0-9]*) max=5 ;; esac
if [ "$max" -gt 5 ]; then max=5; fi
if [ "$max" -lt 1 ]; then max=1; fi

active() {
  [ -e "$HOME/.config/github-review-unattended" ] && [ ! -e "$HOME/.config/local-review-only" ]
}

counter_file() {
  local gitdir
  gitdir="$(git rev-parse --absolute-git-dir 2>/dev/null)" || die "not in a git repository"
  echo "$gitdir/review-unattended-round"
}

case "${1:-}" in
  active) active ;;
  next-round)
    f="$(counter_file)" || exit 2
    n=$(( $(cat "$f" 2>/dev/null || echo 0) + 1 ))
    if [ "$n" -gt "$max" ]; then
      echo "cap=reached"
      exit 1
    fi
    echo "$n" > "$f" || die "cannot write round counter $f"
    if [ "$n" -eq "$max" ]; then echo "round=$n last=1"; else echo "round=$n"; fi
    ;;
  reset)
    f="$(counter_file)" || exit 2
    rm -f "$f"
    ;;
  *) die "usage: review-unattended.sh active|next-round|reset" ;;
esac
