---
description: Run the bounded pre-PR review-and-fix cycle on the current branch
argument-hint: "[base] [--confirm-commits]"
---

# Local Review Cycle

```text
/local-review-cycle                  # commit each round, review on the PR
/local-review-cycle --confirm-commits
/local-review-cycle origin/main
```

This session is the launcher. It never reads the diff under review or triages findings — a fresh `local-review-cycle-manager` agent runs the whole cycle, so implementation history stays out of the orchestration. The manager commits each round locally by default and never pushes. `--confirm-commits` holds each round for the skill's approval question instead.

## 1. Preconditions

The implementing session must have committed everything first. Verify with `git status --porcelain` — if the tree is dirty, tell the user to commit or resolve stray changes first and stop. Resolve BASE (the argument, else `origin/<default branch>`); if it doesn't resolve, stop and say so. Record the repo (`gh repo view`), branch, and absolute working directory.

## 2. Launch the manager

Launch `local-review-cycle-manager`. The kickoff carries only these lines:

```text
Run local-review-cycle-procedure on the current branch.
Repo: <owner>/<repo>
Branch: <branch>
BASE: <ref>
Working directory: <absolute cwd>
Ticket: <ticket ref and one-line acceptance criteria | "none — <one-line change summary>">
Flags: --confirm-commits | (none)
Design context: <1–3 lines: the implementer's reasoning behind the diff's shape | omit the line entirely>
```

Add nothing else: no opinions about the diff, no suggested reviewers, no prior verdicts. This session may already hold opinions about the change, and the manager's value is not inheriting them. The agent reads CLAUDE.md, so standing user preferences reach it anyway.

If the agent runs in the background, wait for its completion notice. Don't act on partial output.

## 3. Report

Print the manager's report **unaltered, at top level** — no blockquote, no code fence, tables emitted directly, because quoting or fencing stops the terminal rendering its tables — then say the next step is `/open-pr`, carrying the report's summary into the PR body's "Review cycle" note (rounds, fixed/dismissed/deferred counts, dismissed findings with reasons). Do not re-review or second-guess the manager's triage.
