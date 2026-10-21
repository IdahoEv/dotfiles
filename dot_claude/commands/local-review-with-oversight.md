# Local Review Cycle

Replaces the Copilot PR-review loop on machines where Copilot is unavailable (the home
machine, marked by `~/.config/local-review-only`; at work Copilot/CodeRabbit still run, so
use `/open-pr` + `/review-comments` there instead): a **fresh reviewer
subagent** reviews the branch, the implementing session triages and fixes its findings,
and the cycle repeats until it stops being worth the effort. Runs *before* `/open-pr`;
no PR is needed.

## Usage

```text
/local-review-with-oversight
```

Run it from the ticket's worktree once the implementation is done and tests pass.

## Rules

- **The implementing session never reviews its own work.** Every round launches a new
  reviewer via the `Agent` tool (a fresh agent each round, so no round inherits the
  previous reviewer's blind spots).
- **Round cap: 5.** The implementing session decides when another round isn't worth it.
  Going past round 5 requires the user's approval via `AskUserQuestion` (state the
  outstanding findings in the question).
- **Stop early** when a round yields no valid findings above nit level, or only findings
  you are deferring. Say so; don't run a round just to confirm.
- Commits follow the project rule: show what changed and get approval first. Use the
  self-contained approval question described below.

## Steps

### 0. Phase

```bash
agent-phase.sh REVIEW
```

(`open-pr.sh` sets this later too; setting it now makes the agent-view row show that the
ticket is in review.) Skip if it's already `REVIEW`. Review rounds feed the statusline: at
the start of round k run `~/.claude/skills/review-comments/review-state.sh --set-local "<k-1>*"`, and when it ends `--set-local <k>`.

### 1. Launch the reviewer (each round)

Use the `Agent` tool, `subagent_type: branch-reviewer`, with a **lean** prompt (don't
pre-read the code for it):

> Review the changes on this branch for correctness bugs, missed edge cases, test gaps,
> and clear simplification opportunities. Scope: everything differing from the base
> branch, including uncommitted changes (`git diff $(git merge-base HEAD origin/main)`
> plus untracked files). Run the `code-review` skill at `high` effort if available.
> Read-only: do NOT edit files, commit, or push. Report a numbered list of findings,
> most severe first. For each: file:line, what's wrong, a concrete failure scenario, and
> a suggested fix. Say "no findings" if there are none.
>
> Already triaged in earlier rounds (don't re-raise unless you have new evidence):
> <one line per dismissed/deferred finding, or "none">

**Round 1 only**, prepend to that prompt: "FIRST answer the higher-level question: is
> this the right software architecture or design pattern for the problem/feature, or is
> there a fundamentally better way? Start your report with `DESIGN: sound` or
> `DESIGN: unsound | <why> | <better approach>` (unsound only if you can name a concrete
> better alternative and the cost of keeping the current one). Then do the detailed
> review." If the verdict is `unsound`, make no fixes or commits this round: put the
reasoning and alternative in the step-3 `AskUserQuestion` (options: continue as-is /
rework the design / Other) and wait.

Round 2+ omit the design question and differ only in the triaged-findings block. Working directory is the ticket's worktree.

### 2. Triage

For each finding decide: **fix**, **dismiss** (explain why: false positive, already
handled, contradicts a project decision), or **defer** (real but out of scope: open a
GitHub issue under the right epic/milestone per the project's bookkeeping rule, don't
grow the branch). Apply fixes (TDD where it's a behavior bug), then run build and tests
quietly (`--logger "console;verbosity=quiet"` for `dotnet test`).

Disagreements that need the user's judgment (design intent, scope) go in the approval
question; don't silently dismiss them.

### 3. Report and ask: one self-contained question

Print the round report as text (findings list, the structured table below, a line per
fix, validation status, proposed commit message), **and put the same content inside one
`AskUserQuestion` call**. Text written before the call may not be shown, so the question
text itself must contain: the reviewer's findings (one line each), the verdict table,
what was fixed, validation status, and the full commit message. Options:

- "Commit and run another round" — only offer when you think another round is worth it
- "Commit and finish review" (Recommended when this round's fixes were small)
- "Don't commit yet"
- (Other: custom commit message or instructions)

`preview` on the commit options = the full commit message.

Table format (a leading and trailing `---` rule around it):

| # | Location | Finding | Verdict |
|---|---|---|---|
| 1 | `path:line` | terse description | ✅ fixed / ❌ dismissed — reason / ⏭ deferred — Is#N |

If a round has fixes only for dismissed/deferred findings (no file changes), skip the
commit option and just ask whether to run another round or finish.

### 4. Commit, then loop or finish

On approval: `git add -A`, commit with the approved message (append the Co-Authored-By
trailer from the session's attribution reminder), and **do not push**. Then:

- Another round chosen and round number < 5 → back to step 1 with the updated
  triaged list.
- Round 5 reached and you still want more → `AskUserQuestion` for approval first.
- Finished → run `agent-phase.sh --no-review` (sets `REVIEWED`; `open-pr.sh` restores `REVIEW` if a bot
  will review), then report: rounds run, findings fixed/dismissed/deferred, issues opened.
  Then continue with `/open-pr` (it defaults to `--review none` here).
