# Workflow telemetry

Workflow scripts and session hooks append events to a local JSONL log. `wf-report.sh` joins those events with Claude Code session transcripts and reports wall time, per-stage time, tokens, estimated cost, review rounds and outcomes (including per-reviewer validity and overlap), and test time for each ticket run. Token counts are measured. Cost is an **estimate** from a pinned price table. Anything the sources didn't record is printed as `unknown` with a reason, never as zero.

## Use

```bash
wf-report.sh                          # runs active in the last 14 days + medians
wf-report.sh --since 30d --detail     # plus per-run breakdowns
wf-report.sh --run idahoev/dotfiles#40
wf-report.sh --json                   # same data, machine-readable
wf-report.sh --prune 90               # delete events older than 90 days
```

| Setting | Default |
| --- | --- |
| Log | `${XDG_STATE_HOME:-~/.local/state}/workflow-telemetry/events.jsonl`; override with `WF_TELEMETRY_LOG` |
| Disable | `WF_TELEMETRY=0` |
| Retention | Kept until `--prune` |
| Transcripts | `~/.claude/projects`; override with `WF_CLAUDE_PROJECTS` |
| Test-command pattern | `WF_TEST_RE` or `--test-re` (Python regex; see `wf_usage.DEFAULT_TEST_RE`) |

Setup: merge, pull the deploy clone, then run `chezmoi apply ~/.claude/settings.json` to register the hooks.

## Runs

The run id is `owner/repo#<issue>` for GitHub issues and `sc-<id>` for Shortcut stories, so worktrees across repos for the same story share one run. It comes from the checked-out branch (`gt::ticket_from_branch`). Events emitted outside a ticket branch are dropped.

| Status | Meaning |
| --- | --- |
| `done` / `merged` | `phase=DONE` / `phase=MERGED` or `finalize.check verdict=ready` |
| `interrupted` | The run's last event is a `StopFailure` |
| `stalled` | No event or token usage for 24h (`--stale-hours`) |
| `open` | Anything else |

Medians per merged ticket are shown only once there are ≥3 merged runs; the same guard gates the reviewer-effectiveness, overlap, and reviewer-mix-vs-rounds aggregate lines.

## Events

