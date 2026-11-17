# Sync the branch with its base

Brings `origin/<base>` into this feature branch and pushes. Run from the ticket's worktree.
The model is needed only when the merge conflicts.

## Steps

### 1. Run

```bash
sync-run.sh
```

Act on the exit code:

- **0** — relay the printed line and stop. Write no report.
- **1** — precondition failed (dirty tree, detached HEAD, on the base branch, a merge
  already in progress, bad `sync_method`): relay stderr and stop.
- **3** — `handoff=<reason>`, with `files=`, `base=`, `method=`:
  - `conflict` — the merge (or rebase) is left in place. Go to step 2.
  - `push-failed` — the merge is committed locally but not pushed (usually the remote
    branch has commits this one lacks; a rebase stops before rewriting in that case).
    Report `detail=`; do not force-push. Once the user reconciles the remote, `sync-run.sh --finish`
    retries the push; a plain re-run prints "up to date" without pushing.
  - `unresolved` — paths still conflicted after `--finish`, including the next commit of a
    multi-commit rebase; `files=` lists them. Return to step 2.

### 2. Resolve conflicts

Read each file in `files=`, resolve it, and `git add` it. Judge each resolution:

- **Risky** — both sides changed logic, or you chose between behaviours. Run the project's
  relevant tests before finishing.
- **Not risky** — adjacent edits, imports, lockfiles or other generated files. Skip the tests.

If you cannot resolve a file with confidence, or the tests fail, stop: leave the merge state
as it is, describe it (files, what each side did, the failing test), and push nothing.

Otherwise run `sync-run.sh --finish`; it completes the merge and pushes.

### 3. Report (conflict path only)

```
Synced <branch> with <base>: conflicts resolved
- Conflicted files: <files>
- Tests: <ran: <command> → pass | skipped: <why the resolution was not risky>>
```
