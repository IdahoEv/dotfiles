#!/usr/bin/env bash
# The committed workflow/manifest.txt must match the tree (the raw-fetch install trusts it),
# and the generator must notice drift.
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$tools_dir")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

bash "$tools_dir/workflow-manifest.sh" --check >/dev/null 2>"$tmp/err" \
  || fail "committed manifest is stale: $(cat "$tmp/err") (run tools/workflow-manifest.sh --write and commit it)"
pass "the committed manifest matches the tree"

fx="$tmp/fx"
mkdir -p "$fx/tools" "$fx/workflow/adapters" "$fx/tools/examples" "$fx/dot_claude/commands"
cp "$tools_dir/workflow-manifest.sh" "$fx/tools/"
printf '#!/bin/sh\n' > "$fx/tools/run.sh"; chmod +x "$fx/tools/run.sh"
printf 'x\n' > "$fx/tools/run.test.sh"
printf 'x\n' > "$fx/tools/examples/personal.sh"
printf '# a\n' > "$fx/workflow/adapters/a.md"
printf '# s\n' > "$fx/dot_claude/commands/s.md"
ln -s ../dot_claude/commands/s.md "$fx/workflow/adapters/link.md"
git -C "$fx" init -q -b main && git -C "$fx" add -A
(cd "$fx" && bash tools/workflow-manifest.sh --write >/dev/null)
m="$fx/workflow/manifest.txt"
grep -q '  755  tools/run.sh$' "$m" || fail "executable mode should be recorded"
grep -q '  644  workflow/adapters/a.md$' "$m" || fail "plain files should be 644"
! grep -q -E 'run.test.sh|examples|link.md' "$m" || fail "tests, examples and symlinks must be left out"
(cd "$fx" && bash tools/workflow-manifest.sh --check >/dev/null) || fail "a fresh manifest should check clean"
printf '# changed\n' > "$fx/workflow/adapters/a.md"
if (cd "$fx" && bash tools/workflow-manifest.sh --check >/dev/null 2>&1); then fail "a changed file must make the manifest stale"; fi
pass "the generator records modes, skips tests/examples/symlinks, and detects drift"
