#!/usr/bin/env bash
# review-unattended.sh — per-machine switch and round counter for the
# unattended GitHub review loop.
#
#   review-unattended.sh active       exit 0 when unattended mode applies
#   review-unattended.sh next-round [--max N]
#                                     count a round; prints round=<n> (plus last=1 on the final round), exit 1 past the cap
#   review-unattended.sh reset        clear the round counter
#
# Unattended mode needs ~/.config/github-review-unattended and no
# ~/.config/local-review-only. The round cap is the first valid positive
# integer of: --max N, $REVIEW_UNATTENDED_MAX, review_max_rounds in the
# project's .start-ticket.conf (or user config), else 5.

set -uo pipefail

die() { echo "review-unattended: $*" >&2; exit 2; }

positive_int() { case "$1" in ''|*[!0-9]*|0*) return 1 ;; *) return 0 ;; esac; }

resolve_max() {
  local v conf
  for v in "$1" "${REVIEW_UNATTENDED_MAX:-}"; do
    if positive_int "$v"; then echo "$v"; return; fi
  done
  conf="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/repo-facts.sh"
  # shellcheck source=lib/repo-facts.sh
  if [ -r "$conf" ]; then
    . "$conf"
    v="$(gt::conf_get review_max_rounds 2>/dev/null || true)"
    if positive_int "$v"; then echo "$v"; return; fi
  fi
  echo 5
}

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
    cli_max=""
    if [ "${2:-}" = "--max" ]; then cli_max="${3:-}"; positive_int "$cli_max" || die "--max needs a positive integer"; fi
    max="$(resolve_max "$cli_max")"
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
