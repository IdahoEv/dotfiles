# Workflow telemetry

Workflow scripts and session hooks append events to a local JSONL log. `wf-report.sh` joins those events with Claude Code session transcripts and reports wall time, per-stage time, tokens, estimated cost, review rounds and outcomes (including per-reviewer validity and overlap), and test time for each ticket run. Token counts are measured. Cost is an **estimate** from a pinned price table. Anything the sources didn't record is printed as `unknown` with a reason, never as zero.

## Use

```bash
wf-report.sh                          # runs active in the last 14 days + medians
wf-report.sh --since 30d --detail     # plus per-run breakdowns
wf-report.sh --run idahoev/dotfiles#40
wf-report.sh --json                   # same data, machine-readable
wf-report.sh --prune 90               # delete events older than 90 days
wf-report.sh --usage --since 10d      # tokens across ALL sessions (see below)
```

| Setting | Default |
| --- | --- |
| Log | `${XDG_STATE_HOME:-~/.local/state}/workflow-telemetry/events.jsonl`; override with `WF_TELEMETRY_LOG` |
| Disable | `WF_TELEMETRY=0` |
| Retention | Kept until `--prune` |
| Transcripts | `~/.claude/projects`; override with `WF_CLAUDE_PROJECTS` |
| Test-command pattern | `WF_TEST_RE` or `--test-re` (Python regex; see `wf_usage.DEFAULT_TEST_RE`) |

Setup: merge, pull the deploy clone, then run `chezmoi apply ~/.claude/settings.json` to register the hooks.

## Token usage across all sessions

`wf-report.sh --usage` reads every transcript under the projects dir, not only ticket runs. Tokens (input, output, cache read, cache write) are measured and summed in full whatever the model or price table. `--by day|ticket|stage|agent|model|type|sessions` restricts the breakdowns (repeatable; default all); `--top N` sizes the session list; `--json` emits the same data.

| View | Grouping |
| --- | --- |
| day | UTC date of the message |
| ticket | Telemetry `run_id` for sessions seen in a run; else the worktree directory name for numbered worktrees; else `—` |
| stage | The run's PLAN…DONE stage at the message time (`—` outside runs) |
| agent | `main`, or the subagent type from `agent-*.meta.json` |
| model | `message.model` |
| type | `ticket` (session in a run, or cwd basename like `121-slug` / `sc-1-slug`), `governor/jobs` (cwd under `.claude/jobs/` or a `governor` worktree), else `other` |
| sessions | Top N by output: session id, cwd, messages, tokens, span, top model by output. No prompt content is read |

The **weighted** column applies the list-price table as a relative-weight proxy for quota burn. It is not billing. A model missing from the table adds tokens but no weight: a group with some such usage shows its weight with `*` (partial), one with only such usage shows `n/a`. Totals never depend on it.

