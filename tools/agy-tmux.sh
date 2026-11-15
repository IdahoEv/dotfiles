#!/usr/bin/env bash
# agy-tmux.sh — launch parallel /start workstreams in a tmux session with a live dashboard.
#
#   agy-tmux.sh [--session <name>] [--provider github|shortcut] [--no-attach] [<ticket-group> ...]
#
# Each <ticket-group> is a single ticket ID (183) or comma-separated chain (12,13).
# Runs `start-ticket.sh <group> --no-tab` for each, opens a tmux window running
# `agy --mode plan --prompt-interactive` with the generated kickoff, and opens a
# dashboard in window 0. Pressing Ctrl-z in any agent window returns to window 0.

set -euo pipefail

die() { printf 'agy-tmux: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: agy-tmux.sh [options] [<ticket-group> ...]

Options:
  --session <name>       Tmux session name (default: agy-<repo>)
  --provider <provider>  Forward --provider to start-ticket.sh (github|shortcut)
  --no-attach            Create/update the session without attaching
  -h, --help             Show this help

Examples:
  agy-tmux.sh 12,13 14 15
  agy-tmux.sh --session my-work 183
  agy-tmux.sh                  # re-attach to existing session
EOF
}

# ---- resolve script dir (following symlinks) -----------------------------
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"

START_TICKET_BIN="${AGY_TMUX_START_TICKET:-$SCRIPT_DIR/start-ticket.sh}"
WORKSTREAM_BIN="${AGY_TMUX_WORKSTREAM_BIN:-$SCRIPT_DIR/workstream.sh}"
AGY_BIN="${AGY_TMUX_AGY_BIN:-agy}"
TMUX_BIN="${AGY_TMUX_TMUX_BIN:-tmux}"
DASHBOARD_PY="$SCRIPT_DIR/lib/agy_tmux_dashboard.py"

tmux_cmd() {
  if [ -n "${AGY_TMUX_SOCKET:-}" ]; then
    "$TMUX_BIN" -L "$AGY_TMUX_SOCKET" "$@"
  else
    "$TMUX_BIN" "$@"
  fi
}

default_session_name() {
  local root=""
  if [ -f "$SCRIPT_DIR/lib/repo-facts.sh" ]; then
    # shellcheck source=lib/repo-facts.sh
    . "$SCRIPT_DIR/lib/repo-facts.sh"
    root="$(gt::main_root 2>/dev/null || true)"
  fi
  [ -n "$root" ] || root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  local name="agy"
  [ -n "$root" ] && name="agy-$(basename "$root")"
  # tmux forbids '.' and ':' in session names
  printf '%s' "${name//[.:]/-}"
}

attach_session() {
  [ "$no_attach" -eq 0 ] || return 0
  if [ -n "${TMUX:-}" ] && [ -z "${AGY_TMUX_SOCKET:-}" ]; then
    tmux_cmd switch-client -t "=$session:0"
  else
    exec env -u TMUX "$TMUX_BIN" ${AGY_TMUX_SOCKET:+-L "$AGY_TMUX_SOCKET"} attach-session -t "=$session:0"
  fi
}

is_dashboard_win0() {
  tmux_cmd list-windows -t "=$session" -F '#{window_index}:#{window_name}:#{@agy_dashboard_win}' 2>/dev/null \
    | grep -qx '0:dashboard:1'
}

install_cz_binding() {
  local existing_cz fallback_cmd
  existing_cz="$(tmux_cmd list-keys -T root 2>/dev/null | grep -E '[[:space:]]C-z[[:space:]]' || true)"
  if ! printf '%s' "$existing_cz" | grep -qF '@agy_dashboard'; then
    if [ -n "$existing_cz" ]; then
      tmux_cmd set-option -s @agy_prev_cz_bind "$existing_cz"
      fallback_cmd="$(printf '%s' "$existing_cz" | sed -E 's/^bind-key[[:space:]]+(-r[[:space:]]+)?-T[[:space:]]+root[[:space:]]+C-z[[:space:]]+//')"
      [ -n "$fallback_cmd" ] || fallback_cmd="send-keys C-z"
    else
      tmux_cmd set-option -su @agy_prev_cz_bind 2>/dev/null || true
      fallback_cmd="send-keys C-z"
    fi
    tmux_cmd bind-key -n C-z if-shell -F '#{==:#{@agy_dashboard},1}' 'select-window -t :0' "$fallback_cmd"
  fi

  local hook_sh
  hook_sh='if ! tmux list-sessions -F "#{@agy_dashboard}" 2>/dev/null | grep -qx 1; then prev=$(tmux show-options -sv @agy_prev_cz_bind 2>/dev/null || true); tmux unbind-key -n C-z 2>/dev/null || true; if [ -n "$prev" ]; then printf "%s\n" "$prev" | tmux source-file - 2>/dev/null || true; tmux set-option -su @agy_prev_cz_bind 2>/dev/null || true; fi; tmux set-hook -gu "session-closed[99]" 2>/dev/null || true; fi'
  tmux_cmd set-hook -g 'session-closed[99]' "run-shell '$hook_sh'"
}

