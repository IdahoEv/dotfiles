# Moving from dotfiles telemetry to Fovea

**The old log is never changed.** The dotfiles reports keep reading it. An optional one-time importer, which lives in dotfiles, converts a copy into [Fovea's format](fovea/telemetry-design.md#imported-data); Fovea never reads the old format. The importer is not built.

[Current behavior](workflow-telemetry.md) describes the existing events (`v: 1`).

## Reading old logs

| Topic | Rule |
| --- | --- |
| Old reports | `wf-report.sh`, `wf-backfill.sh` and `wf-review-gaps.sh` keep working on `${XDG_STATE_HOME:-~/.local/state}/workflow-telemetry/events.jsonl`, or `WF_TELEMETRY_LOG` |
| Keeping history | Don't run `wf-report.sh --prune`; it deletes events from the original |
| Tokens, cost, test time | The old reports compute these from transcripts. With no transcripts, tokens and cost show unknown but tests show zero; with some missing, totals are partial, flagged only by `!` lines. Only an import made before they expire can keep them |
| Switch-over | Dotfiles logging continues until Fovea replaces it. Where both logged the same period, import only events before Fovea started on that host |

## Old IDs to new IDs

| Old | New | Rule |
| --- | --- | --- |
| `run_id` `owner/repo#N` | `tickets: [{github, N}]`, `repo` | A chain's other tickets come from `ticket.start chain` |
| `run_id` `sc-N` | `tickets: [{shortcut, N}]` | One story can span repos |
| (none) | `workstream_id` | Inferred: `ws-` + 12 hex digits of a hash of pool, `run_id` and `repo`, so each repo gets its own. Work that reused a ticket after being abandoned can't be separated |
| `session_id` | `<tool>-<native_id>` | The log doesn't name the agent, and Codex hooks can write to it too. `claude` or `codex` only when that agent's transcript or session log has the ID; otherwise `unknown-<id>` |
| empty `session_id` | absent | Many script events have none |
| (none) | `event_id` | Hash of the source's host ID, the raw line and its occurrence number among identical lines |
| (none) | `host_id`, `pool` | Those of the host that wrote the log. Run the import there |
| (none) | `seq`, `logged_at` | Assigned by that host's Fovea writer, so imports never collide with its pull cursor; `time` keeps the old `ts` |
| `job_id` | dropped | No Fovea use |

Every imported event has `imported.source: "dotfiles-v1"` and `quality: inferred` wherever a value was derived. A required field with no source below stays absent ([imports may omit it](fovea/telemetry-design.md#imported-data)). For `command.completed`, `outcome` `fail` becomes `failed`; `ok`, `stopped` and `handoff` carry over.

## Events

| Old event | Fovea | Import notes |
| --- | --- | --- |
| `ticket.start` | `command.completed` (`kickoff`); first success also infers `workstream.created` | No title, labels or ticket type; `provider` and `chain` carry over |
| `session.launch` | `command.completed` (`session-launch`) | |
| `session.start` | `session.started` | `source` becomes `entry`; `interface` is unknown, imported as a gap |
| `session.end` | `session.ended` | `clear` stays; any other reason becomes `exit`, inferred |
| `session.fail` | `turn.ended` (`failed`) | `error` becomes `error_type` |
| `subagent.stop` | `span.completed` (`subagent`) | End only, so no duration |
| `phase` `PLAN`, `WIP`, `REVIEW` | `workstream.stage` | |
| `phase` `REVIEWED` | `workstream.stage` (`review`) | Not proof that any single review was accepted |
| `phase` `MERGED` | none | Used to infer a merge; no PR number, so no `pr.state` unless another event supplies one |
| `phase` `DONE` | `workstream.closed` (`finished`) | See [outcomes](#outcomes) |
| `review.round` | `review.state` | `state=start` is `round_started`, `end` is `round_ended`; `end` doesn't mean accepted. Missing `source` is `local`; `status` is absent. A `backfill` line adds no event: its `sha` fills the original's `head_sha` |
| `review.result` | `review.state` (`summary`) with counts | Cycle or batch totals, not a round's. `source=bot` becomes `github` |
| `review.launch` | `review.launch` | See [launch tokens](#launch-tokens) |
| `review.finding` | `review.finding` | See [findings](#findings) |
| `pr.open` | `command.completed` (`open-pr`); on success also `pr.state` (`open`) | |
| `pr.watch` | `command.completed` (`review-watch`) | The old outcome becomes `reason`; `outcome` is absent |
| `finalize.check` | `command.completed` (`finalize-check`) | `verdict` becomes `reason`; `outcome` is absent; `ready` implies a merged PR |
| `finalize.run` | `command.completed` (`finalize`) | `ok` also supports a `finished` outcome |

### Findings

| Fovea field | Rule |
| --- | --- |
| `finding_id` | Bot: derived from `comment_id`. Otherwise the new `event_id`, because old IDs repeat across cycles |
| `group_id` | Old `finding_id` or legacy `key`; with neither, the new `finding_id` |
| `external_id` | `comment_id` |
| `verdict`, `validity` | Absent if missing |

A local `backfill` finding with `matched_ts` fills text into the original. One without it is skipped and counted, as the old reports ignore it. Bot `backfill` findings are imported.

### Launch tokens

If no transcript-derived usage exists for the launch's subagent, `tokens_out` becomes `output` in an incomplete `usage.snapshot`. `tokens_in` is dropped: it mixes cached and uncached input.

### Other lines

- **Undocumented fields** exist on some `review.finding` and `review.launch` lines, such as `disposition`, `file`, `status` and `summary`. The importer ignores them and counts what it ignored. It copies only fields on Fovea's allowlist.
- **Bad lines** are skipped and counted. At least one line in a real log has a whole argument string as its event name.
- **Branches:** Fovea takes a branch only from imported `workstream.created` and `pr.state`.

### Outcomes

A `finalize.run` with `outcome=ok`, or `phase=DONE`, gives an inferred `finished` close. `MERGED` or a ready check alone doesn't, because a merge no longer ends a workstream. Every other run gets no close event. **The old log never records a drop.**

### What can't be recovered

| Missing | Effect |
| --- | --- |
| Prompt, turn and wait events | No waiting, idle or typing figures for old work |
| Sessions outside ticket branches | Never logged |
| Purpose, role, links | Inferred links only, from a session appearing in a run |
| Ticket type, labels, estimate | Unknown unless you refetch them from the tracker, marked inferred |
| Quota samples | No quota share |

If transcripts still exist, the same run can append `usage.snapshot` and test spans through Fovea's usage adapter. Prompt labels can be added the same way. Both need to happen before transcripts expire.

## Reports

| Old report | Fovea [question](fovea/telemetry-design.md#questions-telemetry-must-answer) or rule |
| --- | --- |
| `wf-report.sh` run table, `--run`, `--detail`, `--json` | 1, 3, 11, per workstream instead of per ticket run |
| Wall time and stage time | 3, 13, now split into agent, you and idle |
| Tokens and estimated cost by model and stage | 1, plus quota and fee share |
| Peak parallel sessions, summed session time | Derived from session and turn events |
| Review rounds, fixed, dismissed, deferred, validity, overlap, dismissed reasons | 5, 7 |
| Reviewer mix vs rounds | 7 |
| Test runs, failures, reruns, time | 4 |
| Start, PR-open and session failures | 9 |
| Statuses `done`, `merged`, `interrupted`, `stalled`, `open` | `finished` or `dropped` from `workstream.closed`; merged from `pr.state`; interrupted and stalled derived from the last turn and the gap since (default 24 hours) |
| Medians only with at least 3 merged runs | Keep the guard for finished workstreams |
| `--usage` by day, ticket, stage, agent, model, type, sessions | 2 and 15; "type" becomes session purpose, and "agent" splits into agent tool and subagent type |
| `--prune` | Manual purge; nothing is deleted by default |
| `!` gap lines | [Missing data](fovea/telemetry-design.md#missing-data) |
| `wf-backfill.sh` (local and `--bot` recovery) | Importer for old data; new data records these fields when they happen |
| `wf-backfill.sh --live` | Bot-comment adapter writing `review.finding` and `review.state` |
| `wf-review-gaps.sh` | 6 |
| `review.result` updating the statusline's round count | Not telemetry: the statusline reads the workstream record's `reviews` |
