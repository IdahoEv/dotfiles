---
name: local-review-cycle-procedure
description: Procedure for running the bounded local review-and-fix cycle before /open-pr. Preloaded by the local-review-cycle-manager agent, which the /local-review-cycle command launches; not invoked directly.
user-invocable: false
---

# Local Review Cycle Procedure

Run a bounded review-and-fix cycle on the current worktree before `/open-pr`. The implementer never reviews their own work: launch fresh, read-only reviewer agents. You commit fixes locally each round by default; never push — human review happens on the PR.

Usage context: BASE comes from the kickoff and defaults to `origin/<default branch>`; a different ref targets a long-lived branch.

Use the project's documented test commands. `FAST` is the quick suite; `FULL` is the complete suite. If neither is documented, ask once before starting.

## 1. Preflight

- Set `BASE` from the kickoff. Fetch origin and use remote refs directly.
- Stop and report if the branch is the base/default branch or the tree is dirty (the implementing session must commit or resolve stray changes first). Do not rewrite history or force-update branches. If behind BASE, merge BASE into the branch and resolve conflicts before review.
- Record the changed-file set from `git diff --name-only BASE...HEAD`. Stop if empty.
- Run `FAST` as a baseline. Record pre-existing failures and compare later runs against them.
- Run `agent-phase.sh REVIEW` when available. At the start of round k, update the review statusline with `~/.claude/skills/github-review-procedure/github-review-state.sh --set-local "<k-1>*"`; when the round ends, set it to `<k>`.

## 2. Discover and select reviewers

Selection is driven by the reviewers' own `description` fields, not by rules here: every reviewer's `description` ends with a `Use when:` clause (the `reviewer-contract` skill holds the convention).

