#!/usr/bin/env bash
# lib/telemetry.sh — append workflow events to a local JSONL log.
#
#   wf::emit [--dir <d>] <event> [key=value…]
#
# One JSON object per line at $WF_TELEMETRY_LOG (default
# ${XDG_STATE_HOME:-~/.local/state}/workflow-telemetry/events.jsonl); WF_TELEMETRY=0
# disables it. Events are keyed to a run (<owner/repo>#<ticket>) derived from the
# branch checked out in <d>; outside a ticket branch nothing is written.
#
# Never fails the caller: a missing jq or unwritable log warns on stderr and
# returns 0. Values are scalars capped at 200 chars so a line stays far below
# PIPE_BUF, which keeps concurrent O_APPEND writers from interleaving. Callers
# pass identifiers and counts only — never prompts, diffs, or command text.
#
# Sources repo-facts.sh; callers that already have it loaded pay nothing extra.

_wf_lib_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
declare -f gt::repo_key >/dev/null || . "$_wf_lib_dir/repo-facts.sh"

wf::log_path() {
  printf '%s' "${WF_TELEMETRY_LOG:-${XDG_STATE_HOME:-$HOME/.local/state}/workflow-telemetry/events.jsonl}"
}

# Wall clock for cross-process ordering. bash 3.2 has no $EPOCHREALTIME.
wf::ts() {
  perl -MTime::HiRes=time -MPOSIX=strftime -e \
    '$t = time; printf "%s.%03dZ", strftime("%Y-%m-%dT%H:%M:%S", gmtime($t)), ($t - int $t) * 1000' \
    2>/dev/null || date -u +%Y-%m-%dT%H:%M:%S.000Z
}

# Monotonic milliseconds, for durations measured inside one process.
wf::mono_ms() {
  perl -MTime::HiRes=clock_gettime,CLOCK_MONOTONIC -e \
    'printf "%d", clock_gettime(CLOCK_MONOTONIC) * 1000' 2>/dev/null \
    || printf '%s000' "$(date +%s)"
}

_wf_warned=""
_wf_warn() {
  [ -n "$_wf_warned" ] && return 0
  _wf_warned=1
  printf 'telemetry: %s; continuing without it\n' "$*" >&2
}

wf::emit() {
  [ "${WF_TELEMETRY:-1}" = "0" ] && return 0
  local dir="." event branch url repo log line
  if [ "${1:-}" = "--dir" ]; then dir="${2:-.}"; shift 2; fi
  event="${1:-}"; shift || true
  [ -n "$event" ] || return 0
  command -v jq >/dev/null || { _wf_warn "jq not found"; return 0; }

  branch="$(git -C "$dir" branch --show-current 2>/dev/null || true)"
  url="$(git -C "$dir" remote get-url origin 2>/dev/null || true)"
  repo="$(gt::repo_key "$url")"

  # A Shortcut story spans repos, so its run is the story; a GitHub issue
  # number is only unique within its repo. ticket=/scheme= override the branch
  # for events emitted before the ticket branch exists.
  line="$(jq -nc \
    --arg ts "$(wf::ts)" --arg event "$event" --arg branch "$branch" --arg repo "$repo" \
    --arg bticket "$(gt::ticket_from_branch "$branch")" --arg bscheme "$(gt::ticket_scheme "$branch")" \
    --arg session_id "${CLAUDE_CODE_SESSION_ID:-}" --arg job_id "$(basename "${CLAUDE_JOB_DIR:-}")" \
    --args '
    def coerce:
      explode | map(if . < 32 then 32 else . end) | implode
      | if test("^-?(0|[1-9][0-9]{0,15})$") then tonumber
        elif . == "true" then true elif . == "false" then false
        else .[:200] end;
    ([$ARGS.positional[:20][] | capture("^(?<k>[a-z_][a-z0-9_]{0,39})=(?<v>.*)$"; "p")
      | {(.k): (.v | coerce)}] | add // {}) as $x
    | (($x.ticket // $bticket) | tostring) as $ticket
    | ($x.scheme // (if $x.ticket then "github" else $bscheme end)) as $scheme
    | if $ticket == "" or ($scheme != "shortcut" and $repo == "") then empty else
        {v: 1, ts: $ts, event: $event,
         run_id: (if $scheme == "shortcut" then "sc-\($ticket)" else "\($repo)#\($ticket)" end),
         repo: $repo, ticket: $ticket, branch: $branch, session_id: $session_id, job_id: $job_id}
        + ($x | del(.v, .ts, .event, .run_id, .repo, .ticket, .scheme))
        | with_entries(select(.value != ""))
      end' "$@" 2>/dev/null)" || { _wf_warn "could not encode event '$event'"; return 0; }
  [ -n "$line" ] || return 0

  log="$(wf::log_path)"
  if ! { mkdir -p "$(dirname "$log")" && printf '%s\n' "$line" >> "$log"; } 2>/dev/null; then
    _wf_warn "cannot write $log"
  fi
  return 0
}
