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
mkdir -p "$ROOT/bin" "$ROOT/wt1" "$ROOT/wt2" "$ROOT/wt3" "$ROOT/wt4" "$ROOT/wt5"

cat > "$ROOT/bin/mock-start-ticket.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >> "$ROOT/start-ticket-calls.log"
printf 'override=%s\n' "\${MEM_GUARD_OVERRIDE:-unset}" >> "$ROOT/start-ticket-env.log"
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
  12345)
    kf="$ROOT/kickoff-sc-12345.md"
    printf 'Kickoff sc-12345\n' > "\$kf"
    printf 'worktree=%s\nkickoff=%s\nbranch=sc-12345-fix-bug\n' "$ROOT/wt4" "\$kf"
    ;;
  77,78)
    kf="$ROOT/kickoff-77-78.md"
    printf 'Kickoff 77+78\n' > "\$kf"
    printf 'worktree=%s\nkickoff=%s\nbranch=\n' "$ROOT/wt5" "\$kf"
    ;;
  *)
    echo "unexpected group: \$group" >&2; exit 1 ;;
esac
EOF

cat > "$ROOT/bin/mock-agy" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$ROOT/agy-calls.log"
printf 'override=%s\n' "\${MEM_GUARD_OVERRIDE:-unset}" >> "$ROOT/agy-env.log"
sleep 30
EOF

cat > "$ROOT/bin/mock-agy-fast-exit" <<EOF
#!/usr/bin/env bash
exit 1
EOF

chmod +x "$ROOT/bin/mock-start-ticket.sh" "$ROOT/bin/mock-agy" "$ROOT/bin/mock-agy-fast-exit"

export AGY_TMUX_START_TICKET="$ROOT/bin/mock-start-ticket.sh"
export AGY_TMUX_AGY_BIN="$ROOT/bin/mock-agy"
export AGY_TMUX_SOCKET="$SOCK"
# Never measure the real host: pin a healthy memory reading (guard tests override it).
export MEM_GUARD_HOST_FIXTURE="level=normal free_pct=80"
export MEM_GUARD_PS_FIXTURE="$ROOT/no-ps"
unset MEM_GUARD_OVERRIDE

# ---- 1. help output --------------------------------------------------------
help_out="$("$TOOLS/agy-tmux.sh" --help)"
has "--help prints usage" "Usage: agy-tmux.sh" "$help_out"

# ---- 2. no-args on missing session launches governor in main worktree ---------
git init -q "$ROOT/gov-repo"
git -C "$ROOT/gov-repo" checkout -q -B main
git -C "$ROOT/gov-repo" -c user.name=test -c user.email=test@example.com commit -q --allow-empty -m "init"
git -C "$ROOT/gov-repo" worktree add -q -b feat "$ROOT/gov-linked"
(cd "$ROOT/gov-linked" && "$TOOLS/agy-tmux.sh" --session "gov-ws" --no-attach >/dev/null)
gov_wins="$(tmux -L "$SOCK" list-windows -t '=gov-ws' -F '#{window_index}:#{window_name}')"
has "no-args creates dashboard in window 0" "0:dashboard" "$gov_wins"
has "no-args creates governor in window 1" "1:governor" "$gov_wins"
gov_roe="$(tmux -L "$SOCK" show-window-options -t '=gov-ws:1' -v remain-on-exit)"
check "governor window sets remain-on-exit on" "on" "$gov_roe"
gov_path="$(tmux -L "$SOCK" display-message -t '=gov-ws:1' -p '#{pane_current_path}')"
check "governor window opens in main worktree" "$(cd "$ROOT/gov-repo" && pwd -P)" "$gov_path"
for _ in 1 2 3 4 5; do
  [ -f "$ROOT/agy-calls.log" ] && [ "$(wc -l < "$ROOT/agy-calls.log")" -ge 1 ] && break
  sleep 0.2
done
gov_calls="$(cat "$ROOT/agy-calls.log")"
has "governor invokes agy with /governor" "--mode plan --prompt-interactive /governor" "$gov_calls"
rm -f "$ROOT/agy-calls.log"