To weight a non-Anthropic model, add it to `model-pricing.json` `models` with `input`, `output`, `cache_read` (USD per 1M tokens) plus `source` and `as_of` supplied by the owner; no rates are committed by default. Messages are deduplicated by `message.id` across all files, so resumed sessions don't double count.

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
| `review.round` | `github-review-state.sh --set-local` | `round`, `state=start\|end`, `sha` (head commit at the emit) |
| `review.result` | Review prompts, one line at cycle end (bot batches: final report only) | `round`, `fixed`, `dismissed`, `deferred`, `reviewers`, `source=bot` for PR-bot batches. Bot-batch `deferred` means Skipped (nothing filed), unlike the local cycle's deferred-with-issue |
| `review.launch` | `local-review-cycle-manager`, one line per reviewer launch | `reviewer`, `round`, `model` (launch override or the reviewer's `model` frontmatter; `auto` stays `auto`), `effort` (only when set), `source=local`. Model-reported |
| `review.finding` | `local-review-cycle-manager`, one line per triaged finding; `/github-review-comments`, one line per Copilot comment (`source=bot`, `reviewer=copilot`, plus `comment_id`, no `round`) | `source=local\|bot`, `reviewer`, `severity`, `verdict=fixed\|dismissed\|deferred`, `validity=valid\|rejected\|partial` (the triager's judgment of the finding itself, independent of the verdict), `round`, `reason` (required for dismissed/deferred; short phrase, no code or prompt text), `path`, `line` (omitted for file-level findings), `claim` (one sentence naming the file and what is wrong, truncated to 200 characters), `finding_id` (`r<k>-<n>` within a run, shared by reviewers who raised the same triaged finding; local, required on valid/partial), `sha` (bot findings: the commit the comment was made on; local findings join the `state=start` `review.round sha` by `round`). Events before this schema carry a sha256 `key` instead of `finding_id`. `wf-report.sh` renders per-reviewer verdict and validity counts, dismissed findings with reasons, and overlap |
| `pr.open` | `open-pr.sh`, including failures | `outcome`, `exit_code`, `duration_ms`, `pr_number`, `pr_action`, `review` |
| `finalize.check` | `finalize-check.sh` | `verdict`, `pr_number`, `pr_state` |
| `finalize.run` | `finalize-run.sh` | `outcome=ok\|stopped\|handoff`, `reason` (verdict or handoff reason; empty on ok) |
| `pr.watch` | `open-pr-watch.sh`, once when the review poll ends | `pr_number`, `exit_code`, `outcome=comments\|timeout\|no-pr\|signed-off\|reviewer-unavailable\|error` |

Every line also carries `v`, `ts` (UTC wall clock in ms, used for cross-process ordering), `run_id`, `repo`, `ticket`, `branch`, `session_id`, and `job_id`. `duration_ms` uses a monotonic clock.

Logs hold only identifiers, counts, and Claude Code enum values: no prompts, diffs, command text, transcript paths, or environment. The one free-text exception is `review.finding claim`: one sentence naming a file and what is wrong, never a code excerpt. The logger only strips control characters and truncates; wording is the reporting agent's, so offline matching must tolerate varied phrasing. Values are scalars of at most 200 characters, and hook free text becomes `other`. Each line stays far below PIPE_BUF, so concurrent appends from parallel worktrees don't interleave. A failed write prints a warning and the workflow continues.

### Overlap methodology

`finding_id` on local `review.finding` events is assigned by the cycle manager when it dedupes reviewers' findings: reviewers that raised the same triaged finding share one id. A finding overlaps when the same id is raised by ≥2 *distinct* reviewers; a reviewer re-raising it across rounds is not overlap. Bot findings carry no `finding_id`; matching them to local findings ("why didn't we find that?") is an offline pass over `path`, `line`, `claim` and `sha` (map lines between SHAs with `git diff`), comparing only findings in the same file and one representative per id group. Legacy events carry a `key` hash of path + 10-line bucket + normalized claim; `wf-report.sh` still counts overlap on it, and exact-wording matching makes it a lower bound.

## Backfill

`wf-backfill.sh --pr N [--pr M] [--branch B] [--repo owner/repo] [--git-dir DIR] [--dry-run]` recovers finding text, round SHAs and reviewer model for PRs that finished `/local-review-cycle` before those fields were logged. It is time-boxed by transcript retention: run it before the session is finalized and pruned. It reads only the log, the reviewer subagent transcripts and git history, and names no project, so it works for any repo in the log.

| Recovered | Source |
| --- | --- |
| `review.round sha` | Last first-parent commit at or before the existing round event's `ts` |
| `review.launch` model, `tokens_in`, `tokens_out` | Reviewer subagent transcript, one per launch |
| `review.finding` `path`, `line`, `claim` | The reviewer's final report, parsed from the `SEVERITY \| file:line \| defect` lines. The claim is path + first sentence of the defect, not the triager's wording. No `finding_id` is assigned: that is the cycle manager's cross-reviewer judgment and is not recoverable, so backfilled findings add no overlap |

Every appended event carries `backfill=1`. Backfilled `review.finding` events carry no verdict; `matched_ts` points at the original triage event, paired by reviewer, round, severity and order. `wf-report.sh` ignores them: they carry text for the offline comparison, not verdict, validity or overlap. Re-running appends nothing: an event is skipped when its (event, branch, reviewer, round, agent) identity already exists with `backfill=1`. Existing lines are never rewritten.

A reviewer re-launched within a round (an aborted attempt) keeps a launch event for its real cost, but only the latest attempt's findings are backfilled. Sessions without local transcripts (cloud) get round SHAs only; the per-PR summary lists the rest, plus reviewer effort (never in transcripts), as `unknown`. The PR's `## Review` line is shown for reference.

## Measured vs. estimated

| Number | Source | Kind |
| --- | --- | --- |
| Tokens (input, output, cache read, cache write 5m/1h) | Transcript `message.usage`, deduplicated by `message.id`, for the run's sessions and their subagents | Measured |
| Cost | Tokens × `tools/lib/model-pricing.json` (first-party list price, as-of date inside) | Estimate |
| Stage time | Intervals between `phase` events | Measured |
| Test time / reruns | Transcript Bash calls matching the test pattern, timed from tool_use to tool_result; a rerun is the same command repeated | Heuristic |
| Findings fixed / dismissed / deferred | `review.result` (totals) and `review.finding` (per finding, with reviewer and reason), reported by the model | Self-reported |
| Validity (valid / rejected / partial) | `review.finding validity`, the triager's judgment, reported by the model | Self-reported |
| Round head SHA | `review.round sha`, read by `github-review-state.sh` at the emit | Measured |
| Reviewer model / effort | `review.launch`, reported by the model from frontmatter or the launch | Self-reported |
| Reviewer overlap | `review.finding finding_id` (or legacy `key`), assigned by the model | Self-reported |

## Limitations

- Transcripts are Claude Code internals, not an API. `tools/lib/wf_usage.py` is the only reader, so a format change is fixed there.
- Usage is counted only for sessions that emitted an event inside the run, between the run's first and last event. Launcher sessions (`/start`, the governor) are excluded.
- Models missing from the price table (e.g. routed `glm-*`) leave a run's cost `unknown`. Their tokens are still counted, and `--usage` shows them with weight `n/a` without blanking other totals.
- Cost is at list price. It ignores plan billing and Bedrock/Vertex rates.
- `review.result` and `review.finding` are the model-emitted events and a deliberate exception to "deterministic emits only": the fixed/dismissed/deferred triage exists nowhere but the model's context. If the model skips them, findings show as unknown. Round counts still come from `github-review-state.sh`.
- `validity` is the triager's judgment, not ground truth, and is independent of the verdict — e.g. a `partial` finding (right concern, wrong location) may still be fixed. Pre-change events lack `validity`/`finding_id`/`key` and count as `unreported`; events before this schema also lack `path`/`line`/`claim`/`source`/`sha` and `review.launch`, and those can be recovered only by `wf-backfill.sh`, from local transcripts (see Backfill).
- Overlap rests on the cycle manager's judgment that two reviewers' findings are the same; it covers local reviewers within one run only. Legacy hash keys under-count: they require identical wording and the same 10-line bucket. The aggregate "reviewer mix vs rounds" table is a description of small samples, not a causal claim.
- `--prune` can lose an event appended in the instant between its final copy and the file swap. Prune when no sessions are active. A `kill -9` mid-prune leaves `events.jsonl.lock` behind; remove it by hand.
- The test pattern is a heuristic. A command that merely mentions a runner inside quotes can match.
- Runs from before the hooks were installed have no events.

## Comparing before/after

1. Record the baseline: `wf-report.sh --since <window> --json > before.json`. Use at least 3 merged runs and note the commit of the workflow change.
2. Land the change, then collect a similar number of comparable tickets.
3. Compare medians of wall time per merged ticket, estimated cost, and review rounds. Read cost and rounds alongside `fixed`/`deferred` counts. Fewer tokens with more deferred findings is not a win.
4. Check the `!` gap lines first. A run with unknown tokens or no phase events doesn't belong in the comparison.
