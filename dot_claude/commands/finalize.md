# Finalize & Clean Up a Merged Branch

Post-merge housekeeping for a feature branch: verify the PR merged, confirm the ticket
closed, sync the base branch, remove the worktree + branch. Run from the worktree of the
branch you just merged. Makes **no code changes**.

## Steps

### 1. Check

```bash
finalize-check.sh
```

One read-only call answers every mechanical question. It prints:

```
branch= ticket_id= ticket_scheme= base= pr_number= pr_state= pr_merge_commit=
pr_head_oid= head_oid= head_matches= merged= base_worktree= worktree= verdict=
agent_phase=
```

If `agent_phase` is non-empty, stamp it before the slower steps run so the agent-view row
matches reality: `agent-phase.sh "$agent_phase"`. Empty means the verdict was "stop and
look" — leave the label alone rather than relabelling a branch that needs attention.

Act on `verdict`:

- **`ready`** — PR merged, branch is an ancestor of `origin/<base>`, local tip matches the
  PR head. Continue to step 2.
- **`no-pr`** / **`not-merged`** — **stop.** Report that there's nothing to finalize yet.
- **`local-commits`** — **stop.** The local tip is ahead of the merged PR head: there's
  work here the PR never contained. Report it (`git log <pr_head_oid>..HEAD`) and delete
  nothing.
- **`squash-merged`** — the PR says merged but the branch isn't an ancestor, which is
  normal for squash/rebase merges. Say which signals disagreed and confirm before
  deleting anything.
- **`unknown`** — couldn't determine (no `gh`, non-GitHub host, no resolvable base).
  Check that host by branch name yourself; if you still can't confirm the merge, stop.

### 2. Confirm the ticket is closed

Use `ticket_id` and `ticket_scheme` from step 1.

**GitHub** (`ticket_scheme=github`):
```bash
gh issue view <ticket_id> --json state,title,parent
```
If `OPEN`, the `Closes #N` link didn't fire — close it pointing at the merge:
`gh issue close <ticket_id> --comment "Landed in <pr_merge_commit> (PR #<n>)."`
Note any `parent` epic's sub-issue progress for the report.

**Shortcut** (`ticket_scheme=shortcut`): reads are fine either way, but use the **MCP
tools** for anything that writes — `short story update --state` prints `Error fetching
story NaN` and still exits 0, so a scripted change reports success having done nothing.

- Read with `mcp__shortcut__stories-get-by-id`.
- If not already done-type, `mcp__shortcut__workflows-get-default` (story's team id)
  returns states with a `type`. Several may be done-type ("Merged to Development", "On
  Release Candidate (Staging)", "Completed") — merging to the base branch usually means
  the **first** of those, not "Completed". If more than one is plausible and the repo
  config doesn't say, **ask** — overshooting misreports release status.
- Apply with `mcp__shortcut__stories-update` (`workflow_state_id`), then read it back.

If the MCP tools aren't available, say so and tell the user which state to set by hand —
don't fall back to the CLI, which would silently no-op.

### 3. Sync the base worktree

```bash
git -C <base_worktree> pull --ff-only
```

If `base_worktree` was empty, or this session is worktree-isolated and refuses to run git
against another worktree: skip it and tell the user to run it themselves. Don't force it.

### 4. Remove this worktree and branch

You cannot remove the worktree you're standing in.

- If the session entered via `EnterWorktree`, call `ExitWorktree` with `action: "remove"`.
  It only deletes the branch under the name it was *created* with — if renamed since, run
  `git branch -D <current-branch>` afterwards.
- Otherwise:
  ```bash
  cd <base_worktree>            # or any other worktree; never the bare root
  git worktree remove <worktree>
  git branch -D <branch>        # -D is safe: step 1 proved it's merged
  ```
- **Dirty tree** → list what's dirty and **stop**; don't discard uncommitted work.
- **Locked** (a background agent-view session holds a lock on its worktree) → don't force
  with `-f -f`. Stopping the session doesn't clear the lock, so the retry fails the same
  way. Report that the user must stop this session (`Ctrl+X` on its row in `claude
  agents`, or `claude stop <id>`), then run `git worktree unlock <worktree>` before the
  remove + branch delete themselves.

### 5. Mark the session done

```bash
agent-phase.sh DONE
```

Last, and only if step 4 actually completed — `DONE` tells the user nothing remains in
this session. If cleanup was skipped or blocked (dirty, locked, worktree-isolated), leave
the phase at `MERGED` and say what's outstanding.

### 6. Report

```
Finalized <ticket-ref> — <title>
- PR #<n> merged as <pr_merge_commit>
- Ticket state: <closed | just set to "<state>" | was already "<state>">
- Worktree removed: <path>
- Branch deleted: <branch>
- <base> worktree: synced / needs `git -C <path> pull --ff-only`
- Epic <parent-ref>: <x>/<y> sub-issues done; remaining: <...>   (GitHub, if parented)
- Follow-ups: <anything noticed>
```

`<ticket-ref>` uses the scheme's dialect (`#42`, `sc-74085`). Report the ticket state you
**read back** after writing, not the one you intended to set.