# Re-running no-args on existing session re-attaches without adding another governor window.
"$TOOLS/agy-tmux.sh" --session "gov-ws" --no-attach >/dev/null
gov_wins_re="$(tmux -L "$SOCK" list-windows -t '=gov-ws' -F '#{window_index}:#{window_name}')"
check "no-args on existing session does not duplicate governor" "2" "$(printf '%s\n' "$gov_wins_re" | wc -l | tr -d ' ')"
tmux -L "$SOCK" kill-session -t "=gov-ws"
sleep 0.2

# ---- 3. preserve existing C-z binding & launch chain + single ticket -------
tmux -L "$SOCK" new-session -d -s "other-ws" "sleep 30"
tmux -L "$SOCK" bind-key -n C-z "display-message custom-cz"

"$TOOLS/agy-tmux.sh" --session "test-ws" --no-attach 12,13 14 >/dev/null

win_list="$(tmux -L "$SOCK" list-windows -t '=test-ws' -F '#{window_index}:#{window_name}')"
has "window 0 is dashboard" "0:dashboard" "$win_list"
has "window 1 is chain Is12+13" "1:Is12+13" "$win_list"
has "window 2 is single Is14" "2:Is14" "$win_list"

tag="$(tmux -L "$SOCK" show-options -t 'test-ws' -v @agy_dashboard)"
check "@agy_dashboard option set" "1" "$tag"

cz_bind="$(tmux -L "$SOCK" list-keys -T root | grep 'C-z' || true)"
has "root C-z binding installed" "@agy_dashboard" "$cz_bind"
has "root C-z selects window 0" "select-window -t :0" "$cz_bind"
has "root C-z preserves prior binding as fallback" "display-message custom-cz" "$cz_bind"

for _ in 1 2 3 4 5; do
  [ -f "$ROOT/agy-calls.log" ] && [ "$(wc -l < "$ROOT/agy-calls.log")" -ge 2 ] && break
  sleep 0.2
done
calls="$(cat "$ROOT/agy-calls.log")"
has "agy invoked in plan mode with prompt-interactive (chain)" "--mode plan --prompt-interactive Kickoff 12+13" "$calls"
has "agy invoked in plan mode with prompt-interactive (single)" "--mode plan --prompt-interactive Kickoff 14" "$calls"

# ---- 4. add another group + shortcut branch + provider forwarding ----------
"$TOOLS/agy-tmux.sh" --session "test-ws" --provider shortcut --no-attach 15 12345 >/dev/null
win_list2="$(tmux -L "$SOCK" list-windows -t '=test-ws' -F '#{window_index}:#{window_name}')"
has "window 3 added to existing session" "3:Is15" "$win_list2"
has "shortcut branch named sc-12345" "4:sc-12345" "$win_list2"
st_calls="$(cat "$ROOT/start-ticket-calls.log")"
has "--provider shortcut forwarded" "12345 --no-tab --provider shortcut" "$st_calls"

# ---- 5. recover missing window 0 on no-args re-attach ----------------------
tmux -L "$SOCK" kill-window -t '=test-ws:0'
"$TOOLS/agy-tmux.sh" --session "test-ws" --no-attach >/dev/null
win_list3="$(tmux -L "$SOCK" list-windows -t '=test-ws' -F '#{window_index}:#{window_name}')"
has "window 0 recreated on re-attach" "0:dashboard" "$win_list3"

# ---- 5b. repair non-dashboard window 0 on reuse ----------------------------
tmux -L "$SOCK" new-session -d -s "manual-ws" -n "shell" "sleep 30"
"$TOOLS/agy-tmux.sh" --session "manual-ws" --no-attach >/dev/null
manual_wins="$(tmux -L "$SOCK" list-windows -t '=manual-ws' -F '#{window_index}:#{window_name}')"
has "manual session window 0 replaced with dashboard" "0:dashboard" "$manual_wins"
has "manual session original shell preserved" ":shell" "$manual_wins"

