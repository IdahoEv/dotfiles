# Start a Ticket

Prepares a worktree + kickoff for a tracker ticket and opens a Claude session for it.
Takes a ticket id (`/start 22`). No id → list the repo's open tickets and ask which one.

Ticket tracking is provider-based (**GitHub issues** or **Shortcut stories**), resolved
per-repo by `start-ticket.sh`. Don't assume which; all ticket-state operations go through
the script and its providers, never raw CLI calls, except the enrichment queries in step 2
and the Shortcut repair in step 1a.

## Steps

### 1. Setup

```bash
start-ticket.sh <id> --no-tab
```

Creates the worktree, marks the ticket in progress, and writes a kickoff from the repo's
`.claude/kickoff-preamble.md` (which carries the project's working agreement, so this
command doesn't). Prints parseable `key=value` on stdout — capture all of it:

```
worktree= kickoff= branch= provider= ticket_state= ticket_in_progress= ticket_parent=
```

Non-zero exit (ticket not open, no provider, CLI not authed) → **stop** and report why.
An already-existing worktree still succeeds.

### 1a. Repair the ticket state, only if needed

The script already read the state back, so trust `ticket_in_progress`:

- **`yes`** — done. No tool calls.
- **`no` / `unknown`** — the write didn't land (on Shortcut this is expected: the `short`
  CLI's state-set prints `Error fetching story NaN` and still exits 0). Repair it:
  - **GitHub** — `gh issue edit <id> --add-assignee @me`, reopening if needed.
  - **Shortcut** — use the MCP tools, never the CLI: `mcp__shortcut__stories-get-by-id`,
    then `mcp__shortcut__workflows-get-default` (pass the story's team id) to resolve the
    started-state id, then `mcp__shortcut__stories-update` with `workflow_state_id`.
    Prefer the state named in `.start-ticket.conf`'s `shortcut_in_progress_state`.

Don't block on this — if the state can't be set, say so in the report and continue.

### 2. Enrich the kickoff (tracker facts only)

Read the kickoff file and append a short `## Context` section. **Do not open or read source
files** — pre-reading puts them into context three times (ticket author → here →
implementer), and the implementer session can find them itself. Limit to:

- **GitHub** — parent epic (`ticket_parent` from step 1) + its still-open siblings:
  ```bash
  gh issue view <parent> --json title,subIssuesSummary,subIssues \
    -q '"\(.title) (\(.subIssuesSummary.completed)/\(.subIssuesSummary.total))",
        (.subIssues.nodes[] | select(.state=="OPEN") | "#\(.number) \(.title)")'
  ```
- **Shortcut** — read `<worktree>/.ticket.local.md`; note any epic or linked stories (no
  bulk sub-issue progress query exists — skip that line rather than approximating).
- **Dependencies** (either provider) — `Depends on #X` / `Blocked by #X` / linked-story
  refs in the ticket body: fetch each one's state, warn if open, don't block. This is the
  one fact worth the round-trip, since ticket text can't tell you a blocker has closed.

Write the enriched kickoff back to the same path.

### 3. Open the session

```bash
start-ticket.sh --tab-only "<worktree>" "<kickoff>"
```

Never pass `--launcher`; the script resolves it from the user's per-machine config.
What you need for the report: **`iterm`** opens a tab with the kickoff typed but
unsubmitted; **`bg`** starts a background session (findable in `claude agents`) with the
kickoff submitted immediately; **`none`** starts nothing. If a `bg` launch fails over
workspace trust, the script prints a one-time `cd <worktree> && claude` fix — relay it.

A `bg` session is named `[PLAN] <slug>` — the ticket's **workflow phase**, a third state
axis in the agent view beside `status` (idle/busy) and `state` (working/blocked/done).
`agent-phase.sh <PHASE>` sets it; it no-ops outside a bg session.

| Phase | Means | Set by |
|---|---|---|
| `PLAN` | awaiting plan approval | `start-ticket.sh` at launch |
| `WIP` | plan approved, implementing | the ticket session itself |
| `REVIEW` | PR open | `open-pr.sh` |
| `MERGED` | merged, ready to finalize | `/finalize` step 1 |
| `DONE` | finalized; safe to kill | `/finalize` last step |

`PLAN → WIP` is the one transition no script can see, and it belongs to the ticket
session — `/start` has exited by the time the plan is approved. That rule lives in the
global CLAUDE.md so it applies however the session was launched. The phase is
self-reported: a session that dies mid-ticket keeps a stale label, and `/board`
recomputes true state from git + the tracker when they disagree.

### 4. Report

Worktree path, branch, ticket state (report `ticket_state` as read back, not what you
intended), and for GitHub with a parent epic, its sub-issue progress and remaining
siblings. Under `bg`, say the session is running in `claude agents` and shows as
`[PLAN]` until its plan is approved.
