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
branch= ticket_id= ticket_scheme= base= base_source= pr_number= pr_state=
pr_merge_commit= pr_head_oid= pr_count= pr_open_other= head_oid= head_matches=
merged= merge_commit_landed= base_fetch= shallow= tracking_refspec=
base_worktree= worktree= verdict= agent_phase=
```

`base` is the branch **the PR targets** (`base_source=pr`), falling back to the repo
default when there's no PR to ask (`base_source=default`). On a stacked or
release-branch PR those differ — report the one the script used.
`base_source=default_pr_base_gone` means the PR's base no longer exists on origin (the
normal end state for a merged stacked PR), so the repo default was used instead; the
verdict then describes reaching *that* branch, not the one the PR targeted.

A branch can carry several PRs. The script reports `pr_count`, prefers a
`MERGED` one when choosing which to describe, and lists any **other** open PR in
`pr_open_other` — which forces `not-merged` regardless of what the chosen PR
proves. Name the open PR when you report that stop.

Two of those are health signals rather than facts about the PR, and both are worth
relaying in the report even when the verdict is `ready`:

- **`base_fetch=failed`** — `origin/<base>` could not be refreshed, so every ancestry
  answer above came from a possibly-stale ref. Say so; don't silently treat the verdict
  as freshly-proven.
- **`tracking_refspec=missing`** — the repo has no `remote.origin.fetch`, so
  `refs/remotes/origin/*` never advance on fetch. `finalize-check.sh` compensates
  internally with explicit refspecs, but nothing else does — including the
  `git -C <base_worktree> pull` in step 3 and any `git log origin/<base>` the user runs
  next. Relay the repair command the script printed on stderr.

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
- **`squash-merged`** — the PR says merged, the branch isn't an ancestor, and the merge
  commit **couldn't be checked** (not fetchable, or the base ref couldn't be refreshed).
  Evidence is missing, not negative. An ordinary squash/rebase merge whose commit *is*
  reachable now reports `ready` on its own, so reaching this verdict means a check did
  not complete — don't wave it through as "normal for squash merges". Say which signal
  was unavailable (`merge_commit_landed`, `base_fetch`, `shallow`) and confirm before
  deleting. It leaves `agent_phase` empty for the same reason — don't stamp `MERGED` by
  hand to compensate.
- **`not-on-base`** — **stop.** The PR's merge commit is present locally and provably
  **not** reachable from a freshly-fetched `origin/<base>` — and `<base>` here is the
  branch the PR itself targets (`base_source=pr`; the verdict is suppressed when the
  base had to be substituted), so this is not a stacked-PR false alarm. The base was
  rewritten, or the merge was reverted. This branch may hold the only local ref to work
  that never reached `<base>`. Report `pr_merge_commit` and `base`; delete nothing.
- **`unknown`** — couldn't determine (no `gh`, non-GitHub host, no resolvable base, or
  the PR's head object isn't fetchable so `head_matches` is itself unknown).
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