# ---- 5c. fallback chain label uses '+' not ',' -----------------------------
"$TOOLS/agy-tmux.sh" --session "test-ws" --no-attach 77,78 >/dev/null
win_list4="$(tmux -L "$SOCK" list-windows -t '=test-ws' -F '#{window_index}:#{window_name}')"
has "fallback chain label replaces comma with plus" ":77+78" "$win_list4"

# ---- 5d. fast-exiting agy stays alive via remain-on-exit -------------------
AGY_TMUX_AGY_BIN="$ROOT/bin/mock-agy-fast-exit" "$TOOLS/agy-tmux.sh" --session "fast-exit-ws" --no-attach 15 >/dev/null
sleep 0.2
fe_wins="$(tmux -L "$SOCK" list-windows -t '=fast-exit-ws' -F '#{window_index}:#{window_name}:#{pane_dead}')"
has "fast-exit window kept alive with pane_dead=1" "1:Is15:1" "$fe_wins"

# ---- 6. session prefix isolation (=exact match) ----------------------------
tmux -L "$SOCK" new-session -d -s "test-exact-other" "sleep 30"
"$TOOLS/agy-tmux.sh" --session "test-exact" --no-attach 15 >/dev/null
exact_wins="$(tmux -L "$SOCK" list-windows -t '=test-exact' -F '#{window_index}:#{window_name}')"
has "exact session test-exact created despite test-exact-other" "1:Is15" "$exact_wins"

# ---- 7. start-ticket failure handling --------------------------------------
if "$TOOLS/agy-tmux.sh" --session "test-fail-only" --no-attach 999 >/dev/null 2>&1; then
  fail "sole failing group should exit non-zero"
fi
if tmux -L "$SOCK" has-session -t '=test-fail-only' 2>/dev/null; then
  fail "sole failing group should not leave empty session"
fi
printf 'PASS sole failing group leaves no empty session\n'

if "$TOOLS/agy-tmux.sh" --session "test-partial" --no-attach 999 15 >/dev/null 2>&1; then
  fail "partial failure should exit non-zero under --no-attach"
fi
partial_wins="$(tmux -L "$SOCK" list-windows -t '=test-partial' -F '#{window_index}:#{window_name}')"
has "valid group launches despite earlier failing group" "1:Is15" "$partial_wins"

# ---- 8. C-z restored when last @agy_dashboard session closes ---------------
for s in test-ws manual-ws fast-exit-ws test-exact test-partial; do
  tmux -L "$SOCK" kill-session -t "=$s"
done
sleep 0.2
restored_cz="$(tmux -L "$SOCK" list-keys -T root | grep 'C-z' || true)"
has "prior C-z binding restored after agy sessions close" "display-message custom-cz" "$restored_cz"
if printf '%s' "$restored_cz" | grep -qF '@agy_dashboard'; then
  fail "C-z binding still contains @agy_dashboard after cleanup"
fi
printf 'PASS C-z @agy_dashboard wrapper cleaned up\n'

# ---- 8b. dashboard gets the memory provider as an opaque command ---------------
"$TOOLS/agy-tmux.sh" --session "mem-cmd-ws" --no-attach 15 >/dev/null
dash_cmd="$(tmux -L "$SOCK" list-windows -t '=mem-cmd-ws' -F '#{window_index} #{pane_start_command}' | grep '^0 ')"
has "dashboard is given --mem-cmd" "--mem-cmd" "$dash_cmd"
has "provider is mem-guard.sh" "mem-guard.sh" "$dash_cmd"
has "provider asks for JSON" "--json" "$dash_cmd"
has "provider is scoped to the session" "mem-cmd-ws" "$(printf '%s' "$dash_cmd" | sed 's/.*--mem-cmd//')"
tmux -L "$SOCK" kill-session -t "=mem-cmd-ws"
AGY_TMUX_MEM_GUARD="$ROOT/bin/does-not-exist" "$TOOLS/agy-tmux.sh" --session "no-mem-ws" --no-attach 15 >/dev/null 2>&1
dash_cmd="$(tmux -L "$SOCK" list-windows -t '=no-mem-ws' -F '#{window_index} #{pane_start_command}' | grep '^0 ')"
if printf '%s' "$dash_cmd" | grep -qF -- '--mem-cmd'; then fail "dashboard should have no memory provider when the guard is absent"; fi
printf 'PASS dashboard has no memory provider when mem-guard is absent\n'
tmux -L "$SOCK" kill-session -t "=no-mem-ws"

