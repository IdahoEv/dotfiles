# Start a Ticket

Prepares a worktree + kickoff for a tracker ticket and opens a Claude session for it.
Takes a ticket id (`/start 22`). No id → list the repo's open tickets and ask which one.

Ticket tracking is provider-based (**GitHub issues** or **Shortcut stories**), resolved
per-repo by `start-ticket.sh`. Don't assume which; all ticket-state operations go through
the script and its providers, never raw CLI calls, except the enrichment queries in step 2
and the repairs in step 1a (raw `gh` on GitHub, MCP tools on Shortcut).

## Steps

### 1. Setup

```bash
start-ticket.sh <id> --print-title     # read-only; creates nothing
start-ticket.sh <id> --no-tab
```

`--print-title` is read-only and prints `title=`, `proposed_label=` and `proposed_slug=`.
Read the title, write the session label yourself — see **Naming** — and export
`GT_LABEL_OVERRIDE` for the `--no-tab` call. Run it first: the label is applied during
`--no-tab`, so one decided afterwards is too late.

Creates the worktree, marks the ticket in progress, and writes a kickoff from the repo's
`.claude/kickoff-preamble.md`, else the per-project overlay's copy. It carries the
project's working agreement, so this command doesn't. Prints parseable `key=value` on stdout — capture all of it:

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

Read the state back through the same provider after repairing it — `ticket_state` from
step 1 was captured *before* the repair, so reporting it unchanged would claim a state the
tracker never reached. Use what you read back in step 4.

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

### Naming

**The session label is yours to write; the branch slug is not.** Two different jobs:

- **Session label** (the agent-view row, the iTerm tab) — what the user scans to pick a
  session out of a list. Nothing matches on it and `agent-phase.sh` rewrites it on every
  phase change, so judgment costs nothing here. **Write it from the title.**
- **Branch slug and worktree directory** — matched against later by `find_ticket_branch`,
  an open PR, and the user's shell history. A name that varies between two runs of the
  same ticket is a bug, so these stay deterministic. `proposed_slug` is informational;
  `GT_LABEL_OVERRIDE` does not affect it.

Set `GT_LABEL_OVERRIDE` to **3–4 title-cased words naming what the work is about** — the
noun phrase, not the activity. No ticket id (the script prepends `Sc<id>`), no
punctuation, no verb unless the verb is the point. Use `proposed_label` when you can't do
better; it comes from a delete-and-slice rule that keeps the last four significant words,
which is usually right but loses the subject when the title is front-loaded:

| Title | `proposed_label` | Write instead |
| --- | --- | --- |
| Rewards structures are wrong in the legacy mapping layer | `Wrong Legacy Mapping Layer` | `Rewards Structures Legacy Mapping` |
| Investigate why the planner drops subjects with no applicable_date | `Subjects No Applicable Date` | `Planner Drops Subjects` |
| [A/L] Decide PERS data deletion & retention policy (member deletion) | `Data Deletion Retention Policy` | use it — already right |

Report the label you chose. If you genuinely need the branch named too (rare — a
deliberate rename, not a nicer wording), `GT_LABEL_SLUG_OVERRIDE` does that; say so in the
report, since it breaks the reproducible-from-ticket-id property.

A `bg` session is named `[PLAN] <slug>` — the ticket's **workflow phase**, a third state
axis in the agent view beside `status` (idle/busy) and `state` (working/blocked/done).
`agent-phase.sh <PHASE>` sets it; it no-ops outside a bg session. The kickoff also asks
the session to run `session-label.sh --color project`, which colors the row with the
project's key color from `project-colors` in `tools/`.

| Phase | Means | Set by |
|---|---|---|
| `PLAN` | awaiting plan approval | `start-ticket.sh` at launch |
| `WIP` | plan approved, implementing | the ticket session itself |
| `REVIEW` | a review (local or GitHub) is running | review commands, `open-pr.sh` |
| `REVIEWED` | review finished, awaiting merge | `agent-phase.sh --no-review` |
| `MERGED` | merged, ready to finalize | `/finalize` step 1 |
| `DONE` | finalized; safe to kill | `/finalize` last step |

A separate `[PR]` tag (set by `open-pr.sh`) compounds with the phase; see global CLAUDE.md.

`PLAN → WIP` is the one transition no script can see, and it belongs to the ticket
session — `/start` has exited by the time the plan is approved. That rule lives in the
global CLAUDE.md so it applies however the session was launched. The phase is
self-reported: a session that dies mid-ticket keeps a stale label, and `/board`
recomputes true state from git + the tracker when they disagree.

### 4. Report

Worktree path, branch, ticket state (report what you read back — step 1a's re-read if it
repaired, else `ticket_state` — never what you intended to set), and for GitHub with a
parent epic, its sub-issue progress and remaining
siblings. Under `bg`, say the session is running in `claude agents` and shows as
`[PLAN]` until its plan is approved.
