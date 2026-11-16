---
description: Run a read-only periodic project review of the default branch using fresh lens agents
argument-hint: "[--force] [--window N]"
---

# Project Review

```text
/project-review               # run if activity gate passes (default 7-day window)
/project-review --force       # bypass activity gate
/project-review --window 14   # override cadence window (days)
```

This session is the launcher. It never inspects the snapshot or runs lenses itself — a fresh `project-review-manager` agent runs the whole review so session history stays out of the lenses. Default mode is read-only with an inline report.

## 1. Preconditions

Resolve the repository (`gh repo view --json nameWithOwner -q .nameWithOwner`), default branch (`repo-facts.sh default-branch`), and absolute working directory (`git rev-parse --show-toplevel` or `pwd`). If not inside a git repository or the default branch cannot be resolved, stop and say so.

## 2. Launch the manager

Launch `project-review-manager`. The kickoff carries only these lines:

```text
Run project-review-procedure on the default branch.
Repo: <owner>/<repo>
Default branch: <branch>
Working directory: <absolute cwd>
Flags: <--force and/or --window N | (none)>
```

Add nothing else: no opinions about the codebase, no suggested findings, no lens overrides. If the agent runs in the background, wait for its completion notice.

## 3. Report

Print the manager's report **unaltered, at top level** — no blockquote, no code fence, tables emitted directly, because quoting or fencing stops the terminal rendering its tables. Do not re-review or second-guess the manager's synthesis.