# ---- 9. mem-guard blocks launches under dangerous memory pressure ----------
rm -f "$ROOT/start-ticket-calls.log"
rc=0
MEM_GUARD_HOST_FIXTURE="level=critical free_pct=4" "$TOOLS/agy-tmux.sh" --session "mem-block-ws" --no-attach 14 >"$ROOT/mem.out" 2>"$ROOT/mem.err" || rc=$?
check "blocked launch exits non-zero" "1" "$rc"
has "blocked launch names mem-guard" "blocked by mem-guard" "$(cat "$ROOT/mem.err")"
check "blocked launch never runs start-ticket" "no" "$([ -s "$ROOT/start-ticket-calls.log" ] && echo yes || echo no)"
if tmux -L "$SOCK" has-session -t '=mem-block-ws' 2>/dev/null; then
  fail "blocked launch should not create a session"
fi
printf 'PASS blocked launch creates no tmux session\n'

rc=0
MEM_GUARD_HOST_FIXTURE="level=critical free_pct=4" "$TOOLS/agy-tmux.sh" --session "mem-block-gov-ws" --no-attach >"$ROOT/mem.out" 2>"$ROOT/mem.err" || rc=$?
check "blocked governor launch exits non-zero" "1" "$rc"
has "blocked governor launch names mem-guard" "blocked by mem-guard" "$(cat "$ROOT/mem.err")"
if tmux -L "$SOCK" has-session -t '=mem-block-gov-ws' 2>/dev/null; then
  fail "blocked governor launch should not create a session"
fi
printf 'PASS blocked governor launch creates no tmux session\n'

rm -f "$ROOT/agy-env.log"
MEM_GUARD_HOST_FIXTURE="level=critical free_pct=4" "$TOOLS/agy-tmux.sh" --session "mem-force-gov-ws" --no-attach --force >/dev/null 2>"$ROOT/mem.err"
for _ in 1 2 3 4 5; do [ -s "$ROOT/agy-env.log" ] && break; sleep 0.2; done
check "--force governor never reaches the agent pane" "override=unset" "$(cat "$ROOT/agy-env.log")"
has "--force overrides governor block" "1:governor" "$(tmux -L "$SOCK" list-windows -t '=mem-force-gov-ws' -F '#{window_index}:#{window_name}')"
tmux -L "$SOCK" kill-session -t "=mem-force-gov-ws"

rm -f "$ROOT/agy-env.log" "$ROOT/start-ticket-env.log"
MEM_GUARD_HOST_FIXTURE="level=critical free_pct=4" "$TOOLS/agy-tmux.sh" --session "mem-force-ws" --no-attach --force 14 >/dev/null 2>"$ROOT/mem.err"
for _ in 1 2 3 4 5; do [ -s "$ROOT/agy-env.log" ] && break; sleep 0.2; done
check "--force reaches start-ticket's own guard" "override=1" "$(cat "$ROOT/start-ticket-env.log")"
check "--force never reaches the agent pane" "override=unset" "$(cat "$ROOT/agy-env.log")"
check "--force never enters the tmux server environment" "no" "$(tmux -L "$SOCK" show-environment -g 2>/dev/null | grep -q MEM_GUARD_OVERRIDE && echo yes || echo no)"
has "--force overrides the block" "1:Is14" "$(tmux -L "$SOCK" list-windows -t '=mem-force-ws' -F '#{window_index}:#{window_name}')"
has "override is announced" "OVERRIDE" "$(cat "$ROOT/mem.err")"

MEM_GUARD_HOST_FIXTURE="level=warn free_pct=12" "$TOOLS/agy-tmux.sh" --session "mem-warn-ws" --no-attach 15 >/dev/null 2>"$ROOT/mem.err"
has "warning level still launches" "1:Is15" "$(tmux -L "$SOCK" list-windows -t '=mem-warn-ws' -F '#{window_index}:#{window_name}')"
has "warning level warns" "WARNING" "$(cat "$ROOT/mem.err")"

