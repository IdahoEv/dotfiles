# Finalize & Clean Up a Merged Branch

Post-merge housekeeping for a feature branch: verify the PR/MR merged, confirm the
ticket closed, sync the base branch, and remove the worktree + branch.

Run this from the worktree of the branch you just merged. It makes **no code
changes** — it only verifies state and cleans up.

Ticket tracking is provider-based (GitHub issues or Shortcut stories) — same
resolution as `/start`: check `.start-ticket.conf` in the repo root, else
autodetect from installed CLIs (`gh` vs `short`). Don't assume which one.

## Steps

### 1. Identify the branch, PR, and ticket

```bash
git branch --show-current
```

**GitHub provider:**
```bash
gh pr list --head "$(git branch --show-current)" --state all --json number,state,mergedAt,mergeCommit,body
```
Branch names follow `<issue#>-slug`. Take the leading number as the issue, but also
parse `Closes #N` / `Fixes #N` from the PR body — trust that over the slug if they
disagree. If there is **no PR**, or the newest PR's `state` is not `MERGED`: **stop**.
Report that there's nothing to finalize yet and do nothing else.

**Shortcut provider:** branch names follow whatever `short story --git-branch-short`
produced (commonly `<username>/sc-<id>/<slug>`). Extract the story id. There's no PR
CLI equivalent to check here in the same way — check the repo's actual PR/MR host
(GitHub, GitLab, etc., whichever this repo uses) by branch name, or ask the user
where review happens if it isn't obvious. If you can't confirm the branch merged,
**stop** and report that, same as the GitHub case.

### 2. Verify the merge landed on the base branch

```bash
git fetch origin <base-branch>
git merge-base --is-ancestor <branch> origin/<base-branch> && echo MERGED || echo NOT-MERGED
```

Local base branch is frequently stale, so always check against `origin/<base>`,
never the local ref. If this prints `NOT-MERGED`, **stop** and report — do not
delete anything.

### 3. Confirm the ticket is closed

**GitHub:**
```bash
gh issue view <issue#> --json state,title,parent
```
- If `state` is `OPEN`: the `Closes #N` link probably didn't fire (e.g. PR body
  edited after merge). Close it with a comment pointing at the merge commit:
  `gh issue close <issue#> --comment "Landed in <mergeCommit> (PR #<n>)."`
- If it has a `parent` (an epic), fetch the epic and note its sub-issue progress
  and which sibling issues remain open — this goes in the final report.

**Shortcut:**
```bash
short story <id> --quiet
```
- If the story's state isn't a "done"/"completed"-equivalent state, it likely wasn't
  auto-transitioned on merge (Shortcut's GitHub/GitLab integration handles this in
  some setups but not all) — update it:
  `short story update <id> --state "<done-state-name>"` (state name is
  workspace-specific; check `.start-ticket.conf`'s `shortcut_in_progress_state`-style
  config or ask the user if unsure rather than guessing a state name).
- Note any parent epic named in the story details for the final report.

### 4. Sync the base-branch worktree

The base-branch worktree lives at `<repo-parent>/<base-branch-name>` (sibling of
this worktree; `git worktree list` shows it — usually named `main` or `master`,
but confirm rather than assuming).

```bash
git -C <repo-parent>/<base> pull --ff-only
```

If this session is **worktree-isolated** and refuses to run git against another
worktree: skip it and add a line to the final report telling the user to run
`git -C <repo-parent>/<base> pull --ff-only` themselves. Do not force it.

### 5. Remove this worktree and branch

You cannot remove the worktree whose directory you're standing in.

- If the session entered this worktree via `EnterWorktree`, call
  `ExitWorktree` with `action: "remove"`. Note: `ExitWorktree` only deletes the
  branch under the name it was *created* with — if the branch was renamed after
  `EnterWorktree`, run `git branch -D <current-branch-name>` afterwards to clear
  the leftover, first confirming `git merge-base --is-ancestor <branch> origin/<base>`.
- Otherwise:
  ```bash
  cd <repo-parent>/<base>       # or any other worktree; never the bare root
  git worktree remove <this-worktree-path>
  git branch -D <branch>        # -D is safe: step 2 already proved it's merged
  ```
  (`worktree-manager.sh` does not do removal — this is the manual path.)
- If `git worktree remove` complains about a dirty tree, list what's dirty and
  **stop** — don't discard uncommitted work without asking.

### 6. Report

```
Finalized <ticket-ref> — <title>
- PR/MR #<n> merged as <mergeCommit>
- Ticket closed: yes / just closed / (was already closed)
- Worktree removed: <path>
- Branch deleted: <branch>
- <base> worktree: synced / needs `git -C <path> pull --ff-only`
- Epic <parent-ref>: <x>/<y> sub-issues done; remaining: <...>   (only if parented, GitHub only)
- Follow-ups: <anything noticed, e.g. deferred tickets>
```