- Read the project's `CLAUDE.md` and any referenced review/workflow documentation first.
- Enumerate candidate reviewers in tier order, deduping by `name` (an earlier tier's candidate wins when names collide):
  1. Project-local agents under `.claude/agents/` (and the corresponding `dot_claude/agents/` source layout in a chezmoi dotfiles repository) — committed reviewers shared by everyone working in the repo.
  2. Personal reviewers under `docs/local/reviewers/*.md` — uncommitted and personal; format in the `reviewer-contract` skill.
  3. Global agents (`dot_claude/agents/`, deployed to `~/.claude/agents/`).
- Candidates from `docs/local/reviewers/` are not registered agent types. To launch a selected one, read its file, honor its `model` frontmatter when launching, and run it as a `general-purpose` agent whose prompt is the file's body as its brief, prefixed with the same context given to registered reviewers: `BASE`, exact diff scope, ticket criteria, already-triaged findings, and an instruction to follow the `reviewer-contract` skill. `tools` frontmatter is not enforced on these launches — the contract's read-only rule is the guard. Its `description`'s `Use when:` clause participates in selection exactly like a registered agent's.
- Match each candidate's `Use when:` clause against the changed-file set (`git diff --name-only BASE...HEAD`) and the diff's risk signals — concurrency, persistence, external services, API or data-flow changes, prompt files, multiple modules touched. A reviewer is selected when its clause matches; a reviewer whose description has no `Use when:` clause is not auto-selected — its project docs must state the trigger.
- Choose the smallest set whose clauses cover the actual risks. Risk, coupling, and behavior matter more than raw line count. Do not run every available reviewer by default.
- Do not send code reviewers a prompt-only diff: their failing-input bar finds nothing in prose. Code files in the same diff still go to the code reviewers.
- Do not add a syntax reviewer. Use the project's formatter, compiler/type checker, linter, and tests for deterministic issues.
- If adding a new project-specific reviewer is part of the task, follow the `reviewer-contract` authoring convention, and reference the reviewer from the project's `CLAUDE.md` or review instructions. Do not invent or register new reviewers during an ordinary review cycle.
- Run selected reviewers in parallel only when they can independently inspect the same committed diff. Give each the same diff scope and relevant ticket/acceptance criteria.
- Never pass the kickoff's design context to reviewers. It is your triage context only — use it to judge intent when triaging, not to frame or filter what reviewers see.

## 3. Review and triage (at most 5 rounds)

Each round:

1. Round 1 scope is `BASE...HEAD`. At the start of each round, record the round-start SHA (`git rev-parse HEAD` at that moment, stated literally — a shell variable does not survive between tool calls). Round k+1's scope is `git diff <SHA recorded at the start of round k>..HEAD` — only round k's fix commits — plus a `correctness-reviewer` pass over the files those fixes touched. Never re-state `BASE...HEAD` as a later round's scope.
2. Launch fresh instances of the selected reviewers. State `BASE`, exact diff scope, ticket criteria, and already-triaged findings. Do not pre-read the implementation on the reviewer's behalf.
3. Deduplicate overlapping findings. Keep findings only when they concern changed code and have evidence plus a credible failure path, meaningful test gap, or material design cost. Discard stylistic preferences, hypothetical risks, extremely unlikely edge cases, and fixes whose complexity/cost exceeds the plausible impact. Require stronger evidence for defensive hardening than for a direct correctness bug. Never resurrect a dismissed finding without new evidence.
4. For each triaged finding, emit one telemetry event:

   `wf-event.sh review.finding reviewer=<agent> severity=<Critical|High|Medium|Low> verdict=<fixed|dismissed|deferred> round=<k> reason=<short phrase>`

   `reason` is required for dismissed and deferred (the dismissal rationale or issue ref), optional for fixed. Identifiers and short phrases only — never code or prompt text.
5. Fix only actionable findings. Write a failing test first for behavior bugs when practical. Make the smallest adequate fix; do not expand scope. A real but out-of-scope finding is deferred: file an issue for it under the project's bookkeeping rule (tracker, epic, milestone) instead of growing the branch. Record dismissed/deferred findings and brief reasons so later rounds do not repeat them. Never silently dismiss a judgment call on scope or design intent: disclose it in the round summary of your report, and put it in the round's approval question under `--confirm-commits`.
6. Run `FAST`; fix new failures and never disable, skip, or quarantine tests to get green. Commit round fixes locally using the project's commit convention and attribution trailer. Skip the commit if nothing changed. Never push.

   With `--confirm-commits`, ask before committing with one self-contained `AskUserQuestion` holding the reviewers' findings (one line each), the verdict table, what was fixed, `FAST` status, and the full commit message. Table, between `---` rules:

   | # | Location | Finding | Verdict |
   |---|---|---|---|
   | 1 | `path:line` | terse description | ✅ fixed / ❌ dismissed — reason / ⏭ deferred — issue ref |

   Options: "Commit and run another round" (only when another round is worth it), "Commit and finish" (Recommended when the fixes were small), "Don't commit yet"; the `preview` on each commit option is the full commit message. With no file changes, ask only whether to run another round or finish. "Don't commit yet" pauses the cycle: act on the user's instructions, then ask again. The next round reviews only committed changes, so it starts only after this round's commit.
7. Stop when there are no actionable findings or remaining feedback is only repeats, speculative hardening, or low-value nits. In later rounds, scope follows step 1: reviewers see only the fix-commit diff plus the correctness pass on touched files; a full `BASE...HEAD` re-review needs a concrete reason.

If the first architecture review returns `DESIGN: unsound`, stop before changing code and ask the user whether to keep or rework the design. Include the concrete alternative and trade-offs. This gate applies only when the reviewer demonstrates a materially better alternative—not for style preferences.

If significant, well-supported findings remain after round 5, stop and ask the user. Summarize what remains and the likely structural cause; do not silently extend the cycle.

## 4. Finish

- Run `agent-phase.sh --no-review`.
- Run `FULL` once after final review fixes. Re-run only failing checks as needed and compare against the baseline.
- Record the cycle totals with `wf-event.sh review.result round=<last round number> fixed=<n> dismissed=<n> deferred=<n> reviewers=<agent,agent>`, each field only when available. A failure surfaced by `FULL` and fixed here still counts.
- Report reviewers selected and why, rounds, findings fixed/dismissed/deferred, test status (including baseline failures), and commits added. Keep output terse: one line per round (`R<k>: N fixed / M dismissed or deferred`).
- List dismissed findings with the reason for each, and deferred findings with the issue filed for each; do not implement them. Dismissed-with-reasons is mandatory — no report or PR note without it.
- End by stating `/open-pr` is the next step. The report is the source for the PR body's "Review cycle" note: rounds, fixed/dismissed/deferred counts, and the dismissed findings with their reasons.

## Guardrails

- No push, history rewriting, or edits outside the current worktree. Do not make workflow success depend on speculative hardening.
- Ask only for missing test commands, per-round commit approval under `--confirm-commits`, the unsound-design decision, or when the cycle reaches its stop limit / needs human judgment.