AGY_TMUX_MEM_GUARD="$ROOT/bin/does-not-exist" "$TOOLS/agy-tmux.sh" --session "mem-missing-ws" --no-attach 15 >/dev/null 2>"$ROOT/mem.err"
has "missing guard script warns and launches" "launching without a memory check" "$(cat "$ROOT/mem.err")"
has "missing guard script still launches" "1:Is15" "$(tmux -L "$SOCK" list-windows -t '=mem-missing-ws' -F '#{window_index}:#{window_name}')"
for s in mem-force-ws mem-warn-ws mem-missing-ws; do tmux -L "$SOCK" kill-session -t "=$s"; done

# A crashing guard (any exit other than 0/3) warns and launches rather than silently proceeding.
printf '#!/bin/sh\nexit 7\n' > "$ROOT/bin/crash-guard"; chmod +x "$ROOT/bin/crash-guard"
AGY_TMUX_MEM_GUARD="$ROOT/bin/crash-guard" "$TOOLS/agy-tmux.sh" --session "mem-crash-ws" --no-attach 15 >/dev/null 2>"$ROOT/mem.err"
has "crashing guard is reported" "mem-guard failed (exit 7)" "$(cat "$ROOT/mem.err")"
has "crashing guard still launches" "1:Is15" "$(tmux -L "$SOCK" list-windows -t '=mem-crash-ws' -F '#{window_index}:#{window_name}')"
tmux -L "$SOCK" kill-session -t "=mem-crash-ws"

# ---- 10. --window opens a pane in active @agy_dashboard without stealing focus ----
"$TOOLS/agy-tmux.sh" --session "win-ws" --no-attach 14 >/dev/null
tmux -L "$SOCK" select-window -t "=win-ws:1"
caller_pane="$(tmux -L "$SOCK" display-message -t "=win-ws:1" -p '#{pane_id}')"
mkdir -p "$ROOT/win_wt"
git -C "$ROOT/win_wt" init -q -b Is198-window-test
printf 'Kickoff 198\n' > "$ROOT/win_kf.md"
rm -f "$ROOT/agy-calls.log"
TMUX="stub,1,0" TMUX_PANE="$caller_pane" "$TOOLS/agy-tmux.sh" --window "$ROOT/win_wt" "$ROOT/win_kf.md" >/dev/null
win_ws_list="$(tmux -L "$SOCK" list-windows -t '=win-ws' -F '#{window_index}:#{window_name}:#{window_active}:#{remain-on-exit}')"
has "--window appends Is198 with remain-on-exit" "2:Is198:0:on" "$win_ws_list"
active_win="$(tmux -L "$SOCK" list-windows -t '=win-ws' -F '#{window_active}:#{window_index}' | sed -n 's/^1://p')"
check "--window does not steal focus from caller window" "1" "$active_win"
for _ in 1 2 3 4 5; do [ -s "$ROOT/agy-calls.log" ] && break; sleep 0.2; done
has "--window invokes agy in plan mode" "--mode plan --prompt-interactive Kickoff 198" "$(cat "$ROOT/agy-calls.log")"

# Detached-HEAD worktree without .workstream.json falls back to basename of worktree.
mkdir -p "$ROOT/detached_wt"
git -C "$ROOT/detached_wt" init -q
git -C "$ROOT/detached_wt" -c user.name=test -c user.email=test@example.com commit -q --allow-empty -m "init"
git -C "$ROOT/detached_wt" checkout -q --detach HEAD
TMUX="stub,1,0" TMUX_PANE="$caller_pane" "$TOOLS/agy-tmux.sh" --window "$ROOT/detached_wt" "$ROOT/win_kf.md" >/dev/null
detached_wins="$(tmux -L "$SOCK" list-windows -t '=win-ws' -F '#{window_index}:#{window_name}')"
has "--window detached HEAD falls back to basename" "3:detached_wt" "$detached_wins"
tmux -L "$SOCK" kill-session -t "=win-ws"
