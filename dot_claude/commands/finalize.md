# Finalize & Clean Up a Merged Branch

Post-merge housekeeping for a feature branch: verify the PR merged, close the ticket,
sync the base branch, remove the worktree + branch. Run from the worktree of the branch
you just merged. Makes **no code changes**.

## Steps

### 1. Run

```bash
finalize-run.sh
```

It does the whole clean path without a model turn: the `finalize-check.sh` verdict, phase
stamps, GitHub ticket close, base pull, dotfiles deploy, worktree + branch removal, and
disposal of this session. Act on the exit code:

- **0** — done. Relay the printed line (and the reload table, if any) and stop. Write
  no report.
- **2** — `stopped=<verdict>`: nothing was touched. Relay why (`no-pr`/`not-merged`:
  nothing to finalize yet, naming `pr_open_other` if set; `local-commits`: work the PR
  never contained, show `git log <pr_head_oid>..HEAD`; `not-on-base`: the base was
  rewritten or the merge reverted, report `pr_merge_commit` and `base`). Delete nothing.
- **3** — `handoff=<reason>`: the script printed `detail=`, `done=` (steps already
  complete — don't redo them) and the `finalize-check.sh` facts. Resolve just that reason
  (step 2), then re-run `finalize-run.sh` (add `--ticket-closed` after a Shortcut close).

Also relay health signals from the facts, even on exit 0 paths that print them:
`base_fetch=failed` (ancestry answers came from a possibly-stale ref) and
`tracking_refspec=missing` (the repair command is on stderr).

### 2. Handoff reasons

- **`shortcut`** — close `sc-<ticket_id>` with the **MCP tools**, never the CLI (`short
  story update --state` prints `Error fetching story NaN` and still exits 0). Read with
  `mcp__shortcut__stories-get-by-id`; if not done-type, `mcp__shortcut__workflows-get-default`
  lists states with a `type`. Several may be done-type ("Merged to Development", "On Release
  Candidate (Staging)", "Completed"); merging to the base usually means the **first**. If
  more than one is plausible and the repo config doesn't say, **ask** — overshooting
  misreports release status. Apply with `mcp__shortcut__stories-update`
  (`workflow_state_id`), read it back, then `finalize-run.sh --ticket-closed`. Without the
  MCP tools, say so and name the state to set by hand.
- **`squash-merged`** / **`unknown`** — the merge isn't proven: the PR says merged but a
  check didn't complete (`merge_commit_landed`, `base_fetch`, `shallow`), or gh/the base
  couldn't be resolved. Say which signal was missing and confirm with the user before
  deleting anything; check the host by branch name if you can.
- **`unclaimed-ticket`** — an open ticket the PR never closed (a draft PR from a stopped
  chain). Leave it open and report it as unfinished; finish the rest by hand.
- **`ticket-unreadable`** — `gh` failed on the issue or PR. Report the error.
- **`dirty`** — list what's dirty and **stop**; don't discard uncommitted work. If the
  repo has `.claude/finalize-notes.md`, read it first — it may name regenerable files safe
  to discard, and when. Apply only what it states.
- **`locked`** — a background agent-view session holds the worktree. Don't force with
  `-f -f`: stopping the session doesn't clear the lock. The user must stop that session
  (`Ctrl+X` on its row in `claude agents`, or `claude stop <id>`), run `git worktree unlock
  <worktree>`, then remove the worktree and branch (`prune-worktrees.sh` sweeps stale ones).
- **`no-base-worktree`** / **`remove-failed`** — report `detail=`; the user finishes by hand.

### 3. Report (handoff or failure only)

```
Finalized <ticket-ref> — <title>
- PR #<n> merged as <pr_merge_commit>
- Ticket state: <closed | just set to "<state>" | was already "<state>">
- Worktree removed: <path>
- Branch deleted: <branch>
- <base> worktree: synced / needs `git -C <path> pull --ff-only`
- Follow-ups: <anything noticed>
```

`<ticket-ref>` uses the scheme's dialect (`#42`, `sc-74085`). Report the ticket state you
**read back** after writing. If cleanup was blocked, leave the phase at `MERGED` and say
what's outstanding.
