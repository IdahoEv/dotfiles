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
produced (commonly `<username>/sc-<id>/<slug>`, or `sc-<id>/<slug>` once
`worktree-manager.sh` strips the username segment). Take the **last** `sc-<id>`
in the branch name as the story id — a follow-up branch can mention several.

Shortcut tracks stories, not PRs, but that says nothing about where the code is
reviewed: these repos normally still host PRs on GitHub, so the same `gh` query
works and is the first thing to try.

```bash
gh pr list --head "$(git branch --show-current)" --state all --json number,state,mergedAt,mergeCommit,title
```

Don't parse `Closes #N` from the body here — Shortcut-tracked repos have no
GitHub issue namespace, so any `#N` in the body is a PR reference, not the
ticket. The story id comes from the branch name only.

If `gh` isn't the right host for this repo (GitLab, etc.), check that host by
branch name instead. If you can't confirm the branch merged, **stop** and report
that, same as the GitHub case.

### 2. Verify the merge landed on the base branch

Resolve the base branch first — don't assume `main`:

```bash
# host-neutral: read origin's default branch (works on GitHub, GitLab, ...)
base="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
# fall back to the host CLI only if that's unset (GitHub shown; adapt for other hosts)
[ -n "$base" ] || base="$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)"
git fetch origin "$base"
git merge-base --is-ancestor "$(git branch --show-current)" "origin/$base" \
  && echo MERGED || echo NOT-MERGED
```

Local base branch is frequently stale, so always check against `origin/<base>`,
never the local ref. If this prints `NOT-MERGED`, **stop** and report — do not
delete anything. (A squash- or rebase-merged PR won't be an ancestor even though
it landed: if step 1 showed the PR `MERGED` but this says `NOT-MERGED`, say which
signal disagreed and confirm before deleting anything. Before trusting the PR
state, also verify the local tip is the PR's head — the PR only proves its
remote head merged, not commits added locally afterward:
`[ "$(git rev-parse HEAD)" = "<PR head OID>" ]`. Get the head OID from the
active host's PR/MR (GitHub: `gh pr view --json headRefOid -q .headRefOid`;
other hosts: the equivalent field from their CLI/API).
If the tip differs, **stop** and report the local-only commits
(`git log <PR head OID>..HEAD`) instead of deleting.)

Carry `$base` forward — steps 4 and 5 both need it.

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

**Shortcut:** use the Shortcut **MCP tools**, not the `short` CLI, for anything
that writes. Reads are fine either way (`short story <id> --quiet` works), but
`short story update <id> --state …` is **known broken** — it prints `Error
fetching story NaN` and still **exits 0**, so a scripted state change reports
success having done nothing.

- Read the current state with `mcp__shortcut__stories-get-by-id`.
- If it isn't already a done-type state, resolve the target:
  `mcp__shortcut__workflows-get-default` with the story's team id returns the
  workflow's states, each with a `type` (`backlog` / `unstarted` / `started` /
  `done`). Pick the done-type state the workspace actually uses for merged work
  — several may be done-type (e.g. "Merged to Development", "On Release
  Candidate (Staging)", "Completed"), and merging to the base branch usually
  means the *first* of those, not "Completed". If more than one is plausible and
  the repo config doesn't say, ask rather than guessing — overshooting the state
  misreports release status.
- Apply it with `mcp__shortcut__stories-update` (`workflow_state_id`), then read
  it back and report what it actually is.
- Note any parent epic for the final report.

If the Shortcut MCP tools aren't available in this session, say so and tell the
user which state to set by hand — don't fall back to `short story update`, which
would silently no-op.

### 4. Sync the base-branch worktree

The base-branch worktree lives at `<repo-parent>/<base-branch-name>` (sibling of
this worktree; `git worktree list` shows it). Resolve the base branch rather than
assuming `main` — `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`,
or the `HEAD` entry in `git branch -r`. It is frequently neither `main` nor
`master` (`development` is common), and every earlier step that compares against
`origin/<base>` depends on getting this right.

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
- If it reports the worktree is **locked** (a background agent-view session may
  hold a lock on its worktree), don't force it with `-f -f`. Stopping the session
  doesn't clear the lock by itself — `git worktree remove` would just fail again
  with the same error. Add a line to the final report telling the user to stop
  this session (`Ctrl+X` on its row in `claude agents`, or `claude stop <id>`),
  then run `git worktree unlock <this-worktree-path>` before
  `git worktree remove <this-worktree-path>` and `git branch -D <branch>` themselves.

### 6. Report

```
Finalized <ticket-ref> — <title>
- PR/MR #<n> merged as <mergeCommit>
- Ticket state: <closed | just set to "<state>" | was already "<state>">
- Worktree removed: <path>
- Branch deleted: <branch>
- <base> worktree: synced / needs `git -C <path> pull --ff-only`
- Epic <parent-ref>: <x>/<y> sub-issues done; remaining: <...>   (only if parented, GitHub only)
- Follow-ups: <anything noticed, e.g. deferred tickets>
```

`<ticket-ref>` uses the provider's dialect (`#42`, `sc-74085`, …). For the ticket
state line, report the state you **read back** after writing, not the one you
intended to set — on Shortcut especially, "closed" is not a state name and a
write that appeared to succeed may not have landed. If you couldn't change it,
say so explicitly and name the state it's still in.
