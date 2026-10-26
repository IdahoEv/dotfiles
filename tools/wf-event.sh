#!/usr/bin/env bash
# wf-event.sh — append one workflow telemetry event (see lib/telemetry.sh).
#
#   wf-event.sh [--dir <d>] <event> [key=value…]
#   wf-event.sh review.result round=2 fixed=3 dismissed=1 deferred=0 reviewers=correctness,robustness
#   wf-event.sh --hook        # Claude Code hook: reads the hook payload on stdin
#
# For hooks and prompts; scripts source lib/telemetry.sh directly. Always exits 0.

_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
# shellcheck source=lib/telemetry.sh
. "$SCRIPT_DIR/lib/telemetry.sh" || exit 0

# Session lifecycle from hook payloads. Only identifiers and Claude Code's own
# reason/type enums are kept; transcript paths are not logged — wf-report finds
# transcripts by session id.
hook() {
  [ "${WF_TELEMETRY:-1}" = "0" ] && return 0
  command -v jq >/dev/null || return 0
  local fields name sid cwd detail event key
  # detail is an enum-like token or "other", so a free-text error can't leak in.
  # \x1f, not tab: read collapses runs of whitespace IFS, shifting empty fields.
  fields="$(jq -r '[.hook_event_name, .session_id, .cwd,
                    (.source // .reason // .agent_type // .error)]
                   | map(. // "" | tostring | gsub("[\u001f\n]"; " ")) as [$n, $s, $c, $d]
                   | [$n, $s, $c,
                      (if $d == "" or ($d | test("^[A-Za-z0-9_.:-]{1,60}$")) then $d else "other" end)]
                   | join("\u001f")' 2>/dev/null)" || return 0
  IFS=$'\037' read -r name sid cwd detail <<<"$fields"
  case "$name" in
    SessionStart) event=session.start key=source ;;
    SessionEnd)   event=session.end   key=reason ;;
    StopFailure)  event=session.fail  key=error ;;
    SubagentStop) event=subagent.stop key=agent_type ;;
    *) return 0 ;;
  esac
  [ -d "$cwd" ] || cwd="."
  wf::emit --dir "$cwd" "$event" "session_id=$sid" "$key=$detail"
}

case "${1:-}" in
  -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
  --hook)    hook; exit 0 ;;
esac
wf::emit "$@"
exit 0
