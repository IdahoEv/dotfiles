# Sessions and workstreams

A **session** is one agent session. Every session you run or want to monitor gets a record, and sessions are the main thing you triage.

A **workstream** is one unit of agent-implemented work toward a change that lands on the base branch, with or without a PR. It keeps one identity from the commitment to change code until it is finished or dropped, and it owns its name. Its ticket, branch, worktree, sessions, host and PRs can change.

This is the target model, not a description of the current code. Where an older doc or ticket disagrees, this one wins. [Record lifecycles](workstream-lifecycle.md) defines how both records are created, ended and destroyed.

## Identity and lifetime

| Topic | Decision |
| --- | --- |
| Start | When there is a commitment to change code. Starting at session launch is an acceptable fallback. |
| End | Explicitly finished or dropped. A merge completes a step and ends nothing. |
| Major rethink | Drop it and start a new one. Nothing is carried over until a real case needs it. |
| ID | Permanent, and independent of the slug and ticket. |
| Kinds | One. A ticket, interactive iteration and a promoted talk are ways to start. A ticket is optional, and several can be chained. |
| Talk and iterate tags | Talk and iterate sessions stay recognisable through a visible tag, in the title or elsewhere. A talk promoted to work is retagged implement. A tag changes nothing in the model; [setting talk or governor](workstream-lifecycle.md#purpose) removes a session's workstream link. |
| Repos | Each workstream belongs to exactly one repo, and a repo can have several. Related workstreams share a group label, which has no steps, shared context or merge order. |

## Two records

| Record | Applies to | Holds | Lasts |
| --- | --- | --- | --- |
| Session | Every session | ID, purpose tag, tool, role, project, transcript location, activity, attention details and an optional workstream ID | While it needs to be monitored, resumed or handed off |
| Workstream | Work meant to change code | ID, slug, tickets, branch, PRs and setting overrides | Until finished or dropped |

- The two are separate records because work outlives sessions and several sessions can share it. A new agent session gets a new session record linked to the same workstream. Resuming a session keeps its record.
- The link goes one way: a session stores the workstream ID, and the workstream keeps no session list. Shared details live only in the workstream.
- A purpose tag such as talk, governor, project review, iterate or implement helps the user tell sessions apart. It does not create a different record type.
- Governor and talk sessions have no workstream, even when a governor session makes a small direct change.
- A project review session is monitored and logged like any other. One running unattended asks for attention only when it is stuck or has something for the user.
- A workstream supports one lead session, plus any number of helpers and subagents. The lead is the session responsible for moving the workstream forward, whether or not it is running. The data format must not rule out more than one lead.
- Collect what tools can detect. Agents add only what they alone know, such as what they need from the user.

### Edge cases

A session without a workstream and a workstream without a running session are both normal. Orphaned records and unfinished worktrees will also happen. The tools handle the usual path, agent switches and ordinary waiting work. They do not try to detect or repair every other case, and some are left to manual cleanup. This is deliberate, to keep the system small.

## Steps and blocking

The step list is the default happy path, used much like a default prompt. The agent follows it while work goes as expected. What the user says in the session overrides it, such as asking for an extra review round.

- There are default steps, and users can define their own. Steps are optional, can run in parallel, and can differ by project or by workstream.
- Any step can be added, skipped, repeated or jumped back to at any time. A workstream can have several PRs.
- A step can be required. A block applies only when settings declare it, and the defaults declare none. An agent cannot waive a required step on its own, but the user's explicit instruction can.
- The user can list every active block with the settings file that added it. A refusal names that source and how to override it.
- Adding, tightening, removing or weakening a block needs the user's approval. This applies to prompts too, where an agent can otherwise write a new "refuse if" rule that no settings list shows.

### Unproven: tracking step status

An earlier design had each workstream keep a list of planned steps, each marked pending, active or done. **This is unproven and not approved for building.** It must be kept accurate to be useful, and no use for it has been established yet.

The simpler alternative to try first keeps no tracked plan. Progress is the latest reported activity and review results, plus PR status from GitHub. Nothing needs resetting when work jumps back. It cannot reliably show what is left to do or whether a required check was missed, so required checks need separate enforcement.

## Attention

Attention mostly belongs to sessions, which report when they need the user. A workstream adds its own causes, such as a PR waiting to be merged with no agent running. The data keeps the cause, what is being asked, how long it has waited, what it holds up and the asking agent's estimate of the effort to answer. That is enough for an agent to help sort the queue.

## Records and storage

| Topic | Decision |
| --- | --- |
| Contents | A fact belongs in a record only if something needs it during the work and cannot cheaply and reliably get it elsewhere. |
| Lifetime | Temporary. By default only telemetry outlives sessions and workstreams. |
| Telemetry | Every session is logged, with or without a workstream. Each event must make sense without the records, so it carries IDs plus details such as repo and tickets. Dropped is a different outcome from finished. |
| Workstream storage | In the worktree. |
| Session storage | **Tentative:** one folder per host for all sessions, `~/.local/state/workstream/sessions/<session-id>.json`. A database may replace it if the system outgrows files. |
| Access | All reads and writes go through workstream commands, so storage can change. |
| Updates | Workflow commands. For exceptions, the user asks in plain words and a general editing command, which the user can also run, makes the change. |
| Authority | git and GitHub are right about their own facts. The workstream record is right about the slug, tickets and setting overrides. |
| Surprises | When a record and git or GitHub disagree unexpectedly, pause, flag it, suggest a fix and wait. |
| Expected changes | The record picks them up without asking. |

A change is **expected** only when it fits the next step on the happy path and leaves no work or required check behind. If unsure, ask. Syncing only updates the record: it authorizes no merge, and picking up a merge neither finishes the workstream nor removes its worktree.

| Update without asking | Pause and ask |
| --- | --- |
| A push changes the PR's latest commit | The branch gets unexpected commits, such as someone else's |
| A PR is opened from the workstream's branch when none is open | A different or second open PR appears unexpectedly |
| The PR is merged when merging is next | It is merged with a required step unfinished or local commits unpushed |
| GitHub deletes the remote branch after a normal merge | The PR is closed without merging, or an unmerged branch disappears |
| | The local branch is renamed, or the worktree is on a different branch |

## Names

- One slug supplies the branch, worktree, session and PR names through per-surface formats. An optional fuller title defaults to the slug.
- A ticket's own slug is used if it has one. Otherwise one is drafted at kickoff, close to the ticket title. A chain normally gets a new slug.
- Renaming is expected only soon after creation. After publishing, the session name, statusline and PR title follow a rename. The branch and worktree keep the old name, and the tool says so. A forced change of those is done by hand until a real case needs more.

## Switching agents and hosts

- The user switches agents with one command. The switch must work when the old agent cannot respond.
- The new agent gets the workstream record, ticket, code and old transcript. There are no progress notes or generated summaries for now. The transcript's location is therefore recorded when a session starts, and the old session record is kept until the handoff no longer needs it.
- Moving a workstream between hosts must stay possible. It will be built later.
- Seeing work across hosts is fairly urgent. Before building an aggregator, find out how far herdr or a similar tool gets, possibly with session names that show a few workstream attributes as emoji.

## Settings and code boundaries

- The workstream record is the top [settings layer](workstream-config.md#layers): a value set there applies to that workstream only. Per-workstream changes are expected to be rare. The record holds only settings that differ from the lower layers, and everything else follows current settings. Actual branch and worktree names are stored as facts. If step tracking is built, kickoff would also copy the step list into the record.
- Setup tools (kickoff, worktree management, cleanup) and delivery tools (review, PR, merge) may call the record code. The record code never depends on them.
- The tool serves its author's needs first and stays configurable enough to extend to other users and workflows. How to package it for others is deferred.

## Worked cases

| Case | What happens | Not yet decided |
| --- | --- | --- |
| A design is rejected | The workstream is dropped and logged as dropped. The user chooses what happens to the old branch, PR and worktree. A replacement gets a new ID and usually a new ticket. | Whether to link the two. |
| A design fails during review | The user and agent go back to planning, then implementation. Reviews that no longer apply are run again. | Whether that happens automatically or on request. |
| Fixes are left unpushed after a merge | The workstream is still open. A second PR is added, on the same branch or a new one, then reviewed and merged. | |
| A trivial ticket | The user asks for one local review round and nothing more. A required step needs an explicit waiver. | |
| A security-critical project | Project settings add an external audit as a third review and can mark it required. | How a required check is enforced without tracked steps. |
| Quota runs out | One [takeover command](workstream-lifecycle.md#lead-check-and-takeover) starts a new lead session, linked to the same workstream, from the old transcript. The old session is marked ended. | How to find each tool's transcript where its hooks don't report it. |
| A change spans two repos | Two workstreams, each with its own agent, reviews and PRs, share a group label. The user coordinates them. | |
| A talk turns into work | A new workstream is created, and the existing talk session record links to it, keeping its context. It is retagged implement. | How earlier discussion cost is tied to the workstream. |

## Open

- Data formats for the session record, workstream record and any status report. No reader of a snapshot has been settled.
- Whether to track step status at all.
- Session storage: whether herdr already covers it, and whether sandboxed agents can write to the folder. Age alone does not show that a session is dead.
- The unverified agent signals in [record lifecycles](workstream-lifecycle.md#triggers-by-agent).
- Where workstreams live: the worktree is the current decision. A per-host folder remains an option now that sessions need one.
- Collecting records from other hosts, to be investigated separately.
- What herdr supports: a view across hosts, emoji in names, renaming and session status. None of this is verified.
- Attention: a stored level with a reason, or urgency computed from the stored details.
- The rest of the settings layer design in [workstream-config.md](workstream-config.md), which is still to be reviewed.
- What the slug of a workstream without a ticket is drafted from.
- How existing tickets, open PRs and the current tag design change to fit this model. The tags can serve as a compact view of steps and attention, but a fixed set of review sources and a single flag cannot be the underlying data.
