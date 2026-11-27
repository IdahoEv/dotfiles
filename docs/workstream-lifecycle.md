# Session and workstream record lifecycles

**Session tracking is automatic and unobtrusive; a workstream may ask more of you.** The agent's start hook creates each session record. An unlinked record goes away when you remove the session from the agent's own list, where that can be detected. A workstream record lasts until you finish or drop the workstream, never just because a PR merged.

This is the target design; none of it is built. It extends the [concept](workstream-concept.md); [record schemas](workstream-schema.md) defines the fields. Items marked **provisional** depend on what herdr provides.

## Terms

| Term | Meaning |
| --- | --- |
| Linked | The session record holds a workstream ID. |
| Unlinked | It holds none: talk, governor, project review and most ad hoc sessions. A talk can gain one later. A link to a [gone](workstream-schema.md#open-workstream-list) workstream, one listed on this host whose worktree is missing, is cleaned up like no link. With no list entry, or a failed lookup or unreadable record, the session record stays. |
| Lead | The one linked session responsible for moving the workstream forward. It is a role, not a status: a lead can be working, waiting or exited. v0 has at most one. |
| Helper | Any other linked session. |
| Not running | Confirmed from evidence on the same host, never from age. A stopped process may still be resumable. |

Governor and talk sessions are never linked.

## Session record

### States

| State | Meaning |
| --- | --- |
| `open` | Created or reopened, with no end seen. The process may or may not be running. |
| `ended` | Something ended it: a clean exit, `/clear`, takeover or detected removal. The reason is stored. It can reopen. |
| destroyed | The record is gone, after its [final log entry](#before-a-record-is-destroyed). |

Whether the process is running is checked when needed and not stored. There is no `launching` state.

Updates come from the start events below, purpose changes, takeover, promotion, and activity and attention reports. Activity and attention are separate from state (**provisional**).

### Start

| Event | Effect |
| --- | --- |
| New session | The agent's start hook creates the record, keyed on agent and native session ID. A repeat updates it. |
| Resume | Reopens the record, or creates one if it is missing. A former lead whose role another session took returns as a helper and says so. With no successor, it still holds the role. |
| Compact | Updates the same record. |
| `/clear` with a new ID | The old record ends and the new one notes the old ID, because earlier context is in the old transcript. If linked, the link, role and purpose carry over, and an old lead becomes a helper. If unlinked, the purpose carries over only when it is talk or governor, so the new record isn't linked. |
| Fork | The original is unchanged. The fork gets its own record, as a helper if the original is linked. |
| Subagent | No record. |
| Headless run | Helpers spawned by tools get none. Scheduled unattended runs do. |

- A session that starts in a worktree with a workstream record is **linked automatically**, unless its declared or stored purpose is talk or governor.
- Launchers create no session records, so a launched session can be invisible until its first hook. A launch that fails before then leaves only launch telemetry. A rerun can't find that session from records and may start a second one.
- A launcher can declare a link, role or purpose for the start hook to apply. The hook never claims the lead on its own.

### Purpose

| Source | Rule |
| --- | --- |
| Launcher or command, including one run in a hand-started session | `/start`'s new session and takeover set implement, `/discuss` talk, `/governor` governor. |
| You | Declare or change it in plain words. Your declaration beats an agent's guess. |
| Agent | May fill a blank on an unlinked ad hoc session when your prompt makes it clear. It never asks. |

- Setting talk or governor removes the link. A guessed purpose never changes a link.
- A talk promoted to work keeps its record, gains the link, and its tag becomes implement. The workstream slug is drafted from the talk's goal, unless a ticket supplies one.
- A lead has no goal of its own and shows the slug. Helpers and unlinked sessions can have one, declared by you or written by an agent when it's clear. It is never asked for.

### End and destroy

| Record | When it is destroyed |
| --- | --- |
| Unlinked | When you remove the session from the agent's own list (Claude Code's agent view and its equivalents). Where removal can't be detected, once it has ended or is confirmed not running. |
| Linked | When its workstream is finished or dropped. Exiting or removing the session only marks it `ended`. |
| Linked session at finish or drop that is running (usually the one running `/finalize`) or can't be checked | Its link is logged and removed. It then follows the unlinked rule. |
| Unlinked session where it can't be told whether it is running | It stays, unless its removal is detected. |
| Any record you dismiss with the dismiss command | At once. Dismissing is never required. |

A hook or the next workstream command notices removal; no background process runs. Resuming after destruction creates a new record.

## Lead check and takeover

The check runs when a session starts or is asked to resume work in a workstream, and when a governor is asked to.

| Lead found | Session in the worktree | Governor |
| --- | --- | --- |
| Ended, or confirmed not running | Takes the role and tells you | Starts a new lead and tells you |
| Running | Leaves it | Leaves it |
| No lead record, or can't tell | Asks: "I can't find a lead session for this worktree. Shall I take that role?" | Asks: "I can't find a lead session for this worktree. Shall I start a new one for you?" |

- The start hook only prompts the agent to run the check.
- An unattended session that can't tell does not take the role.
- **One takeover command** covers abandoned worktrees and agent switches. It marks the old lead `ended` without its cooperation and makes the new session lead, which turns the old record into a helper. It gives it the old transcript path if there is one.
- Replacing a lead that is still running, such as one out of quota, takes your explicit request.
- A governor can also list workstreams with no running lead and offer to start one. It marks those it can't determine. It reads this host's [open-workstream list](workstream-schema.md#open-workstream-list). Other hosts are **provisional**.

## Workstream record

### States

The only stored state is **active**. Finished and dropped are outcomes, logged as the record is destroyed. There is no paused state.

| Transition | Owner and trigger | Effect |
| --- | --- | --- |
| Create | Kickoff (`/start` → `start-ticket.sh`), `/iterate` (not built yet), talk promotion, or your request for an existing worktree | A permanent ID, an active record in the worktree and a list entry. |
| Update | Workflow commands, and the general editing command | [Expected changes](workstream-concept.md#records-and-storage) are picked up; surprises pause and ask. A command that moves the worktree updates the list entry. |
| PR merged | `/merge`, or a command that finds the merge | Only the PR's state changes. |
| Finish | `/finalize`, so also `/land` | Asks first if commits are unpushed or no PR merged. Logs, then destroys the records and the list entry. |
| Drop | A new drop command | Ends and finalizes without a merge. Asks separately about the PR, remote branch, unpushed or uncommitted work, and worktree. It closes or deletes only what you confirm. The records and list entry are destroyed even if the worktree stays. |

Finish and drop destroy linked session records first and the workstream record last. An interrupted run leaves the workstream active; run it again. A rerun may log an event twice.

**Gap:** [`prune-worktrees.sh`](../tools/lib/prune_worktrees.py) can remove a merged worktree, record included, without a finish. It must not destroy an active workstream that way. Whether it skips such a worktree or runs finish is not decided.

## Before a record is destroyed

| Record | Logged to telemetry |
| --- | --- |
| Session | Agent, native session ID, repo or project, **transcript path**, and, if it was linked, the workstream ID and any readable tickets |
| Workstream | Outcome (finished or dropped), workstream ID, repo and tickets |

- Logging the path is a deliberate exception to the [telemetry rule](workflow-telemetry.md#events) against transcript paths.
- If the write fails, the record stays. If telemetry is disabled, destruction proceeds.
- Transcripts are not copied. Agents may delete them on their own schedule (`cleanupPeriodDays` is 30 for Claude Code here), so a logged or stored path can point to nothing.
- **Gap:** today's logger drops events from outside a ticket branch, but every session must be logged. It also reports success when a write fails and cuts values to 200 characters. Destruction needs to learn of a dropped or failed write, and to log the full path.

## Triggers by agent

Record writes belong to the workstream commands; hooks and launchers only call them. None of those calls exists yet, so evidence tags describe the agent's signal, not a working integration.

| Tag | Meaning |
| --- | --- |
| **Seen** | Observed on this host |
| **Doc** | Vendor documentation: [Claude Code](https://code.claude.com/docs/en/hooks), [Codex](https://learn.chatgpt.com/docs/hooks.md), [agy](https://antigravity.google/docs/hooks/) |
| **3P** | Third-party reports only |
| **Unverified** | Assumed or untested |
| **Gap** | No known signal |

| Session transition | Claude Code | Codex | OpenCode | agy |
| --- | --- | --- | --- | --- |
| Create | `SessionStart`, `startup` (**Seen**) | `SessionStart`, `startup` (**Doc**) | Plugin `session.created` ([**3P**](https://github.com/rohitg00/agentmemory/tree/main/plugin/opencode)); no plugin here | `SessionStart` (**Doc**); may wait for the first prompt ([**3P**](https://github.com/k-k1/agent-fleet/issues/2156)) |
| Resume | `resume` (**Seen**) | `resume` (**Doc**) | **Gap** | **Gap**; `PreInvocation` could stand in (**Unverified**) |
| Compact | `compact` (**Seen**) | `compact` (**Doc**) | **Unverified** | **Gap** |
| Clear | `clear` (**Doc**); new ID and old-to-new match **Unverified** | `clear` (**Doc**); same two **Unverified** | **Gap** | **Gap** |
| Fork | `fork` (**Seen**); finding the original **Unverified** | `fork` (**Doc**); same | **Gap** | **Gap** |
| Clean end | `SessionEnd` (**Seen**), often missing | `SessionEnd` (**Doc**), also after 30 idle minutes; [not trusted alone](#codex-end-events) | **Gap** | **Gap**; `Stop` ends a run, not a session |
| Removal from the agent's list | **Unverified**: hook and on-disk effect of double Ctrl-X | `SessionEnd` on archive or delete of an open conversation (**Doc**); same reason as other ends, so [not trusted alone](#codex-end-events) | **Gap**; standalone delete skips plugins (**3P**) | **Gap** |
| Running check | Per-process files matched 4 of 4 live processes (**Seen**, one look); idle-stopped sessions **Unverified** | Lock files and shared server (**Unverified**) | **Gap** | `presence/` lock files (**Unverified**) |
| Hook can prompt the lead check | Added context (**Doc**) | Added context (**Doc**) | **Unverified** | **Unverified** |

| Activity and attention (**provisional**) | `Stop`, `Notification`, `PermissionRequest`, `UserPromptSubmit` (hooked here for tab color; the last also clears `!`) | The same events except `Notification` (hooked here) | **Unverified** | `Stop`, `PreInvocation` (**Doc**) |

### Codex end events

Codex sends `SessionEnd` with one reason on close, archive, delete, and after 30 idle minutes with no client connected. So **the event alone neither ends nor destroys a record.** It counts only when a running check confirms the session isn't running; until then the session is "can't tell". That check is unverified, so expect extra prompts and leftover Codex records.

Command-owned transitions work the same way on every agent. Claude Code runs the command; Codex and agy reach it through a skill, and OpenCode through a command, that points to the same file.

| Command transition | Owner | Wrappers today |
| --- | --- | --- |
| Workstream create | `/start`, `/discuss` promotion, `/iterate` | `/start` and `/discuss` have all three; `/iterate` is not built (**Gap**) |
| Workstream update and PR merged | Workflow commands such as `/open-pr`, `/merge`, `/sync` | `/open-pr`, `/merge`: all three. `/sync`: not agy (**Gap**) |
| Purpose, link, promotion | The launching or promoting command; your plain-words request | As above |
| Lead check, takeover, dismiss, list, drop | New commands | None (**Gap**) |
| General record edit | New command, which you can also run yourself | None (**Gap**) |
| Destroy unlinked records and gone links | A hook or the next workstream command; which ones is not yet decided | None (**Gap**) |
| Finish | `/finalize`, `/land` | All three |

Hook limits:

- On this host, 96 of 142 sessions with a logged start had no logged end (counted 2026-11-27; some may still be open, and the logger skips non-ticket branches). Nothing may depend on an end hook firing.
- Codex hooks here are configured only in the local `~/.codex/hooks.json`. Payloads and daemon-launched threads are **Unverified**.
- agy and OpenCode have no record hooks configured.
- **Unverified** for all agents: passing launcher declarations through background daemons, writing session records from a sandbox, and telling headless helpers from scheduled runs.
- When a hook can't match a new ID to the old one after `/clear`, the new record gets only the automatic link, even if the old one was talk or governor, and the lead check applies.
- A replaced lead that is still running has no known way to be told.

**Provisional:** activity, attention, the source of the running check, and anything across hosts. A session on another host counts as "can't tell".

## Walkthroughs

### Agent handoff

1. A Claude lead runs out of quota. You ask a governor to hand the workstream to Codex.
2. Takeover runs the lead check. The old agent is running or unknown, so your request is what authorizes replacing it.
3. Takeover marks the old record `ended` (replaced). This edits only the record, so it works when the old agent can't respond.
4. It launches Codex in the worktree, declaring link, lead and implement, with the workstream record, ticket, code and old transcript path.
5. Codex's start hook creates the new record.
6. The old record stays until the workstream ends. If the old agent resumes after the new one took the role, it is a helper.

A responsive old agent changes nothing: there are no progress notes to collect. If the launch fails, the old record is `ended` but still holds the role, so the next lead check can fill it. If the old agent resumes first, it is still lead. With no transcript path, the new agent works from the record, ticket and code.

### A talk becomes a workstream

1. `/discuss` starts an unlinked session tagged talk.
2. You commit to a code change. Promotion creates the worktree and workstream record.
3. The same session record gains the link, takes lead and is retagged implement. Its context is kept.
4. From then on it is destroyed under the linked rule.

How earlier discussion cost is tied to the workstream is still open. The session ID is the same before and after, so telemetry can be joined later.

### A merge, then a second PR

1. PR 1 is merged with `/merge`. The record marks it merged and stays active. GitHub deleting the remote branch is an expected change.
2. Unpushed fixes remain. You don't run `/finalize`.
3. You continue on the same branch or a new one. A workflow command that switches branches updates the record; an unexplained switch pauses and asks.
4. PR 2 is added to the same workstream, reviewed and merged. [Reviews accepted before PR 1 merged](workstream-schema.md#reviews) count as planned, so they can't mark PR 2 ready.
5. `/finalize` finishes it.

## Tolerated and manual cleanup

Nothing here is repaired automatically. Removing unlinked records and broken links is part of the usual path.

| Leftover | Handling |
| --- | --- |
| Session record whose running state is unknown | Stays; dismiss it if it bothers you. |
| Linked record in a workstream that is never finished | Stays with the workstream. |
| Worktree deleted by hand | The workstream record goes with it, and no outcome is logged. Its sessions' links are then gone. The stale list entry stays. |
| Worktree moved by hand | It looks gone, so its non-running sessions can be destroyed. Move it with a workflow command. |
| Missing list entry | The workstream isn't listed, and its sessions' records stay. |
| Corrupt or unreadable record | Reported; fix or delete it by hand. |
| Worktree or branch kept after a drop | Clean up by hand. |
| Talk or governor session whose purpose is lost: resumed after its record was destroyed, or an unmatched `/clear` | In a workstream worktree, the new record is linked. Declare the purpose again to remove the link. |
| Missing or pruned transcript | Handoff proceeds without it. |
| Worktree with no workstream record | Sessions there are unlinked; ask for a record to be created. |
| Workstream with no session records, including all that predate them | The lead check asks before filling the role. |