| Event | Emitted by | Fields |
| --- | --- | --- |
| `ticket.start` | `start-ticket.sh` (create / `--no-tab`) | `outcome`, `exit_code`, `duration_ms`, `mode`, `launcher`, `provider`, `ticket_in_progress` |
| `session.launch` | `start-ticket.sh --tab-only` | same |
| `session.start` / `session.end` / `session.fail` / `subagent.stop` | `wf-event.sh --hook` on SessionStart / SessionEnd / StopFailure / SubagentStop | `source` / `reason` / `error` / `agent_type` |
| `phase` | `agent-phase.sh` (set and `--no-review`) | `phase` |
| `review.round` | `github-review-state.sh --set-local` | `round`, `state=start\|end` |
| `review.result` | Review prompts, one line at cycle end (bot batches: final report only) | `round`, `fixed`, `dismissed`, `deferred`, `reviewers`, `source=bot` for PR-bot batches. Bot-batch `deferred` means Skipped (nothing filed), unlike the local cycle's deferred-with-issue |
| `review.finding` | `local-review-cycle-manager`, one line per triaged finding | `reviewer`, `severity`, `verdict=fixed\|dismissed\|deferred`, `validity=valid\|rejected\|partial` (the triager's judgment of the finding itself, independent of the verdict), `round`, `reason` (required for dismissed/deferred; short phrase, no code or prompt text), `key` (sha256 overlap hash; required on valid/partial). `wf-report.sh` renders per-reviewer verdict and validity counts, dismissed findings with reasons, and overlap |
| `pr.open` | `open-pr.sh`, including failures | `outcome`, `exit_code`, `duration_ms`, `pr_number`, `pr_action`, `review` |
| `finalize.check` | `finalize-check.sh` | `verdict`, `pr_number`, `pr_state` |

Every line also carries `v`, `ts` (UTC wall clock in ms, used for cross-process ordering), `run_id`, `repo`, `ticket`, `branch`, `session_id`, and `job_id`. `duration_ms` uses a monotonic clock.

Logs hold only identifiers, counts, and Claude Code enum values: no prompts, diffs, command text, transcript paths, or environment. Values are scalars of at most 200 characters, and hook free text becomes `other`. Each line stays far below PIPE_BUF, so concurrent appends from parallel worktrees don't interleave. A failed write prints a warning and the workflow continues.

### Overlap methodology

`key` on `review.finding` is `sha256(path + "\n" + bucket + "\n" + claim)`, where path is the repo-relative file exactly as `git diff --name-only` prints it, bucket is the 10-line decade of the finding's primary line (`L41-L50`; `L0` for file-level), and claim is one normalized sentence stating only the file and what is wrong. The exact normalization recipe lives in `local-review-cycle-procedure`; only the hash is logged. A finding overlaps when the same key is raised by ≥2 *distinct* reviewers — the same reviewer re-raising it across rounds is not overlap. Phrasing drift means two reviewers wording the same bug differently produce different hashes, so overlap is a lower bound.

## Measured vs. estimated

| Number | Source | Kind |
| --- | --- | --- |
| Tokens (input, output, cache read, cache write 5m/1h) | Transcript `message.usage`, deduplicated by `message.id`, for the run's sessions and their subagents | Measured |
| Cost | Tokens × `tools/lib/model-pricing.json` (first-party list price, as-of date inside) | Estimate |
| Stage time | Intervals between `phase` events | Measured |
| Test time / reruns | Transcript Bash calls matching the test pattern, timed from tool_use to tool_result; a rerun is the same command repeated | Heuristic |
| Findings fixed / dismissed / deferred | `review.result` (totals) and `review.finding` (per finding, with reviewer and reason), reported by the model | Self-reported |
| Validity (valid / rejected / partial) | `review.finding validity`, the triager's judgment, reported by the model | Self-reported |
| Reviewer overlap | `review.finding key` (hash identity across reviewers), reported by the model | Self-reported, lower bound |

## Limitations

- Transcripts are Claude Code internals, not an API. `tools/lib/wf_usage.py` is the only reader, so a format change is fixed there.
- Usage is counted only for sessions that emitted an event inside the run, between the run's first and last event. Launcher sessions (`/start`, the governor) are excluded.
- Models missing from the price table (e.g. routed `glm-*`) leave the total cost `unknown`. Their tokens are still counted.
- Cost is at list price. It ignores plan billing and Bedrock/Vertex rates.
- `review.result` and `review.finding` are the model-emitted events and a deliberate exception to "deterministic emits only": the fixed/dismissed/deferred triage exists nowhere but the model's context. If the model skips them, findings show as unknown. Round counts still come from `github-review-state.sh`.
- `validity` is the triager's judgment, not ground truth, and is independent of the verdict — e.g. a `partial` finding (right concern, wrong location) may still be fixed. Pre-change events lack `validity`/`key` and count as `unreported`.
- Overlap under-counts: hash identity requires both reviewers to follow the same normalization and land in the same 10-line bucket. The aggregate "reviewer mix vs rounds" table is a description of small samples, not a causal claim.
- `--prune` can lose an event appended in the instant between its final copy and the file swap. Prune when no sessions are active. A `kill -9` mid-prune leaves `events.jsonl.lock` behind; remove it by hand.
- The test pattern is a heuristic. A command that merely mentions a runner inside quotes can match.
- Runs from before the hooks were installed have no events.

## Comparing before/after

1. Record the baseline: `wf-report.sh --since <window> --json > before.json`. Use at least 3 merged runs and note the commit of the workflow change.
2. Land the change, then collect a similar number of comparable tickets.
3. Compare medians of wall time per merged ticket, estimated cost, and review rounds. Read cost and rounds alongside `fixed`/`deferred` counts. Fewer tokens with more deferred findings is not a win.
4. Check the `!` gap lines first. A run with unknown tokens or no phase events doesn't belong in the comparison.
