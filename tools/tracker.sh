#!/usr/bin/env bash
# tracker.sh — read-only view of the ticket tracker through the provider seam.
#
#   tracker.sh list [--state open|closed|all] [--limit N] [--provider NAME]
#
# Prints {"truncated":bool,"issues":[{id,title,state,labels,url,updated,body}]}. truncated
# means more than --limit matched; callers that need the full set must abort on it.
# Provider: --provider → .start-ticket.conf `provider` → autodetect (gh, then short).
# Providers are the start-ticket-providers scripts; one that defines no
# provider::list_issues (or stubs it) makes this exit 2: report-only for the caller.
# Exit: 0 ok · 1 failure · 2 provider cannot list. No write subcommands exist.

set -euo pipefail

die() { printf 'tracker: %s\n' "$*" >&2; exit 1; }

_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
# shellcheck source=lib/repo-facts.sh
. "$SCRIPT_DIR/lib/repo-facts.sh"

# Same lookup order as start-ticket.sh's find_provider_file.
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

cmd="${1:-}"
[ "$cmd" = list ] || die "usage: tracker.sh list [--state open|closed|all] [--limit N] [--provider NAME]"
shift

state=open limit=500 provider=""
while [ $# -gt 0 ]; do
  case "$1" in
    --state)    state="${2:?--state needs a value}"; shift 2 ;;
    --limit)    limit="${2:?--limit needs a value}"; shift 2 ;;
    --provider) provider="${2:?--provider needs a value}"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done
case "$state" in open|closed|all) ;; *) die "--state must be open, closed or all" ;; esac
case "$limit" in ''|*[!0-9]*|0) die "--limit must be a positive integer" ;; esac

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repo"
command -v jq >/dev/null || die "jq is required"

[ -n "$provider" ] || provider="$(gt::conf_get provider || true)"
if [ -z "$provider" ]; then
  if command -v gh >/dev/null && gh repo view >/dev/null 2>&1; then provider=github
  elif command -v short >/dev/null; then provider=shortcut
  else die "no ticket provider detected — set 'provider=' in .start-ticket.conf or pass --provider"
  fi
fi

pf="$(find_provider_file "$provider")"
[ -n "$pf" ] || die "no provider script for '$provider'"
# shellcheck source=/dev/null
source "$pf"

provider::available || die "provider '$provider' unavailable (CLI missing or not authed)"
declare -F provider::list_issues >/dev/null || { echo "tracker: provider '$provider' cannot list issues" >&2; exit 2; }

# Ask for one extra so a full page is distinguishable from a cut-off one.
rc=0
raw="$(provider::list_issues "$state" "$((limit + 1))")" || rc=$?
[ "$rc" -ne 2 ] || exit 2
[ "$rc" -eq 0 ] || die "provider '$provider' failed to list issues"
jq -e --argjson l "$limit" '{truncated: (length > $l), issues: .[:$l]}' <<<"$raw" \
  || die "provider '$provider' returned malformed output"
