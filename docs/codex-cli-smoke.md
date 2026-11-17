# Local Codex CLI smoke evidence

The real native task completed two turns and retained its token; the implementing session recorded a successful CLI resume. Ordered groups, failure recovery and provider integration remain automated-test coverage rather than end-to-end smoke results.

Observed on 2026-11-14; transcript evidence rechecked on 2026-11-16. Installation versions recorded during implementation: CLI 0.166.0, running daemon 0.169.0.

| Check | Evidence | Result |
| --- | --- | --- |
| Independent task | UUID `01a1d7f7-2209-79e0-8912-100833c5b17f`, title `[TALK] Is185 CLI Smoke`, cwd `/private/tmp/codex-parity-smoke` | Native task exists separately from implementer |
| Initial turn | Prompt requested no tools/edits and exact response `PARITY_185_731` | Completed with that response |
| Later steering | Follow-up asked which token to remember, again without tools/edits | Second completed turn returned `PARITY_185_731` |
| Interactive CLI resume | `codex resume 01a1d7f7-2209-79e0-8912-100833c5b17f` | Prior implementer recorded original cwd and both responses displayed |
| Current verification | Native `read_thread` inspected both completed turns and task metadata | Confirmed task identity, cwd, title and token retention |

CLI-resume evidence comes from implementer task `01a1d793-2cb3-7423-972e-9e8c2bd13f87`, whose final interrupted turn reports skipping the update prompt and continuing without trusting hooks; no global setting changed. Review did not rerun the interactive CLI or inspect its terminal recording.

This smoke did not exercise real ticket setup, ordered multi-ticket launches, review/repair, PR creation or finalize. See [validation commands](codex-cli-workflow.md#validation) for fixture-based protocol, lifecycle and existing-Claude regression coverage.
