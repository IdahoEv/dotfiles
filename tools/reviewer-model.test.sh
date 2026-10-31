#!/usr/bin/env bash
# reviewer-model.test.sh — behavioral checks for reviewer-model.sh (flip,
# restore, drift detection, idempotency, apply invocation).
#
#   reviewer-model.test.sh
#
# Plain script, exits non-zero on failure. Runs against a sandbox source tree
# via REVIEWER_MODEL_SOURCE, with a fake chezmoi on PATH that records calls.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RM="$TOOLS/reviewer-model.sh"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

contains() {  # <description> <needle> <haystack>
  case "$3" in *"$2"*) check "$1" yes yes ;; *) check "$1" yes no ;; esac
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/reviewer-model-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"
mkdir -p "$HOME/bin" "$ROOT/src/dot_claude/agents"
export REVIEWER_MODEL_SOURCE="$ROOT/src"
export REVIEWER_MODEL_SKIP_APPLY=1

AGENTS="correctness-reviewer architecture-reviewer robustness-reviewer \
security-reviewer supply-chain-reviewer prompt-reviewer \
local-review-cycle-manager github-review-repair-agent"

for name in $AGENTS; do
  printf -- '---\nname: %s\nmodel: sonnet\n---\nbody\n' "$name" \
    > "$ROOT/src/dot_claude/agents/$name.md"
done

models() {  # all eight model values, space-separated
  for name in $AGENTS; do
    sed -n 's/^model:[[:space:]]*//p' "$ROOT/src/dot_claude/agents/$name.md"
  done | tr '\n' ' ' | sed 's/ $//'
}

run() { "$RM" "$@" 2>&1; }

# --- flip to auto ---
out="$(run auto)"
check "flip output names eight changed files" "8" \
  "$(printf '%s\n' "$out" | grep -c '^changed ')"
check "flip announces resulting state" "review-chain agents now on auto" \
  "$(printf '%s\n' "$out" | grep '^review-chain agents now')"
check "all eight on auto" \
  "auto auto auto auto auto auto auto auto" "$(models)"

# --- restore sonnet ---
out="$(run sonnet)"
check "restore announces resulting state" "review-chain agents now on sonnet" \
  "$(printf '%s\n' "$out" | grep '^review-chain agents now')"
check "all eight back on sonnet" \
  "sonnet sonnet sonnet sonnet sonnet sonnet sonnet sonnet" "$(models)"

# --- idempotency ---
chezmoi_log="$ROOT/chezmoi-calls"
: > "$chezmoi_log"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> %s\n' "$chezmoi_log" > "$HOME/bin/chezmoi"
chmod +x "$HOME/bin/chezmoi"
export PATH="$HOME/bin:$PATH"
unset REVIEWER_MODEL_SKIP_APPLY

out="$(run sonnet)"
check "idempotent run exits 0" "0" "$?"
contains "idempotent run says nothing to do" "already on sonnet — nothing to do" "$out"
check "idempotent run skips chezmoi" "0" "$(wc -l < "$chezmoi_log" | tr -d ' ')"

# --- apply invocation (a real flip, with the fake chezmoi) ---
out="$(run auto)"
check "real flip invokes chezmoi once" "1" "$(wc -l < "$chezmoi_log" | tr -d ' ')"
contains "chezmoi gets -S <source root>" "-S $ROOT/src" "$(cat "$chezmoi_log")"
contains "chezmoi names a target file" "$HOME/.claude/agents/correctness-reviewer.md" "$(cat "$chezmoi_log")"
run sonnet >/dev/null   # leave the sandbox on the committed default

# --- drift detection ---
sed -i '' 's/^model:.*/model: opus/' "$ROOT/src/dot_claude/agents/prompt-reviewer.md"
before="$(models)"
out="$(run auto)"; rc=$?
check "drift exits non-zero" "yes" "$([ "$rc" -ne 0 ] && echo yes || echo no)"
contains "drift message names file and value" \
  "prompt-reviewer.md has model: opus" "$out"
check "drift modifies nothing" "$before" "$(models)"

# --- usage errors ---
out="$(run fable)"; rc=$?
check "unknown state exits 1" "1" "$rc"
contains "unknown state names the value" "unknown state 'fable'" "$out"
out="$("$RM" 2>&1)"; rc=$?
check "no argument exits 1" "1" "$rc"
contains "no argument shows usage" "usage:" "$out"
out="$(run --help)"
contains "--help documents both states" "reviewer-model.sh auto|sonnet" "$out"
contains "--help names the committed default" "committed default" "$out"

# --- source-root guard ---
unset REVIEWER_MODEL_SOURCE
out="$(REVIEWER_MODEL_SOURCE="$ROOT/empty" run auto)"; rc=$?
check "bad source root exits 1" "1" "$rc"
contains "bad source root is named" "no dot_claude/agents/" "$out"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