ensure_session() {
  local dash_cmd
  dash_cmd="python3 -I $(printf '%q' "$DASHBOARD_PY") --session $(printf '%q' "$session") --tmux-bin $(printf '%q' "$TMUX_BIN")"
  if [ -n "${AGY_TMUX_SOCKET:-}" ]; then
    dash_cmd="$dash_cmd --socket $(printf '%q' "$AGY_TMUX_SOCKET")"
  fi

  local created_idx
  if ! tmux_cmd has-session -t "=$session" 2>/dev/null; then
    created_idx="$(tmux_cmd new-session -d -P -F '#{window_index}' -s "$session" -n "dashboard" "$dash_cmd")"
    tmux_cmd set-option -t "$session" base-index 0
    if [ "$created_idx" != "0" ]; then
      tmux_cmd move-window -s "=$session:$created_idx" -t "=$session:0"
    fi
    tmux_cmd set-window-option -t "=$session:0" @agy_dashboard_win 1
  elif ! is_dashboard_win0; then
    if tmux_cmd list-windows -t "=$session" -F '#{window_index}' 2>/dev/null | grep -qx '0'; then
      tmux_cmd move-window -s "=$session:0" -t "=$session:"
    fi
    created_idx="$(tmux_cmd new-window -d -P -F '#{window_index}' -t "=$session:" -n "dashboard" "$dash_cmd")"
    if [ "$created_idx" != "0" ]; then
      tmux_cmd move-window -s "=$session:$created_idx" -t "=$session:0"
    fi
    tmux_cmd set-window-option -t "=$session:0" @agy_dashboard_win 1
  fi

  tmux_cmd set-option -t "$session" @agy_dashboard 1
  install_cz_binding
}

session=""
provider=""
no_attach=0
groups=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --session)
      [ "$#" -ge 2 ] || die "--session requires a value"
      session="$2"; shift 2 ;;
    --provider)
      [ "$#" -ge 2 ] || die "--provider requires a value"
      provider="$2"; shift 2 ;;
    --no-attach)
      no_attach=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    --)
      shift; groups+=("$@"); break ;;
    -*)
      die "unknown option: $1" ;;
    *)
      groups+=("$1"); shift ;;
  esac
done

command -v "$TMUX_BIN" >/dev/null 2>&1 || die "tmux not found"
command -v python3 >/dev/null 2>&1 || die "python3 not found"
[ -f "$DASHBOARD_PY" ] || die "dashboard script not found at $DASHBOARD_PY"

[ -n "$session" ] || session="$(default_session_name)"
session="${session//[.:]/-}"

if [ "${#groups[@]}" -eq 0 ]; then
  if tmux_cmd has-session -t "=$session" 2>/dev/null; then
    ensure_session
    tmux_cmd select-window -t "=$session:0"
    attach_session
    exit 0
  fi
  usage >&2
  exit 1
fi

[ -x "$START_TICKET_BIN" ] || command -v "$START_TICKET_BIN" >/dev/null 2>&1 \
  || die "start-ticket.sh not found ($START_TICKET_BIN)"
command -v "$AGY_BIN" >/dev/null 2>&1 || die "agy CLI not found ($AGY_BIN)"

window_label_for() {  # <group> <branch> [<worktree>]
  local group="$1" branch="$2" wt="${3:-}"
  if [ -n "$wt" ] && [ -x "$WORKSTREAM_BIN" ]; then
    local key
    key="$("$WORKSTREAM_BIN" render key --dir "$wt" 2>/dev/null || true)"
    if [ -n "$key" ]; then
      printf '%s' "$key"
      return 0
    fi
  fi
  if [[ "$branch" =~ ^(sc-[0-9]+(\+[0-9]+)*|Is[0-9]+(\+[0-9]+)*)- ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  elif [ -n "$branch" ]; then
    printf '%s' "${branch%%-*}"
  else
    printf '%s' "${group//,/+}"
  fi
}

launch_group() {  # <group>
  local group="$1"
  local st_args=("$group" --no-tab)
  [ -z "$provider" ] || st_args+=(--provider "$provider")

  local out
  if ! out="$("$START_TICKET_BIN" "${st_args[@]}")"; then
    printf 'agy-tmux: start-ticket.sh failed for %s\n' "$group" >&2
    return 1
  fi

  local wt="" kf="" branch="" line=""
  while IFS= read -r line; do
    case "$line" in
      worktree=*) wt="${line#worktree=}" ;;
      kickoff=*)  kf="${line#kickoff=}" ;;
      branch=*)   branch="${line#branch=}" ;;
    esac
  done <<< "$out"

  if [ -z "$wt" ] || [ ! -d "$wt" ]; then
    printf 'agy-tmux: start-ticket.sh did not return a valid worktree for %s\n' "$group" >&2
    return 1
  fi
  if [ -z "$kf" ] || [ ! -f "$kf" ]; then
    printf 'agy-tmux: start-ticket.sh did not return a valid kickoff for %s\n' "$group" >&2
    return 1
  fi

  ensure_session

  local win_name agent_cmd win_idx
  win_name="$(window_label_for "$group" "$branch" "$wt")"
  agent_cmd="$(printf 'cd %q && exec %q --mode plan --prompt-interactive "$(cat %q)"' "$wt" "$AGY_BIN" "$kf")"

  win_idx="$(tmux_cmd new-window -d -P -F '#{window_index}' -t "=$session:" -n "$win_name" -c "$wt" "sleep 60")"
  tmux_cmd set-window-option -t "=$session:$win_idx" remain-on-exit on
  tmux_cmd respawn-pane -k -t "=$session:$win_idx" "$agent_cmd"
  printf 'agy-tmux: launched [%s] %s in %s (window %s)\n' "$win_name" "$branch" "$wt" "$win_idx"
}

launched=0
failed=0
for g in "${groups[@]}"; do
  if launch_group "$g"; then
    launched=$((launched + 1))
  else
    failed=1
  fi
done

if [ "$launched" -eq 0 ]; then
  exit 1
fi

tmux_cmd select-window -t "=$session:0"
attach_session
exit "$failed"
