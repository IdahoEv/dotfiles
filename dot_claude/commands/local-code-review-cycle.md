# Local Code Review Cycle

Run a bounded review-and-fix cycle on the current worktree before `/open-pr`. The implementer does not review its own work: launch fresh, read-only reviewer agents. This command may commit fixes locally; it must never push.

Usage: `/local-code-review-cycle [base]`. Base defaults to `origin/<default branch>`; pass another ref for a long-lived target branch.

Use the project's documented test commands. `FAST` is the quick suite; `FULL` is the complete suite. If neither is documented, ask once before starting.

## 1. Preflight

- Set `BASE` from the argument or `origin/<default branch>`. Fetch origin and use remote refs directly.
- Stop if the current branch is the base/default branch or the working tree is dirty; ask the user to commit or resolve stray changes first. Do not rewrite history or force-update branches. If behind BASE, merge BASE into the branch and resolve conflicts before review.
- Record the changed-file set from `git diff --name-only BASE...HEAD`. Stop if empty.
- Run `FAST` as a baseline. Record pre-existing failures and compare later runs against them.
- Run `agent-phase.sh REVIEW` when available. At the start of round k, update the review statusline with `~/.claude/skills/review-comments/review-state.sh --set-local "<k-1>*"`; when the round ends, set it to `<k>`, as supported by the existing workflow.

## 2. Discover and select reviewers

First inspect the project instructions and reviewer definitions before selecting agents:
- Read the project's `CLAUDE.md` and any referenced review/workflow documentation.
- Look for project-local agents under `.claude/agents/` (and the corresponding `dot_claude/agents/` source layout when working in a chezmoi dotfiles repository). Check project docs for reviewer instructions defined elsewhere.
- Treat project-specific reviewers as first-class options. Follow their documented scope and activation conditions; for example, a game project may define performance and game-UI reviewers, while a web project may define a frontend usability/accessibility reviewer.
- If a project-local reviewer fits the changed files or risk better than a generic reviewer, select it. Combine it with a general reviewer only when the responsibilities are complementary. Do not run every available reviewer by default.
- If adding a new project-specific reviewer is part of the task, use the project's existing convention. Otherwise, a useful convention is an agent definition with a clear scope, evidence requirements, finding format, and explicit invocation criteria, referenced from the project's `CLAUDE.md` or review instructions. Do not invent or register new reviewers during an ordinary review cycle.

Then choose the smallest set that covers the actual risks. Risk, coupling, and behavior matter more than raw line count.

- **Correctness:** use `correctness-reviewer` for non-trivial behavior or test changes. Tiny documentation-only or mechanical changes with no behavior impact may need only deterministic checks.
- **Architecture:** use `architecture-reviewer` when the diff changes module boundaries, abstractions, public APIs, data flow, state ownership, multiple modules, or makes a consequential design choice. Include it for large or cross-cutting changes.
- **Robustness:** use `robustness-reviewer` for realistic risks involving async/concurrent code, persistence, external services, retries/timeouts, cancellation, resource cleanup, lifecycle/state transitions, or recovery.
- **Prompt:** use `prompt-reviewer` in diff mode with the same `BASE...HEAD` when the diff touches `CLAUDE.md`, `.claude/**`, or chezmoi's `dot_claude/**`. The code reviewers' failing-input bar finds nothing in prose, so don't send them prompt-only diffs; code files in the same diff still go to them.
- **Project-specific:** invoke only when its documented trigger matches the changed area or a concrete risk in this diff. A specialist such as performance or UI/UX should not be run on unrelated changes.
- Do not add a syntax reviewer. Use the project's formatter, compiler/type checker, linter, and tests for deterministic issues.
- Run selected reviewers in parallel only when they can independently inspect the same committed diff. Give each the same `BASE...HEAD` scope and relevant ticket/acceptance criteria.

## 3. Review and triage (at most 5 rounds)

Each round:

1. Launch fresh instances of the selected reviewers. State `BASE`, exact diff scope, ticket criteria, and already-triaged findings. Do not pre-read the implementation on the reviewer's behalf.
2. Deduplicate overlapping findings. Keep findings only when they concern changed code and have evidence plus a credible failure path, meaningful test gap, or material design cost. Discard stylistic preferences, hypothetical risks, extremely unlikely edge cases, and fixes whose complexity/cost exceeds the plausible impact. Require stronger evidence for defensive hardening than for a direct correctness bug. Never resurrect a dismissed finding without new evidence.
3. Fix only actionable findings. Write a failing test first for behavior bugs when practical. Make the smallest adequate fix; do not expand scope. Record dismissed/deferred findings and brief reasons so later rounds do not repeat them.
4. Run `FAST`; fix new failures and never disable, skip, or quarantine tests to get green. Commit round fixes locally using the project's commit convention and attribution trailer. Skip the commit if nothing changed. Never push.
5. Stop when there are no actionable findings or remaining feedback is only repeats, speculative hardening, or low-value nits. In later rounds, rerun only the reviewers relevant to the files/risks changed by the fixes; do not repeat a full review without a reason.

If the first architecture review returns `DESIGN: unsound`, stop before changing code and ask the user whether to keep or rework the design. Include the concrete alternative and trade-offs. This gate applies only when the reviewer demonstrates a materially better alternative—not for style preferences.

If significant, well-supported findings remain after round 5, stop and ask the user. Summarize what remains and the likely structural cause; do not silently extend the cycle.

## 4. Finish

- Run `agent-phase.sh --no-review` when available.
- Run `FULL` once after final review fixes. Re-run only failing checks as needed and compare against the baseline.
- Report reviewers selected and why, rounds, findings fixed/dismissed/deferred, test status (including baseline failures), and commits added. Keep output terse: one line per round (`R<k>: N fixed / M dismissed or deferred`).
- List real but out-of-scope findings only; do not implement them or open tickets unless asked.
- End with `/open-pr` as the next step. Include the review-cycle summary in the PR body's "Review cycle" note.

## Guardrails

- No push, history rewriting, or edits outside the current worktree. Do not make workflow success depend on speculative hardening.
- Ask only for missing test commands, the unsound-design decision, or when the cycle reaches its stop limit / needs human judgment.
