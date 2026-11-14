#!/usr/bin/env bash
# Integration tests for agy-tmux.sh using mocked start-ticket.sh + agy and an isolated tmux socket.

set -euo pipefail

TOOLS="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(mktemp -d)"
SOCK="agy-tmux-test-$$"

cleanup() {
  tmux -L "$SOCK" kill-server >/dev/null 2>&1 || true
  rm -rf "$ROOT"
}
trap cleanup EXIT

fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }
check() {
  local name="$1" want="$2" got="$3"
  [ "$want" = "$got" ] || fail "$name: want '$want', got '$got'"
  printf 'PASS %s\n' "$name"
}
has() {
  local name="$1" needle="$2" hay="$3"
  printf '%s' "$hay" | grep -qF -- "$needle" || fail "$name: missing '$needle' in '$hay'"
  printf 'PASS %s\n' "$name"
}

# ---- mocks -----------------------------------------------------------------
mkdir -p "$ROOT/bin" "$ROOT/wt1" "$ROOT/wt2" "$ROOT/wt3"

cat > "$ROOT/bin/mock-start-ticket.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
group="\$1"
case "\$group" in
  12,13)
    kf="$ROOT/kickoff-12-13.md"
    printf 'Kickoff 12+13\n' > "\$kf"
    printf 'worktree=%s\nkickoff=%s\nbranch=Is12+13-oauth-chain\n' "$ROOT/wt1" "\$kf"
    ;;
  14)
    kf="$ROOT/kickoff-14.md"
    printf 'Kickoff 14\n' > "\$kf"
    printf 'worktree=%s\nkickoff=%s\nbranch=Is14-fix-cache\n' "$ROOT/wt2" "\$kf"
    ;;
  15)
    kf="$ROOT/kickoff-15.md"
    printf 'Kickoff 15\n' > "\$kf"
    printf 'worktree=%s\nkickoff=%s\nbranch=Is15-add-metrics\n' "$ROOT/wt3" "\$kf"
    ;;
  *)
    echo "unexpected group: \$group" >&2; exit 1 ;;
esac
EOF

cat > "$ROOT/bin/mock-agy" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$ROOT/agy-calls.log"
sleep 30
EOF

chmod +x "$ROOT/bin/mock-start-ticket.sh" "$ROOT/bin/mock-agy"

export AGY_TMUX_START_TICKET="$ROOT/bin/mock-start-ticket.sh"
export AGY_TMUX_AGY_BIN="$ROOT/bin/mock-agy"
export AGY_TMUX_SOCKET="$SOCK"

# ---- 1. help output --------------------------------------------------------
help_out="$("$TOOLS/agy-tmux.sh" --help)"
has "--help prints usage" "Usage: agy-tmux.sh" "$help_out"

# ---- 2. launch chain + single ticket ---------------------------------------
"$TOOLS/agy-tmux.sh" --session "test-ws" --no-attach 12,13 14 >/dev/null

win_list="$(tmux -L "$SOCK" list-windows -t test-ws -F '#{window_index}:#{window_name}')"
has "window 0 is dashboard" "0:dashboard" "$win_list"
has "window 1 is chain Is12+13" "1:Is12+13" "$win_list"
has "window 2 is single Is14" "2:Is14" "$win_list"

tag="$(tmux -L "$SOCK" show-options -t test-ws -v @agy_dashboard)"
check "@agy_dashboard option set" "1" "$tag"

cz_bind="$(tmux -L "$SOCK" list-keys -T root | grep 'C-z' || true)"
has "root C-z binding installed" "@agy_dashboard" "$cz_bind"
has "root C-z selects window 0" "select-window -t :0" "$cz_bind"

# Wait briefly for mock-agy to log its invocations in the panes
for _ in 1 2 3 4 5; do
  [ -f "$ROOT/agy-calls.log" ] && [ "$(wc -l < "$ROOT/agy-calls.log")" -ge 2 ] && break
  sleep 0.2
done
calls="$(cat "$ROOT/agy-calls.log")"
has "agy invoked in plan mode with prompt-interactive (chain)" "--mode plan --prompt-interactive Kickoff 12+13" "$calls"
has "agy invoked in plan mode with prompt-interactive (single)" "--mode plan --prompt-interactive Kickoff 14" "$calls"

# ---- 3. add another group to existing session ------------------------------
"$TOOLS/agy-tmux.sh" --session "test-ws" --no-attach 15 >/dev/null
win_list2="$(tmux -L "$SOCK" list-windows -t test-ws -F '#{window_index}:#{window_name}')"
has "window 3 added to existing session" "3:Is15" "$win_list2"
