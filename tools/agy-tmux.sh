#!/usr/bin/env bash
# agy-tmux.sh — launch parallel /start workstreams in a tmux session with a live dashboard.
#
#   agy-tmux.sh [--session <name>] [--provider github|shortcut] [--no-attach] [<ticket-group> ...]
#   agy-tmux.sh --window <worktree> <kickoff> [--session <name>]
#
# Each <ticket-group> is a single ticket ID (183) or comma-separated chain (12,13).
# Runs `start-ticket.sh <group> --no-tab` for each, opens a tmux window running
# `agy --mode plan --prompt-interactive` with the generated kickoff, and opens a
# dashboard in window 0. Pressing Ctrl-z in any agent window returns to window 0.
# --window appends a single agent window for an existing worktree + kickoff
# without stealing focus from the caller window.

set -euo pipefail

die() { printf 'agy-tmux: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: agy-tmux.sh [options] [<ticket-group> ...]
       agy-tmux.sh --window <worktree> <kickoff> [--session <name>]

Options:
  --session <name>       Tmux session name (default: active @agy_dashboard session or agy-<repo>)
  --provider <provider>  Forward --provider to start-ticket.sh (github|shortcut)
  --window <wt> <kf>     Open one agent window for an existing worktree + kickoff without stealing focus
  --no-attach            Create/update the session without attaching
  --force                Launch even if mem-guard blocks on memory pressure
  -h, --help             Show this help

Examples:
  agy-tmux.sh 12,13 14 15
  agy-tmux.sh --session my-work 183
  agy-tmux.sh                  # attach to existing session, or launch governor if none exists
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
MEM_GUARD_BIN="${AGY_TMUX_MEM_GUARD:-$SCRIPT_DIR/mem-guard.sh}"

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

active_dashboard_session() {
  [ -n "${TMUX:-}" ] || return 1
  local info=""
  info="$(tmux_cmd display-message ${TMUX_PANE:+-t "$TMUX_PANE"} -p '#{@agy_dashboard}:#{session_name}' 2>/dev/null || true)"
  case "$info" in
    1:*) printf '%s' "${info#1:}"; return 0 ;;
    *)   return 1 ;;
  esac
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
  # Optional memory column: the dashboard only sees this command's JSON, nothing else.
  if [ -x "$MEM_GUARD_BIN" ] || command -v "$MEM_GUARD_BIN" >/dev/null 2>&1; then
    local mem_cmd
    mem_cmd="$(printf '%q' "$MEM_GUARD_BIN") report --json --session $(printf '%q' "$session") --tmux-bin $(printf '%q' "$TMUX_BIN")"
    [ -z "${AGY_TMUX_SOCKET:-}" ] || mem_cmd="$mem_cmd --socket $(printf '%q' "$AGY_TMUX_SOCKET")"
    dash_cmd="$dash_cmd --mem-cmd $(printf '%q' "$mem_cmd")"
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

# The override applies to this invocation's guard checks only. Capture it, then drop it from
# the environment so the tmux server, the agent panes and any /start they run never inherit it.
force_override="${MEM_GUARD_OVERRIDE:-}"
unset MEM_GUARD_OVERRIDE
session=""
provider=""
no_attach=0
window_wt=""
window_kf=""
groups=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --session)
      [ "$#" -ge 2 ] || die "--session requires a value"
      session="$2"; shift 2 ;;
    --provider)
      [ "$#" -ge 2 ] || die "--provider requires a value"
      provider="$2"; shift 2 ;;
    --window)
      [ "$#" -ge 3 ] || die "--window requires <worktree> <kickoff>"
      window_wt="$2"; window_kf="$3"; shift 3 ;;
    --no-attach)
      no_attach=1; shift ;;
    --force)
      force_override=1; shift ;;
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

if [ -n "$window_wt" ]; then
  [ "${#groups[@]}" -eq 0 ] || die "--window cannot be combined with ticket groups"
  [ -n "$session" ] || session="$(active_dashboard_session || default_session_name)"
else
  [ -n "$session" ] || session="$(default_session_name)"
fi
session="${session//[.:]/-}"

main_worktree_dir() {
  local config_root=""
  config_root="$(git config --get worktreeManager.configRoot 2>/dev/null || true)"
  if [ -n "$config_root" ] && [ -d "$config_root" ]; then
    printf '%s' "$config_root"
    return 0
  fi

  local wt=""
  wt="$(git worktree list --porcelain 2>/dev/null | awk '
    function flush() {
      if (path == "" || bare || prunable) return
      if (first == "") first = path
      if (primary == "" && (branch == "refs/heads/main" || branch == "refs/heads/master" || branch == "refs/heads/development")) primary = path
    }
    /^worktree / { flush(); path = substr($0, 10); bare = 0; prunable = 0; branch = "" }
    /^bare$/ { bare = 1 }
    /^prunable/ { prunable = 1 }
    /^branch / { branch = substr($0, 8) }
    END { flush(); print (primary != "" ? primary : first) }
  ' || true)"
  if [ -n "$wt" ] && [ -d "$wt" ]; then
    printf '%s' "$wt"
    return 0
  fi

  local top=""
  top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -n "$top" ] && [ -d "$top" ]; then
    printf '%s' "$top"
    return 0
  fi

  pwd
}

