#!/usr/bin/env bash
# Drift check: every Claude-only construct used by the commands a cloud adapter
# covers must have a row in the adapter's construct map, and every row must
# still occur in those commands.
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$tools_dir")"

fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

check() { # check <adapter.md> <command.md>...
  local adapter="$1"; shift
  python3 -I - "$adapter" "$@" <<'PY' || return 1
import re, sys

adapter, commands = sys.argv[1], sys.argv[2:]
construct = re.compile(
    r"mcp__[a-z_]+__|\b(?:AskUserQuestion|EnterWorktree|ExitWorktree|TodoWrite|EnterPlanMode|ExitPlanMode)\b"
    r"|\b(?:agent-phase|session-label|sibling-worktrees|github-review-poll|github-review-state|request-review)\.sh\b"
    r"|\bGT_LABEL_[A-Z_]+\b|--tab-only|--no-multi|--no-watch|--review|--launcher|--confirm-commits|github-review-repair-agent|local-review-cycle-manager|~/\.config/local-review-only|claude agents|Co-Authored-By|git push --no-verify"
    r"|~/\.claude/"
    r"|(?<![\w/.-])/(?:start|open-pr|finalize|discuss|board|github-review-comments|local-review-cycle)\b"
)
used = {}
for path in commands:
    for match in construct.finditer(open(path, encoding="utf-8").read()):
        used.setdefault(match.group(0), path)

rows = {m.group(1) for line in open(adapter, encoding="utf-8")
        if (m := re.match(r"\| `([^`]+)` \|", line))}

undocumented = sorted(set(used) - rows)
stale = sorted(rows - set(used))
if undocumented:
    print("constructs used by covered commands but missing from the adapter: " + ", ".join(undocumented), file=sys.stderr)
if stale:
    print("adapter rows no covered command uses anymore: " + ", ".join(stale), file=sys.stderr)
sys.exit(1 if undocumented or stale else 0)
PY
}

codex_commands=("$repo/dot_claude/commands/start.md" "$repo/dot_claude/commands/open-pr.md")
check "$repo/workflow/adapters/codex.md" "${codex_commands[@]}" || fail "codex adapter has drifted from the commands it covers"
printf 'PASS codex adapter maps every Claude-only construct in its covered commands\n'

agy_commands=(
  "$repo/dot_claude/commands/start.md"
  "$repo/dot_claude/commands/local-review-cycle.md"
  "$repo/dot_claude/agents/local-review-cycle-manager.md"
  "$repo/dot_claude/skills/local-review-cycle-procedure/SKILL.md"
  "$repo/dot_claude/commands/open-pr.md"
  "$repo/dot_claude/commands/github-review-comments.md"
  "$repo/dot_claude/agents/github-review-repair-agent.md"
  "$repo/dot_claude/skills/github-review-procedure/SKILL.md"
)
check "$repo/workflow/adapters/agy.md" "${agy_commands[@]}" || fail "agy adapter has drifted from the commands it covers"
printf 'PASS agy adapter maps every Claude-only construct in its covered commands\n'

claude_commands=(
  "$repo/dot_claude/commands/start.md"
  "$repo/dot_claude/commands/open-pr.md"
  "$repo/dot_claude/commands/finalize.md"
  "$repo/dot_claude/commands/local-review-cycle.md"
  "$repo/dot_claude/agents/local-review-cycle-manager.md"
  "$repo/dot_claude/skills/local-review-cycle-procedure/SKILL.md"
  "$repo/dot_claude/commands/github-review-comments.md"
  "$repo/dot_claude/agents/github-review-repair-agent.md"
  "$repo/dot_claude/skills/github-review-procedure/SKILL.md"
)
check "$repo/workflow/adapters/claude-cloud.md" "${claude_commands[@]}" || fail "claude-cloud adapter has drifted from the commands it covers"
printf 'PASS claude-cloud adapter maps every Claude-only construct in its covered commands\n'

commands=("${codex_commands[@]}")

fixture="$(mktemp -d)"
trap 'rm -rf "$fixture"' EXIT
cp "$repo/workflow/adapters/codex.md" "$fixture/adapter.md"
cp "${commands[@]}" "$fixture/"

printf '\nCall AskUserQuestion here, then mcp__github__create.\n' >> "$fixture/start.md"
if check "$fixture/adapter.md" "$fixture/start.md" "$fixture/open-pr.md" 2>"$fixture/err"; then
  fail "a new unmapped construct must be detected"
fi
grep -q 'mcp__github__' "$fixture/err" || fail "the unmapped construct should be named"
cp "${commands[0]}" "$fixture/start.md"
pass_new=1

printf '| `TodoWrite` | Drop. |\n' >> "$fixture/adapter.md"
if check "$fixture/adapter.md" "${commands[@]}" 2>"$fixture/err"; then
  fail "a stale adapter row must be detected"
fi
grep -q 'TodoWrite' "$fixture/err" || fail "the stale row should be named"
[[ "$pass_new" == 1 ]] && printf 'PASS detects unmapped constructs and stale rows\n'

for adapter_name in codex agy claude-cloud; do
  adapter="$repo/workflow/adapters/${adapter_name}.md"
  if grep -q 'bash <(' "$adapter"; then fail "$adapter_name adapter must not run the bootstrap via process substitution (hides download failure)"; fi
  for rule in 'workflow_source_commit=' 'Never imply a check passed' 'Workflow source:'; do
    grep -q -- "$rule" "$adapter" || fail "$adapter_name adapter protocol is missing: $rule"
  done
done
printf 'PASS adapter protocol keeps fail-closed download, SHA stamp, and unrun-check rules\n'
