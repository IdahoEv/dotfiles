# Local Code Review Cycle

Review and fix the current branch before `/open-pr`. The implementer does not review its own work: launch fresh reviewer agents each round. This command may commit round fixes locally, but must never push.

Usage: `/local-code-review-cycle [base]`. Base defaults to `origin/<default branch>`; pass another ref for a long-lived target branch.

Use the project's documented test commands. `FAST` is the quick suite; `FULL` is the complete suite. If neither is documented, ask once before starting.

## 1. Preflight

- Set `BASE` from the argument or `origin/<default branch>`. Fetch origin and use remote refs directly.
- Stop if the current branch is the base/default branch or the working tree is dirty. Do not rewrite history or force-update branches. If behind BASE, merge BASE into the branch and resolve conflicts before review.
- Record the changed-file set from `git diff --name-only BASE...HEAD`. Stop if empty. Include untracked files in scope only if they are intentionally added before review.
- Run `FAST` once as a baseline. Record pre-existing failures and compare later runs against them.
- Run `agent-phase.sh REVIEW` when available. At each round, update the local review statusline using `review-state.sh --set-local` as documented by the existing workflow.

## 2. Select reviewers

Inspect the ticket, diff summary, changed paths, and affected callers. Use judgment, not a rigid line-count threshold: risk and coupling matter more than raw size.

- **Always:** `correctness-reviewer` for any behavior or test change. For tiny documentation-only or mechanical changes with no behavior impact, skip specialist agents and run relevant deterministic checks.
- **Architecture:** add `architecture-reviewer` when the diff changes module boundaries, abstractions, public APIs, data flow, state ownership, multiple modules, or makes a non-obvious design choice. For a large or cross-cutting diff, include it even if the trigger is uncertain.
- **Robustness:** add `robustness-reviewer` for async/concurrent code, persistence, external services, retries/timeouts, cancellation, resource cleanup, lifecycle/state transitions, or recovery paths.
- Run selected reviewers in parallel only when they can independently inspect the same committed diff. Each gets the same `BASE...HEAD` scope and is read-only.
- Don't add a separate syntax reviewer. Use the project's formatter, compiler/type checker, linter, and tests for deterministic issues.
- Each reviewer should use its focused agent instructions and return only actionable, evidenced findings. Do not ask every reviewer to repeat the same general review.

## 3. Review and triage (at most 5 rounds)

Each round:

1. Launch a fresh instance of each selected reviewer. The prompt must name `BASE`, the exact diff scope, and already-triaged findings. Do not pre-read the implementation on the reviewer's behalf.
2. Deduplicate findings across reviewers. Keep only findings in changed files with a plausible failure path or concrete, material design cost. Require evidence from code, callers, tests, or a reproducible check. Drop preferences, speculation, and findings already triaged unless there is new evidence.
3. Fix only actionable findings. For behavior bugs, write a failing test first when practical. Keep changes minimal; don't expand scope. Record dismissed or deferred findings with a short reason for later rounds.
4. Run `FAST`. Fix new failures; never disable, skip, or quarantine tests to get green. Commit fixes locally using the project's commit convention and attribution trailer. Skip the commit if nothing changed. Never push.
5. Stop when there are no actionable findings, or another round would likely yield only repeats or nits. On later rounds, rerun correctness plus only the specialist reviewers relevant to the files and risks changed by the fixes; do not repeat a full review without a reason.

If round 1's architecture review returns `DESIGN: unsound`, stop before changing code and ask the user whether to keep the design or rework it. Include the concrete alternative, trade-offs, and the review findings. The reviewer must justify a materially better alternative; a stylistic preference is not a design gate.

If significant findings remain after round 5, stop and ask the user. Summarize what recurred, what remains, and the suspected structural cause. Do not silently extend the cycle.

## 4. Finish

- Run `agent-phase.sh --no-review` when available.
- Run `FULL` once after the final review fixes. Re-run only failing checks as needed. Compare results with the baseline.
- Report tersely: reviewers selected and why; rounds; findings fixed/dismissed/deferred; test status including baseline failures; and commits added.
- List real but out-of-scope findings only; do not implement them or open tickets unless explicitly asked.
- End with the next step: `/open-pr`. Include the review-cycle summary in the PR body's "Review cycle" note.

## Guardrails

- No push, history rewriting, or edits outside the current worktree.
- Ask only for the initial missing test commands, an unsound-design decision, or when the cycle reaches its stop limit / requires human judgment.
- Keep output terse: one line per round (`R<k>: N fixed / M dismissed or deferred`).
- For prompt files (`CLAUDE.md`, `.claude/**`, chezmoi's `dot_claude/**`), use the `prompt-review` skill in diff mode against the same BASE; don't treat prose as ordinary runtime code.
