# What a workstream is

A **workstream** is one unit of agent-implemented work toward a change that lands on the base branch, with or without a PR. It keeps one identity from the commitment to change code until it is finished or dropped, and it owns its name. The ticket, branch, worktree, sessions, host and PRs are attached to it and can change.

This is the target model, not a description of the current code. Where an older doc or ticket disagrees, this one wins.

## Identity and lifetime

| Topic | Decision |
| --- | --- |
| Start | When there is a commitment to change code. Starting at session launch is an acceptable fallback. |
| End | Explicitly finished or dropped. A merge completes a step and ends nothing. |
| Major rethink | Drop it and start a new one. Nothing is carried over until a real case needs it. |
| ID | Permanent, and independent of the slug and ticket. |
| Kinds | One. A ticket, interactive iteration and a promoted talk are ways to start. A ticket is optional, and several can be chained. |
| Talk and iterate tags | Talk and iterate sessions stay recognisable through a visible tag, in the title or elsewhere. The tag helps the user keep them straight and changes nothing in the model. |
| Repos | Each workstream belongs to exactly one repo, and a repo can have several. Related workstreams share a group label, which has no steps, shared context or merge order. |

## Sessions

- A workstream has a list of sessions, each with a role. One lead is supported, plus any number of helpers and subagents. The data format must not rule out more than one lead.
- Governor and talk sessions are not workstreams, even when a governor session makes a small direct change. They must still appear in dashboards and session lists, so a session has its own identity and status.
- Project reviews are outside this model for now.

## Steps and blocking

Steps **describe** the work. The usual order is a default, not a procedure.

- There are default steps, and users can define their own. Steps are optional, can run in parallel, and can differ by project or by workstream.
- Any step can be added, skipped, reopened or jumped back to at any time. A workstream can have several PRs.
- A step can be required. A block applies only when settings declare it, and the defaults declare none.
- The user can list every active block with the settings file that added it. A refusal names that source and how to override it.
- Adding, tightening, removing or weakening a block needs the user's approval. This applies to prompts too, where an agent can otherwise write a new "refuse if" rule that no settings list shows.

## Attention

Sessions report when they need the user, and a workstream adds its own causes, such as a PR waiting to be merged with no agent running. The data keeps the cause, what is being asked, how long it has waited, what it holds up and the asking agent's estimate of the effort to answer. That is enough for an agent to help sort the queue.

## The record

| Topic | Decision |
| --- | --- |
| Contents | A fact belongs in the record only if something needs it during the work and cannot cheaply and reliably get it elsewhere. |
| Lifetime | Temporary. By default only telemetry outlives the workstream. |
| Telemetry | Each event must make sense without the record, so it carries the ID plus details such as repo and tickets. Dropped is a different outcome from finished. |
| Storage | In the worktree only. All access goes through workstream commands, so storage can change. |
| Updates | Workflow commands. For exceptions, the user asks in plain words and a general editing command, which the user can also run, makes the change. |
| Authority | git and GitHub are right about their own facts. The record is right about the slug, steps and tickets. |
| Surprises | When they disagree unexpectedly, pause, flag it, suggest a fix and wait. |
| Expected changes | The record picks them up without asking. |

A change is **expected** only when it fits the next step and leaves no work or required check behind. If unsure, ask. Syncing only updates the record: it authorizes no merge, and picking up a merge neither finishes the workstream nor removes its worktree.

| Update without asking | Pause and ask |
| --- | --- |
| A push changes the PR's latest commit | The branch gets unexpected commits, such as someone else's |
| A PR is opened from the workstream's branch when none is open | A different or second open PR appears unexpectedly |
| The PR is merged when merging is next, which marks that step done | It is merged with a required step unfinished or local commits unpushed |
| GitHub deletes the remote branch after a normal merge | The PR is closed without merging, or an unmerged branch disappears |
| | The local branch is renamed, or the worktree is on a different branch |

## Names

- One slug supplies the branch, worktree, session and PR names through per-surface formats. An optional fuller title defaults to the slug.
- A ticket's own slug is used if it has one. Otherwise one is drafted at kickoff, close to the ticket title. A chain normally gets a new slug.
- Renaming is expected only soon after creation. After publishing, the session name, statusline and PR title follow a rename. The branch and worktree keep the old name, and the tool says so. A forced change of those is done by hand until a real case needs more.

## Switching agents and hosts

- The user switches agents with one command. The switch must work when the old agent cannot respond.
- The new agent gets the record, ticket, code and old transcript. There are no progress notes or generated summaries for now. The transcript's location is therefore recorded when a session starts.
- Moving a workstream between hosts must stay possible. It will be built later.
- Seeing work across hosts is fairly urgent. Before building an aggregator, find out how far herdr or a similar tool gets, possibly with session names that show a few workstream attributes as emoji.

## Settings and code boundaries

- The record is the top [settings layer](workstream-config.md#layers): a value set there applies to that workstream only. Per-workstream changes are expected to be rare. The record holds only settings that differ from the lower layers, and everything else follows current settings. The exception is the step plan: kickoff copies it into the record, where it can be edited. Actual branch and worktree names are stored as facts. What kickoff copies can change later without a new record format.
- Setup tools (kickoff, worktree management, cleanup) and delivery tools (review, PR, merge) may call the record code. The record code never depends on them.
- The tool serves its author's needs first and stays configurable enough to extend to other users and workflows. How to package it for others is deferred.

## Worked cases

| Case | What happens | Not yet decided |
| --- | --- | --- |
| A design is rejected | The workstream is dropped and logged as dropped. A replacement gets a new ID and usually a new ticket. | Whether to link the two; what happens to the old branch and PR. |
| A design fails during review | Planning is reopened, then implementation. Reviews that no longer apply are reset. | Whether reviews reset automatically or on request. |
| Fixes are left unpushed after a merge | The workstream is still open. A second PR is added, and the PR and merge steps run again. | Whether it reuses the branch. |
| A trivial ticket | Its steps are changed to one local review round and nothing more. A required step needs its stated override. | |
| A security-critical project | Project settings add an external audit as a third review and can mark it required. | |
| Quota runs out | One command starts a new lead from the transcript and records the old session as no longer lead. | How to find each tool's transcript. |
| A change spans two repos | Two workstreams, each with its own agent, reviews and PRs, share a group label. The user coordinates them. | |
| A talk turns into work | The new workstream gets an ID and takes the talk session as its lead, keeping its context. | Whether the talk tag stays; how earlier discussion cost is tied to the new ID. |

## Open

- Data formats for the record, sessions and any status report. No reader of a snapshot has been settled.
- What herdr supports: a view across hosts, emoji in names, renaming and session status. None of this is verified.
- Attention: a stored level with a reason, or urgency computed from the stored details.
- The rest of the settings layer design in [workstream-config.md](workstream-config.md), which is still to be reviewed.
- What the slug of a workstream without a ticket is drafted from.
- How existing tickets, open PRs and the current tag design change to fit this model. The tags can serve as a compact view of steps and attention, but a fixed set of review sources and a single flag cannot be the underlying data.
