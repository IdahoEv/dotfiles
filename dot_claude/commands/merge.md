# Merge the PR from the session

Merges this worktree's PR on GitHub only if local state is exactly what the PR holds, then
deletes the remote branch. Run from the PR's worktree. Does **not** run `/finalize` (that
is `/land`) and makes no code changes.

## Steps

### 1. Run

```bash
merge-run.sh
```

It runs the sync gate (`sync-gate.sh`), resolves the merge method, merges, verifies the PR
reads `MERGED`, and deletes the remote branch. Act on the exit code:

- **0** — merged. Relay the printed line and any `warning=` line (the branch merged but its
  remote copy remains). Stop; write no report.
- **2** — `stopped=<reason>`, with `reason=`: nothing was merged. Relay the reason in one
  line and stop.
  - `dirty` — list the changed files. Commit and push them, then re-run, **only if the user
    asked you to**; otherwise leave them alone.
  - `unpushed` / `behind-pr` / `diverged` — name the commits that differ
    (`git log <pr_head>..HEAD`, `git log HEAD..<pr_head>`). Push or pull only if the user
    asked.
  - `conflict` — tell the user to run `/sync`.
  - `merge-method-ambiguous` / `merge-method-not-allowed` — name the allowed methods and the
    `merge_method` key (`start-ticket.conf`, project or global).
  - Anything else (`no-pr`, `draft`, `closed`, `already-merged`, `mergeable-unknown`,
    `unknown`, `merge-failed`, `not-merged`) — relay `reason=`; for `already-merged` suggest
    `/finalize`.
- **1** — usage or precondition error: relay stderr and stop.
