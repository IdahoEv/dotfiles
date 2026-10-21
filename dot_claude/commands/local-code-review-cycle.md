# Local Code Review Cycle

Run an unattended review-and-fix cycle on the current worktree's branch, before the PR
exists. Local counterpart of `/cloud-code-review-cycle`: same loop and stop rules, but it
runs in a worktree, uses a fresh reviewer subagent each round, and ends at "ready for
`/open-pr`" instead of pushing or opening a PR. Needs no input unless the cycle stops
for human evaluation (Step 3).

Usage: `/local-code-review-cycle [base]`. `base` defaults to `origin/<default branch>`; pass another ref
when the PR targets a long-running branch.

Test commands: use the project's own (CLAUDE.md / README). `FAST` = its quick suite
(quiet output, slow tests excluded if supported); `FULL` = the complete suite. If
neither is documented, ask once up front, not mid-cycle.

Invoking this command is explicit authorization to commit each round's fixes locally.
Never push.

## Steps

### 1. Preflight

- `BASE` = the argument, else `origin/<default branch>`. Confirm the branch is not `main`/`BASE`'s
  branch and the working tree is clean (commit or ask about strays first).
- `git fetch origin` then use `origin/...` refs directly. Do **not** `git branch -f
  main`: main is checked out in another worktree, so that fails. If the branch is
  behind `BASE`, merge it in (no rebase) and resolve conflicts now.
- Record the review set once: `git diff --name-only BASE...HEAD` (the "changed files").
  Empty set → stop and say so.
- Baseline: run `FAST`. Red for reasons unrelated to
  this branch → note it and continue; compare later runs against it.
- `agent-phase.sh REVIEW` (no-ops outside a bg session; don't report it).
- Review rounds feed the statusline: at the start of round k run
  `~/.claude/skills/review-comments/review-state.sh --set-local "<k-1>*"`, and when it ends (after the commit step, or at once if
  nothing changed) `--set-local <k>`.

### 2. Review cycle (at most 5 rounds)

Each round:

1. **Review.** Launch a fresh `Agent` (`subagent_type: branch-reviewer`) every round;
   the implementer never reviews its own work. Lean prompt, do not pre-read code for it.
   **Round 1 only**, add the design question below to the prompt; later rounds omit it:

   > FIRST answer the higher-level question: is this the right software architecture or
   > design pattern for the problem/feature this branch implements, or is there a
   > fundamentally better way? Start your report with one line, `DESIGN: sound` or
   > `DESIGN: unsound | <why> | <better approach>`. Mark unsound only if you can name
   > a concrete better alternative and the cost of keeping the current one. Then do the
   > detailed review below.

   Base prompt:

   > Review the branch in the current directory for realistic correctness bugs, missed
   > edge cases, test gaps, and violations of architecture rules stated in the project's
   > CLAUDE.md. Scope strictly: `git diff BASE...HEAD` (BASE=<ref>). Use the
   > `code-review` skill at medium effort with that explicit target if available.
   > Read-only: do NOT edit, commit, or push. Report at most 10 findings, most severe
   > first, one block each: `file:line | problem | concrete failing input/caller |
   > minimal fix`. Say "no findings" if none. No praise, no summaries.
   >
   > Already triaged (don't re-raise without new evidence): <one line each, or "none">

2. **Design gate** (round 1 only). `DESIGN: unsound` → halt the cycle: make no fixes
   and no commits, then `AskUserQuestion`, self-contained: the reviewer's reasoning, the
   proposed alternative, the cost of keeping vs. changing, your recommendation, and the
   detail findings (one line each). Options: continue the cycle as-is / rework the
   design (Other: instructions). Only `sound` proceeds.
3. **Triage** (no asking). Discard findings outside the changed files. **Fix** only
   findings with a plausible real caller/input that reaches the failure. **Skip**
   far-fetched, purely stylistic, or costlier-than-the-problem findings. Record each
   skip as one line for the next round's "already triaged" list.
4. **Fix.** TDD per CLAUDE.md: a failing test first for each behavior bug. Keep fixes
   minimal; no scope growth.
5. **Validate.** Re-run `FAST`. Red → fix before
   committing. Never skip, disable, or quarantine a test to get green.
6. **Commit** the round locally: `Review round <k>: <what changed>` (follow the project's
   commit/ticket prefix convention, if any), with the attribution trailer. No push.
   If the round changed nothing, skip the commit.
7. **Continue?** Stop when the round had no actionable findings or only diminishing
   returns (nits, repeats of skipped items). Otherwise next round with the updated
   triaged list.

### 3. If round 5 still finds significant problems

No sixth round. Review the approach of the whole branch instead: root cause of the
recurring findings (wrong abstraction, boundary violation, missing invariant, scope
creep). Then `AskUserQuestion`, self-contained: per-round found/fixed/skipped, what is
still open, suspected structural cause, 1–2 options with a recommendation.

### 4. On completion

1. `agent-phase.sh --no-review` (REVIEW → REVIEWED; `open-pr.sh` restores `REVIEW` if a
   bot will review).
2. Run `FULL` once; re-run only failures.
3. Report: rounds run; fixed / skipped (with reasons) / real-but-out-of-scope findings
   (listed only: don't open issues or implement them); suite status; commits added.
4. Next step: `/open-pr` (it defaults to `--review none` while `~/.config/local-review-only`
   exists), where that command exists. Put the review-cycle summary in the PR body's "Review cycle" note.

## Rules

- No mid-cycle questions except the round-1 design gate and Step 3.
- No history rewriting; add commits.
- Chat output terse: one line per round (`R<k>: N fixed / M skipped`).
- Scratch files: use the project's convention (CLAUDE.md), not shared `/tmp`.