check_mem_guard() {  # <label>
  local label="$1"
  # Each launched agent changes memory pressure. Blocked launches are skipped
  # (not killed, nothing created); --force / MEM_GUARD_OVERRIDE=1 overrides.
  if [ -x "$MEM_GUARD_BIN" ] || command -v "$MEM_GUARD_BIN" >/dev/null 2>&1; then
    local grc=0
    MEM_GUARD_OVERRIDE="$force_override" "$MEM_GUARD_BIN" check --context "agy-tmux $label" || grc=$?
    case "$grc" in
      0) ;;
      3) printf 'agy-tmux: skipped %s: blocked by mem-guard (override with --force)\n' "$label" >&2
         return 1 ;;
      *) printf 'agy-tmux: mem-guard failed (exit %s); launching without a memory check\n' "$grc" >&2 ;;
    esac
  else
    printf 'agy-tmux: mem-guard.sh not found (%s); launching without a memory check\n' "$MEM_GUARD_BIN" >&2
  fi
}

open_agent_window() {  # <win_name> <dir> <agent_cmd> -> prints window index
  local win_name="$1" dir="$2" agent_cmd="$3" win_idx
  win_idx="$(tmux_cmd new-window -d -P -F '#{window_index}' -t "=$session:" -n "$win_name" -c "$dir" "sleep 60")"
  tmux_cmd set-window-option -t "=$session:$win_idx" remain-on-exit on
  tmux_cmd respawn-pane -k -t "=$session:$win_idx" "$agent_cmd"
  printf '%s' "$win_idx"
}

launch_governor() {
  command -v "$AGY_BIN" >/dev/null 2>&1 || die "agy CLI not found ($AGY_BIN)"
  check_mem_guard "governor" || return 1

  local gov_dir agent_cmd win_idx
  gov_dir="$(main_worktree_dir)"
  ensure_session

  agent_cmd="$(printf 'cd %q && exec %q --mode plan --prompt-interactive %q' "$gov_dir" "$AGY_BIN" "/governor")"
  win_idx="$(open_agent_window "governor" "$gov_dir" "$agent_cmd")"
  printf 'agy-tmux: launched [governor] in %s (window %s)\n' "$gov_dir" "$win_idx"
}

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

open_worktree_window() {  # <worktree> <kickoff> [<branch> [<group>]]
  local wt="$1" kf="$2" branch="${3:-}" group="${4:-}"
  if [ "$#" -lt 3 ]; then
    branch="$(git -C "$wt" branch --show-current 2>/dev/null || true)"
    [ -n "$branch" ] || branch="$(basename "$wt")"
  fi
  ensure_session

  local win_name agent_cmd win_idx
  win_name="$(window_label_for "$group" "$branch" "$wt")"
  agent_cmd="$(printf 'cd %q && exec %q --mode plan --prompt-interactive "$(cat %q)"' "$wt" "$AGY_BIN" "$kf")"
  win_idx="$(open_agent_window "$win_name" "$wt" "$agent_cmd")"
  printf 'agy-tmux: launched [%s] %s in %s (window %s)\n' "$win_name" "$branch" "$wt" "$win_idx"
}

if [ -n "$window_wt" ]; then
  command -v "$AGY_BIN" >/dev/null 2>&1 || die "agy CLI not found ($AGY_BIN)"
  [ -d "$window_wt" ] || die "worktree not found: $window_wt"
  [ -f "$window_kf" ] || die "kickoff not found: $window_kf"
  window_wt="$(cd "$window_wt" && pwd)"
  window_kf="$(cd "$(dirname "$window_kf")" && pwd)/$(basename "$window_kf")"
  open_worktree_window "$window_wt" "$window_kf"
  exit 0
fi

if [ "${#groups[@]}" -eq 0 ]; then
  if tmux_cmd has-session -t "=$session" 2>/dev/null; then
    ensure_session
  else
    launch_governor || exit 1
  fi
  tmux_cmd select-window -t "=$session:0"
  attach_session
  exit 0
fi

[ -x "$START_TICKET_BIN" ] || command -v "$START_TICKET_BIN" >/dev/null 2>&1 \
  || die "start-ticket.sh not found ($START_TICKET_BIN)"
command -v "$AGY_BIN" >/dev/null 2>&1 || die "agy CLI not found ($AGY_BIN)"

launch_group() {  # <group>
  local group="$1"
  check_mem_guard "$group" || return 1

  local st_args=("$group" --no-tab)
  [ -z "$provider" ] || st_args+=(--provider "$provider")

  local out
  if ! out="$(MEM_GUARD_OVERRIDE="$force_override" "$START_TICKET_BIN" "${st_args[@]}")"; then
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

  open_worktree_window "$wt" "$kf" "$branch" "$group"
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
