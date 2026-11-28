# Fovea telemetry design

**Fovea keeps its own append-only event log on each host as the official record.** Reports pull other hosts' logs over SSH and keep them forever. Agent hooks, transcripts, OpenTelemetry and outside tools only feed that log. Every event still makes sense after the session and workstream records are deleted.

This is a target design; none of it is built. It extends the [record lifecycles](../workstream-lifecycle.md) and [record schemas](../workstream-schema.md). Three limits matter most:

- **Time waiting on you is unproven on every agent.** No agent is known to report each question, approval and its answer reliably.
- **Typing time and quota share are estimates.** I found no hook that times typing, and quota percentages cover a whole account.
- **Hook coverage is uneven.** agy has no documented permission or token signal, I did not verify OpenCode's signals, and no hook here is verified on Linux.

## Decisions

| Topic | Decision |
| --- | --- |
| Foundation | Own JSONL log. Not built on OpenTelemetry: [uneven support across agents](#appendix-existing-tools) |
| Usage source | Pluggable. A trial picks Fovea's own parsers or an agentsview export for each agent |
| Claude OpenTelemetry | Optional extra input for request timing and active time |
| Collection | Pull on demand over SSH |
| Pools | Separate pools, such as work and personal, never exchange data |
| Retention | Forever, with no automatic deletion |
| Free text | [Short summaries on an allowlist](#exclusions) only |
| Cloud sessions | Not collected in this version |
| Adapters | The core names no agent, tracker, terminal tool or UI. Each plugs in through an adapter, including [herdr](https://github.com/IdahoEv/dotfiles/pull/277) and agentsview |
| Priority | Your attention first, then tokens and agent response time ([Fovea's principles](https://github.com/IdahoEv/Fovea)) |

Fovea's format starts clean. Older logs enter only [as imports](#imported-data).

## Questions telemetry must answer

Listed by priority. **Measured** comes from a clock or a provider's count. **Estimated** is derived by a stated rule. **Reported** is an agent's judgment. A listed gap shows as [unknown](#missing-data).

| # | Question | Events and key fields | Quality and gaps |
| --- | --- | --- | --- |
| 8 | Time waiting on you by cause, longest waits and what each asked | `attention.*` (cause, request), `pr.state`, `review.state`, `turn.*` | Measured where the wait is seen. Waiting to merge is derived. Permission and question waits vary by agent |
| 12 | Time waiting on the agent or model, by trigger, activity and prompt label | `turn.*`, `span.completed` (kind, duration, model, effort), `prompt.labeled` | Activity detail varies. Time to first token needs Claude's beta tracing. Labels are reported |
| 13 | Wall time per ticket and ticket type, split into agent, you and idle; which types sit abandoned | `workstream.*` (ticket types, labels, estimate, category), `turn.*`, `attention.*`, `away.declared` | Times measured; the split is estimated |
| 14 | Typing effort by ticket type | `turn.started` and `attention.closed` (input size and kind), `input.active_time` | Estimated. Active time is Claude only and includes reading |
| 3 | One workstream's time per stage, split into agent working, waiting on you and idle | `workstream.stage`, plus the events for 13 | As 13 |
| 15 | The same breakdowns for sessions without a workstream, by purpose | `session.started`, `session.updated`, `turn.*`, `attention.*`, `usage.snapshot` | As 12–14. A session with no purpose shows as unknown |
| 9 | Failures and stalls by type, agent and host | `turn.ended` (error type), `command.completed`, `span.completed`, `review.state`, `host.profile` | Measured where signaled. Stalls are derived from gaps |
| 1 | Tokens and cost per finished workstream by stage, agent, model, main or subagent | `usage.snapshot`, `workstream.stage`, `workstream.closed`, `quota.sample` | Tokens measured; cost and quota estimated. Coarse usage can't be split by stage |
| 2 | A month's tokens and cost by project and session purpose | `usage.snapshot`, `session.started`, `session.updated`, `quota.sample` | As 1 |
| 4 | Test runs, test time and repeated reruns | `span.completed` (kind `test`, command fingerprint) | Test detection is a pattern match |
| 5 | Findings, validity, overlap and tokens per valid finding by reviewer, model and effort | `review.launch`, `review.finding`, `usage.snapshot` | Validity and overlap are reported |
| 6 | Valid bot findings that local review missed | `review.finding` (source, path, line, claim, commit), `review.launch`, `review.state` | Matching findings is a later judgment |
| 7 | Rounds, cost and findings before and after a workflow change | `config_ref` on `session.started` and `review.launch`, `review.*`, `usage.snapshot` | Small samples; descriptive only |
| 10 | Dropped workstreams: stage, cost and reason | `workstream.closed` (outcome, drop reason, stage), `usage.snapshot` | A hand-deleted worktree has no close event |
| 11 | A ticket's or PR's history: sessions, agents, hosts, handoffs, outcome, transcripts | `workstream.*`, `session.*`, `pr.state` | A logged transcript path may point to nothing |

## Common fields

| Field | Req | Meaning |
| --- | --- | --- |
| `schema_version` | yes | Integer, `0` |
| `event_id` | yes | Random 128-bit ID, assigned once. Duplicates are found by it |
| `type` | yes | Name from the [catalog](#event-catalog) |
| `time` | yes | When it happened, UTC, milliseconds |
| `logged_at` | yes | When it was written; differs for extracted or imported events |
| `pool` | yes | The host's pool |
| `host_id` | yes | Random, made once per installation. Not the hostname |
| `seq` | yes | Position in this host's log, assigned by the writer under a lock. Gives pull cursors |
| `producer`, `producer_version` | yes | Which command, hook, extractor, classifier or importer wrote it |
| `quality` | yes | `measured`, `estimated`, `reported` or `inferred` |
| `session_id` | when about a session | `<tool>-<native_id>`, as in the session record |
| `agent_id`, `agent_type` | for subagents | The subagent within that session |
| `workstream_id` | when linked | `ws-` plus 12 hex digits; survives renames |
| `repo` | when known | `owner/name` or directory name |
| `tickets` | when linked | `{provider, id}` pairs |
| `turn_id` | when within a turn | The agent's ID, or one the adapter assigns |
| `imported` | when imported | `{source, original_id}` |

- **One writer command appends every event.** It takes an exclusive lock, validates fields against the type's allowlist, and returns success or failure. It never truncates a transcript path.
- **IDs and descriptions travel separately.** Every workstream event repeats `workstream_id`, `repo` and ticket IDs. Titles, labels and ticket types appear in `workstream.created`, `updated` and `closed`.
- **Order** within a host is `seq`. Across hosts it is `time`, which depends on host clocks.

## Event catalog

**Req** lists required fields beyond the common ones; "?" marks an optional field. **Use** gives question numbers.

### Sessions and attention

| Event | Purpose | Req | Producer and trigger | Use |
| --- | --- | --- | --- | --- |
| `session.started` | A session began or reopened | `tool`, `native_id`, `entry` (`startup`, `resume`, `clear`, `compact`, `fork`), `interface` (`interactive`, `headless`, `subagent`, `scheduled`); `agent_version`?, `purpose`?, `purpose_source`?, `previous_id`?, `forked_from`?, `parent_session_id`?, `config_ref`? (workflow version) | Start hook | 2, 7, 11, 15 |
| `session.updated` | Purpose changed | `purpose`, `purpose_source` | Record command | 2, 11, 15 |
| `session.linked` | Joined a workstream or changed role | `role`, `reason` (`created`, `auto`, `declared`, `promoted`, `takeover`, `lead_check`, `resume`, `fork`, `clear`); `replaced_session_id`? | Record command | 1, 11 |
| `session.unlinked` | Left a workstream | `reason` (`purpose`, `finished`, `dropped`, `gone`) | Record command | 1, 11 |
| `session.ended` | An end was seen. Often missing, so nothing depends on it | `end_reason` (`exit`, `clear`, `replaced`, `removed`) | End hook, takeover, removal check | 9, 11 |
| `session.destroyed` | Final entry before the record goes | `tool`, `native_id`, `transcript_path` or `transcript_gap`; plus `workstream_id` and `tickets` if it was linked | Dismiss, cleanup, finish, drop | 11 |
| `turn.started` | The agent began working | `trigger` (`prompt`, `command`, `skill`, `agent_message`, `schedule`, `continuation`), `actor` (`user`, `automation`, `unknown`); `name`? (command or skill), `input_chars`?, `pasted_chars`?, `input_kind`? (`typed`, `pasted`, `dictated`, `mixed`, `unknown`) | Prompt-submit hook or adapter | 3, 8, 12–15 |
| `turn.ended` | The agent stopped | `outcome` (`completed`, `interrupted`, `failed`); `error_type`? (fixed list) | Stop, failure and interrupt hooks | 3, 8, 9, 12, 13, 15 |
| `prompt.labeled` | What you were asking for | `labels`, `label_list_version`, `classifier_model` | [Batch classifier](#prompt-labels) | 12 |
| `attention.opened` | Something needs you | `wait_id`, `scope` (`session`, `workstream`), `cause`; `request`?, `effort`?, `subject`? | Question, permission and notification hooks; workflow commands | 3, 8, 13, 15 |
| `attention.closed` | It no longer does | `wait_id`, `cleared_by` (`reply`, `command`, `subject_changed`, `stage`, `destroyed`), `resolution` (`answered`, `approved`, `denied`, `cancelled`, `unknown`); `input_chars`?, `input_kind`? | Same | 3, 8, 13–15 |
| `input.active_time` | Seconds the agent counted you as active | `seconds`, `from`, `to` | Claude OpenTelemetry adapter | 14 |
| `span.completed` | One timed piece of agent work | `kind` (`model_request`, `tool`, `test`, `subagent`, `compaction`), `ended_at`, `outcome`; `started_at`?, `duration_ms`?, `ttft_ms`?, `name`? (tool or subagent type), `model`?, `effort`?, `query_source`?, `error_type`?, `command_fingerprint`?, `source_ref`? (the agent's tool-use, request or subagent ID) | Tool, model and subagent hooks, extractors, OpenTelemetry | 3, 4, 9, 12 |

`cause` is the record's open set (`question`, `plan-approval`, `design-gate`, `auth`, `reviewer-failed`, `review-stalled`, `no-pr`) plus `permission`. `wait_id` is the [attention entry](../workstream-schema.md#attention)'s. For a wait with no entry, the adapter uses the agent's request ID; without one, the wait has no explicit close.

### Usage and quota

| Event | Purpose | Req | Producer and trigger | Use |
| --- | --- | --- | --- | --- |
| `usage.snapshot` | Tokens that outlive transcripts | `scope_key`, `granularity` (`request`, `turn`, `session`), `from`, `to`, `model`, `tokens`, `extractor`, `extractor_version`, `complete`, `billing` (`api`, `subscription`, `unknown`); `speed`?, `account_ref`?, `api_cost_usd`?, `price_table`?, `agent_cost_usd`? | Usage adapter | 1, 2, 5, 7, 10, 15 |
| `quota.sample` | How much of an account limit is used | `account_ref` (your label, never an email), `limit_id`, `window_minutes`, `used_pct`, `resets_at`, `source`; `plan`? | Quota adapter, when the value changes | 1, 2 |

- **`scope_key`** is the agent's request ID or the `turn_id`. At `session` granularity it is `total`, a running total.
- **Link boundaries.** Each link and unlink also captures usage. A `session` source stores that total again under `at:<link or unlink event_id>`; reports only subtract these, to split the running total. Without one, the split is unknown.
- **Replace, never add.** For one session, subagent, model, speed and `scope_key`, the latest snapshot wins. A report uses one granularity per session, the finest complete one, so totals are never counted twice. Adapters must also drop requests that resumed or forked transcripts repeat.
- **Token buckets don't overlap:** `input` (excluding cache), `cache_read`, `cache_write_5m`, `cache_write_1h`, `output`, `reasoning`. If a source can't separate reasoning from output, `reasoning` is unknown and `output` is flagged as including it.
- **Capture** at each turn end, before a record is destroyed, and in a sweep before transcripts expire (Claude Code keeps them 30 days by default). Every report or pull runs the sweep. A host you rarely query also needs it scheduled.

### Workstreams, reviews and PRs

| Event | Purpose | Req | Producer and trigger | Use |
| --- | --- | --- | --- | --- |
| `workstream.created` | Identity and description | `origin` (`ticket`, `iterate`, `talk`, `request`), `slug`, `repo`, `branch`, `tickets` ([with descriptions](#ticket-type)); `title`?, `category`?, `group`?, `from_session_id`? | Kickoff, promotion, record command | 1, 10, 11, 13 |
| `workstream.updated` | The description changed | The same description fields: all current values, except [`category`](#ticket-type) only when set | Record command | 11, 13 |
| `workstream.stage` | Stage written | `stage` (`plan`, `wip`, `review`) | Stage writes | 1, 3, 10, 11, 13 |
| `workstream.closed` | Final summary | `outcome` (`finished`, `dropped`), `stage`, `repo`, `slug`, `tickets` with descriptions, `prs`; `title`?, `drop_reason`? | Finish or drop, before destroying the record | 1, 10, 11, 13 |
| `review.state` | A review was planned, started a round, ended one, was accepted or removed | `source`, `status` (`planned`, `running`, `accepted`, `removed`), `round`, `change` (`planned`, `round_started`, `round_ended`, `accepted`, `reset`, `removed`, or `summary`: cycle or batch totals, with no `status` or `round`); `reviewer`?, `head_sha`?, `fixed`?, `dismissed`?, `deferred`?, `findings_count`? | Review commands | 6–9, 13 |
| `review.launch` | A reviewer ran | `reviewer`, `round`, `model`; `effort`?, `agent_id`? or `reviewer_session_id`?, `config_ref`? | Review manager | 5–7 |
| `review.finding` | One triaged finding | `finding_id`, `group_id`, `source`, `reviewer`, `severity`; `round`?, `verdict`?, `validity`?, `reason`?, `claim`?, `path`? (relative to the repo), `line`?, `head_sha`?, `external_id`? | Review triage; bot-comment adapter | 5–7 |
| `pr.state` | A PR was opened, updated, merged or closed | `number`, `state` (`open`, `merged`, `closed`); `url`?, `branch`?, `head_sha`?, `merged_at`? | PR commands and sync | 6, 8, 11 |
| `command.completed` | A workflow command ended | `command`, `outcome` (`ok`, `failed`, `stopped`, `handoff`), `duration_ms`; `reason`? (fixed list), `exit_code`? | Each workflow command, including launches and review watches | 9 |

`group_id` is shared by reviewers who raised the same finding. Findings overlap when two different reviewers share one.

**A fact seen twice counts once.** These keys apply beyond `event_id`:

| Event | Same fact when | Merge |
| --- | --- | --- |
| `span.completed` | Same `session_id`, `kind` and `source_ref` | Hook fields win; other producers fill blanks. Without `source_ref`, only the one producer the adapter names for that agent and kind counts |
| `review.finding` | Same `workstream_id` (else `session_id`), `source`, `reviewer` and `finding_id` | Latest wins. `finding_id` is unique to one finding in that scope; the bot adapter derives it from `external_id` |
| `pr.state` | Same `repo`, `number` and `state` | Latest wins |

### Hosts and gaps

| Event | Purpose | Req | Producer and trigger | Use |
| --- | --- | --- | --- | --- |
| `host.profile` | What this host can observe | `label` (you choose it), `os`, `adapters`: each adapter's agent, version and signals (`supported`, `unsupported`, `unverified`) | Writer, at setup and on change | 9, all reports |
| `gap.recorded` | A known loss | `signal`, `gap_reason`; `detail`? (fixed list) | Any producer | All reports |
| `away.declared` | A period you mark as away | `from`, `to`; `kind`? (`vacation`, `off_hours`, `other`) | Your command | 3, 13 |

## What happens in common cases

| Case | Events, in order |
| --- | --- |
| Standalone session (talk, governor, project review, ad hoc) | `session.started` → turns, spans, usage → `session.ended` if seen → `session.destroyed` |
| Talk becomes work | Same session: `workstream.created` (`from_session_id`) → `session.updated` (implement) → `session.linked` (`promoted`). Earlier usage stays outside the workstream; reports can add it as a separate "preceding discussion" line using the link time. If [usage can't be split](#usage-and-quota) there, both figures are unknown |
| Handoff | Takeover: old `session.ended` (`replaced`) → new `session.started` → `session.linked` (`takeover`, `replaced_session_id`) → old `session.linked` (`helper`). A failed launch leaves only the first event and `command.completed` |
| Resume or `/clear` | `session.started` with `entry`; `/clear` also sets `previous_id` and relinks |
| Merge, then a second PR | `pr.state` merged; the workstream stays open → second `pr.state` open |
| Finished | Per linked session: final `usage.snapshot` → `session.unlinked` → `session.destroyed` or later cleanup. Then `workstream.closed` (`finished`) last |
| Dropped | The same, with `outcome: dropped` and a drop reason |
| Review manager or subagent | Usage and spans under the parent `session_id` with `agent_id`. A separate headless session gets `session.started` with `parent_session_id`, even if it gets no record |

- **A required write that fails keeps the record** ([lifecycle rule](../workstream-lifecycle.md#before-a-record-is-destroyed)). Required: `session.destroyed`, `workstream.closed` and an attempt at final usage. If usage can't be read, a `gap.recorded` satisfies it. With telemetry disabled, destruction proceeds.
- **A rerun can repeat close events.** The latest `workstream.closed` per workstream wins, and the latest `session.destroyed` per session.
- **A workstream with no close event is open or unknown,** never assumed finished or dropped.

```json
{"schema_version":0,"event_id":"7f0c…","type":"workstream.closed","time":"2026-11-27T23:10:04.120Z",
 "logged_at":"2026-11-27T23:10:04.131Z","pool":"personal","host_id":"h-51ac…","seq":18234,
 "producer":"finish","producer_version":"0.1.0","quality":"measured","workstream_id":"ws-9c41e07a52bd",
 "repo":"example/app","slug":"record lifecycles","outcome":"finished","stage":"review",
 "tickets":[{"provider":"github","id":"12","type":"feature","labels":["design"],"estimate":"3"}],
 "prs":[{"number":15,"state":"merged"}]}
```

## Report rules

### Waiting and idle time

Events store only timestamps, so you can change these rules and rerun old data. A workstream's time is split into non-overlapping intervals; the first matching row wins.

| Class | Rule |
| --- | --- |
| Agent working | A linked session has a turn running and no open wait. Spans break this down; the rest is `unattributed` |
| Declared away | You would otherwise be waited on or idle, inside an `away.declared` period |
| Busy elsewhere | Waiting on you, while you submitted a prompt or answered a wait in another session in the pool |
| Unknown | Needed signals are missing, including when a session in use during the interval can't report your input or tell it from automation |
| Away or abandoned | No input from you anywhere in the pool for longer than the threshold (default 30 minutes) |
| Waiting on you | Any other time with a wait open, a PR ready to merge, or a finished turn awaiting your next prompt |

- Only `actor: user` turns and waits cleared by your reply count as your activity.
- **A pool can't see your activity in another pool,** so time on work looks like time away in personal data.
- A wait with no close ends at the session's next sign of progress and is marked estimated.
- Abandonment (13) reports the longest gaps per open or closed workstream, grouped by ticket type, category, estimate and project.

### Typing effort

Typing time is typed characters divided by a typing speed you configure. Pasted and dictated characters are counted but excluded from that estimate. If an adapter can't tell, the input is `unknown` and reported separately. Claude's active time is shown beside the estimate, never added to it, because it includes reading.

### Cost and quota

| Measure | How |
| --- | --- |
| API-equivalent cost | Tokens × a dated price table. Computed for API and subscription use alike. An unpriced model is unknown, not free |
| Quota share | Within one account, limit and reset window, split each rise in `used_pct` across the usage between the two samples, in proportion to API-equivalent cost. Report percentage points for the 5-hour and weekly limits |
| Subscription fee share | Dated monthly fee × weekly points ÷ 100 ÷ 4.35. Unused quota is left unallocated |

All three can be compared per activity. **Quota share is an estimate:**

- Use on a host that wasn't pulled, in a web app or from another pool inflates local activities. A rise with no local usage shows as unattributed.
- A provider may weight models differently from list price.
- Rounded percentages make short activities imprecise, so reports sum them over longer spans.

### Ticket type

Each ticket in `workstream.created`, `updated` and `closed` copies the tracker's `type`, `labels` and `estimate` word for word through the tracker adapter, plus `provider`, `id` and `url`. The project is `repo`, and a chain is a list of more than one ticket. `category` is Fovea's own optional value from a configurable list (starting `feature`, `bug`, `design`, `research`, `chore`), set at kickoff or edited later. Only the `created` or `updated` event that sets it carries it, and the latest wins. The workstream record needs no new field, because nothing reads category during the work.

### Prompt labels

A batch job on each host reads prompts from local transcripts and stores only labels. It runs periodically and before a record is destroyed. The first list is `question`, `new_work`, `correction`, `review_request`, `approval`, `status_check`, `discussion` and `other`.

- Prompts not labeled before their transcript disappears stay unknown, and old prompts can't be relabeled after that.
- The classifier sends prompt text to a model. Each pool configures which model and account may receive it.
- Its own tokens are logged as a session with purpose `classifier`.

## Missing data

Reports never show missing data as zero. Each figure is measured, estimated, reported, inferred, **partial** (with "n of m sessions") or **unknown** with a reason:

| Reason | Meaning |
| --- | --- |
| `unsupported` | The agent has no such signal |
| `unverified` | The adapter doesn't yet trust the signal |
| `not_configured` | The hook or input is off |
| `source_expired`, `source_missing` | The transcript or file is gone |
| `parse_failed` | The format changed or the data is unreadable |
| `not_captured` | Supported, but no event arrived |
| `not_pulled` | The host is unreachable or its data is stale |

`host.profile` says what each adapter claims to see, so a report can tell "no failures" from "can't see failures". A failed write is returned to the caller; one that can't reach the log may leave no trace.

## Trigger coverage

| Tag | Meaning |
| --- | --- |
| **Seen** | The signal or data was observed on a development host. For hooks, this is not a working Fovea integration |
| **Doc** | Vendor docs: Claude Code [hooks](https://code.claude.com/docs/en/hooks), [statusline](https://code.claude.com/docs/en/statusline), [OpenTelemetry](https://code.claude.com/docs/en/monitoring-usage); [Codex](https://learn.chatgpt.com/docs/hooks.md); [agy](https://antigravity.google/docs/hooks/) |
| **3P** | Third-party reports or a third-party tool's parser |
| **Unverified** | Assumed or untested |
| **Gap** | No known signal |

Lifecycle signals (create, resume, compact, clear, fork, end, removal, running check) are in the [record lifecycle table](../workstream-lifecycle.md#triggers-by-agent).

| Signal | Claude Code | Codex | OpenCode | agy |
| --- | --- | --- | --- | --- |
| Prompt submitted | `UserPromptSubmit` (**Seen**) | `UserPromptSubmit` (**Doc**) | Plugin (**Unverified**) | No event (**Gap**); `lastUserInput` on `PreInvocation` could infer it (**Doc** field, use **Unverified**) |
| User vs automated prompt; paste detection | **Unverified** | **Unverified** | **Unverified** | **Unverified** |
| Turn end | `Stop` (**Seen**) | `Stop` (**Doc**) | **Unverified** | `Stop` with reason and `fullyIdle` (**Doc**) |
| Interrupt | **Unverified** | `Interrupt`, not for idle threads or subagents (**Doc**) | **Unverified** | **Gap** |
| API or turn failure | `StopFailure` (**Seen**) | `PostModelRequest` status (**Doc**) | **Unverified** | `Stop` error (**Doc**) |
| Permission wait opens | `PermissionRequest`, `Notification` (**Doc**) | `PermissionRequest` (**Doc**) | Plugin ([**3P**](https://github.com/DEVtheOPS/opencode-plugin-otel)) | No event (**Gap**); an `ask_permission` tool match is **Unverified** |
| Question wait opens | Tool hook on the question tool (**Unverified**) | **Unverified** | **Unverified** | **Unverified** |
| Wait answered, denied or cancelled | Pairing **Unverified**; `PermissionDenied` exists (**Doc**) | Pairing **Unverified** | **Unverified** | **Gap** |
| Tool and test timing | `PreToolUse`, `PostToolUse` (**Doc**); transcript (**Seen**) | Same hooks; hosted tools skip them (**Doc**) | Tool times in its store (**3P**) | `PreToolUse`, `PostToolUse` (**Doc**) |
| Model request timing | OpenTelemetry request duration (**Doc**); transcript turn durations and session API total (**Seen**) | `Pre`/`PostModelRequest` (**Doc**), pairing **Unverified**; task start and end in session log (**Seen**) | **Unverified** | `Pre`/`PostInvocation` (**Doc**), pairing **Unverified** |
| Time to first token | Beta tracing only (**Doc**) | **Gap** | **Gap** | **Gap** |
| Subagent | `SubagentStop` (**Seen**), start (**Doc**) | Start and stop (**Doc**) | Parent link (**3P**) | Tool match on `invoke_subagent` (**Doc**, use **Unverified**) |
| Compaction timing | `PreCompact`, `PostCompact` (**Doc**) | Same (**Doc**) | **Unverified** | **Gap** |
| Token usage | Transcript (**Seen**) | Session log (**Seen**); `PostModelRequest`, may be null (**Doc**) | SQLite store ([**3P**](https://pkg.go.dev/github.com/elephaant/shiplino/pkg/adapters/opencode)) | No hook (**Gap**); partial from local files ([**3P** parser](https://github.com/kenn-io/agentsview)) |
| Quota percentage | Statusline, subscribers only (**Doc**; read by a script here, **Seen**). Headless and background sessions **Unverified** | 5-hour and weekly limits in session log (**Seen**) | **Gap** | **Gap** |
| Active time | OpenTelemetry, typing plus reading (**Doc**) | **Gap** | **Gap** | **Gap** |
| Attention raised by workflow commands | Fovea commands | Same | Same | Same |

| Host | Coverage |
| --- | --- |
| macOS | Where **Seen** signals were observed, unless noted otherwise |
| Linux | Supported target. **No hook signal above is verified on Linux** |
| Windows | **Gap**; not supported |
| Cloud sessions | **Gap**: not reachable over SSH and their disks disappear. Reports say so; GitHub or the tracker is the only trace |

## Storage, collection and retention

| Item | Design |
| --- | --- |
| Local log | `${XDG_STATE_HOME:-~/.local/state}/fovea/telemetry/log/<YYYY-MM>.jsonl`, one event per line |
| Pulled copies | `…/telemetry/hosts/<host_id>/`, as received |
| Index | Optional SQLite built from the logs. It can be deleted and rebuilt, and is never synced |
| Price and plan tables | Dated configuration files |
| Pool | Set per host. A host belongs to one pool and lists only that pool's hosts |
| Pull | A report or pull command runs Fovea's export command over SSH, asking for events after the last `seq` it holds from that `host_id` |
| Checks | The remote refuses a different pool. The importer rejects events from another pool, drops repeated `event_id`s, and flags a repeated ID with different content |
| Newer schema | Kept as received and reported as unreadable |
| Offline host | The report uses the last copy and shows its pull time. The pull enforces its own timeout |
| Rebuilt host | Gets a new `host_id`; old events stay under the old one |
| Retention | Forever. A manual purge removes chosen events; run it on every host holding a copy, and rebuild indexes. Purged IDs are listed so a pull can't restore them |
| Backup | **Open risk.** Pulled copies exist only on hosts that pulled, so they aren't a backup |
| Transcripts | Never copied or synced |

Account labels must match across a pool's hosts so quota samples can be joined.

## Exclusions

**Never stored:** prompts, responses, reasoning, tool input or output, command text, diffs, code, environment values, credentials, email or account IDs, hostnames, IP addresses, error message text, or absolute paths other than `transcript_path`.

| Allowed free text | Cap (characters) |
| --- | --- |
| Finding `claim` and `reason` | 200 each |
| Attention `request`; `drop_reason` | 200 each |
| Attention `effort` | 40 |
| Workstream `title` | 120 |
| Tracker labels and type, `category`, `estimate` | 100 each |

- Identifiers are also stored: slugs, branches, repo names, ticket URLs, repo-relative file paths, and command, skill, tool, model and subagent type names.
- `command_fingerprint` is a hash keyed with a per-pool secret. It spots reruns without storing the command.
- The writer drops fields not on a type's allowlist. Inputs that carry content, such as OpenTelemetry or transcripts, are filtered before anything is written.
- **A cap can't stop an agent quoting code or a secret in a summary.** Prompts that produce these fields must forbid it, and logs stay private.

## Imported data

Fovea accepts events from outside importers and knows nothing about their source formats. An importer must:

- write this schema, setting `imported` and a deterministic `event_id`, so reruns add nothing;
- mark guessed values `quality: inferred`, including any workstream ID it makes;
- leave unknown fields absent and record a `gap.recorded` rather than guessing zero. The writer lets imported events omit required fields beyond the [common ones](#common-fields) when the source lacks them.

Reports can include or exclude imported data. The dotfiles importer is specified [outside this design](../workflow-telemetry-migration.md).

## Before implementation

In priority order. Each can change an adapter or mark a signal unsupported.

1. **Waits:** record what each agent emits on approve, deny, answer, interrupt, idle, crash and parallel prompts.
2. **Your input:** check that automated prompts and pasted or dictated text can be told apart.
3. **Linux:** verify the hooks.
4. **Usage trial:** compare our parsers, agentsview and [ccusage](https://github.com/ccusage/ccusage) on all four agents, including resume, fork, compaction, subagents and aborted turns. For agentsview, also check its usage-only mode keeps no content, totals survive deleted transcripts and upgrades, and its network traffic can be turned off.
5. **Quota:** confirm the statusline runs in background sessions, and check the precision of percentages.
6. **Claude OpenTelemetry:** measure what is lost when no local receiver is running.
7. **Volume:** measure log growth with tool spans, given keep-forever.

## Appendix: existing tools

Checked 2026-11-27 from docs and source only; nothing was installed. Several long pages and files were read only in part.

| Option | Finding | Basis | Verdict |
| --- | --- | --- | --- |
| OpenTelemetry as the foundation | Claude exports the most. I found no native export for agy. Codex tool events can include [full arguments](https://raw.githubusercontent.com/openai/codex/main/codex-rs/otel/src/tool_result.rs). [GenAI conventions](https://github.com/open-telemetry/semantic-conventions-genai) are still in development, and I found none for multi-session work. The [collector](https://opentelemetry.io/docs/collector/resiliency/) can lose data, and Fovea would still need its own index | Vendor docs and source; agy absence from a [third-party guide](https://signoz.io/docs/antigravity-cli-monitoring/) | Input only |
| [agentsview](https://github.com/kenn-io/agentsview) (MIT) | Local archive with parsers for all four agents and a usage-only mode. agy and cost coverage have gaps. I found no human-wait measure or custom event interface. Its [SSH sync](https://www.agentsview.io/docs/remote-access/) mirrors raw transcripts, so Fovea would not use it. `prune` also deletes source files | Vendor docs and source; **untested** | Trial as a usage source |
| [ccusage](https://github.com/ccusage/ccusage) (MIT) | Token and cost totals from local transcripts for all four agents | Vendor docs; untested | Trial cross-check |
| Hosted or self-hosted LLM observability platforms | Built around traces, not workstreams or review findings | Vendor docs, survey level | Skip |
