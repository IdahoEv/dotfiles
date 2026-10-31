#!/usr/bin/env bash
# reviewer-model.sh — toggle the review-chain agents' `model:` between
# sonnet and auto.
#
#   reviewer-model.sh auto|sonnet
#
# Rewrites the `model:` frontmatter line of the eight review-chain agents in
# the deploy clone's dot_claude/agents/, then runs `chezmoi -S <deploy clone>
# apply` on exactly those targets so ~/.claude/agents/ reflects the change
# immediately. `sonnet` is the committed default: flipping back leaves the
# deploy clone clean, so the diff while on `auto` is expected and temporary.
#
# Validation happens before any write: if a target file's `model:` value is
# neither sonnet, auto, nor the requested target, the script exits 1 naming
# the file, so future agent edits can't silently escape the toggle.
#
# REVIEWER_MODEL_SOURCE overrides the deploy-clone root (tests use it to point
# at a sandbox); REVIEWER_MODEL_SKIP_APPLY=1 skips the chezmoi apply.
#
# Exit codes: 0 on success and on the no-op "already at target" case; 1 on
# usage errors and model-line drift.

set -euo pipefail

die() { printf 'reviewer-model: %s\n' "$*" >&2; exit 1; }

AGENTS="correctness-reviewer architecture-reviewer robustness-reviewer \
security-reviewer supply-chain-reviewer prompt-reviewer \
local-review-cycle-manager github-review-repair-agent"

[ $# -eq 1 ] || die "usage: reviewer-model.sh auto|sonnet (see --help)"
target="$1"
case "$target" in
  -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0 ;;
  sonnet|auto) ;;
  *) die "unknown state '$target' (expected: auto or sonnet)" ;;
esac

# Resolve to the deploy clone even when invoked via the ~/.local/bin symlink;
# REVIEWER_MODEL_SOURCE lets tests point at a sandbox instead.
if [ -n "${REVIEWER_MODEL_SOURCE:-}" ]; then
  root="$REVIEWER_MODEL_SOURCE"
else
  _src="${BASH_SOURCE[0]}"
  while [ -h "$_src" ]; do
    _dir="$(cd -P "$(dirname "$_src")" && pwd)"
    _src="$(readlink "$_src")"
    [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
  done
  root="$(cd -P "$(dirname "$_src")/.." && pwd)"
fi
agents_dir="$root/dot_claude/agents"
[ -d "$agents_dir" ] || die "no dot_claude/agents/ under $root — not the chezmoi source?"

model_of() {  # <name> -> its model: value
  sed -n 's/^model:[[:space:]]*//p' "$agents_dir/$1.md" | head -1
}

# Read and validate every file first, so drift never leaves a partial flip.
for name in $AGENTS; do
  f="$agents_dir/$name.md"
  [ -f "$f" ] || die "missing agent file: $f"
  val="$(model_of "$name")"
  [ -n "$val" ] || die "$f has no model: line"
  case "$val" in
    sonnet|auto) ;;
    *) die "$f has model: $val (expected sonnet or auto) — fix it before toggling" ;;
  esac
done

changed=0
for name in $AGENTS; do
  [ "$(model_of "$name")" = "$target" ] && continue
  f="$agents_dir/$name.md"
  sed -i '' "s/^model:.*/model: $target/" "$f"
  printf 'changed %s\n' "$f"
  changed=$((changed + 1))
done

if [ "$changed" -eq 0 ]; then
  printf 'already on %s — nothing to do\n' "$target"
  exit 0
fi

printf 'review-chain agents now on %s\n' "$target"

if [ "${REVIEWER_MODEL_SKIP_APPLY:-0}" = 1 ]; then
  printf 'chezmoi apply skipped (REVIEWER_MODEL_SKIP_APPLY=1)\n'
  exit 0
fi

command -v chezmoi >/dev/null || die "chezmoi not found — run: chezmoi -S $root apply ~/.claude/agents/<name>.md"
targets=()
for name in $AGENTS; do
  targets+=("$HOME/.claude/agents/$name.md")
done
# Bare `apply` would write every managed file; always name the targets.
chezmoi -S "$root" apply "${targets[@]}"
printf 'applied to ~/.claude/agents/\n'
