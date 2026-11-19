# Project review config

Inputs for the periodic, whole-project review (`/project-review`). Not for PR or diff review. Lenses read this file; keep project facts here, not in lens agents.

## Planning docs

Roles, not names. A role absent here falls back to `governor.md` § Key documents.

- roadmap: `docs/workstream-roadmap.md`
- capacity-targets: `<path>`
- current-focus: `<path>`

## Review state

Paths the apply step may edit. Omit a line to make that item report-only.

- backlog: `<path>`
- archive: `<path>`
- pending-actions: `docs/local/pending-actions.md`

## Cadence

- Window: 7
- Activity globs: `<glob>`, `<glob>`

## Scope

Subsystem → paths, for the architecture lens.

- claude config (commands, agents, skills): `dot_claude/`
- tools: `tools/`
- cloud and host adapters: `workflow/`
- docs: `docs/`

## Invariants

Each probe is a deterministic command with its expected result.

- workflow manifest is current: `bash tools/workflow-manifest.test.sh` → exit 0
- FAST suite passes: `for t in tools/workflow-manifest.test.sh tools/cloud-workflow-adapter.test.sh tools/project-test-commands.test.sh; do bash "$t" || exit 1; done` → exit 0

Conventions docs:

- `CLAUDE.md` — layout, tests, the two-checkout rule

## Lenses

Skip: <lens-name>, <lens-name>

## Actions

What `/project-review-apply` does with the report. Omit this section for report-only.

- file-tickets: off
<!-- off | <severity> <status>: file tickets for findings at that severity or higher (P0-P3); status NEW or ANY. e.g. `P1 NEW` -->
- ticket-labels: `review`
- queue-ticket-closures: on
<!-- on: queue triage closures and redefinitions in § Review state pending-actions; tickets are never closed or edited -->
- doc-pr: off
<!-- on: one PR updating the § Review state docs -->

## Delivery

file:docs/local/project-review-output.md
<!-- inline | file:<path> | email:<address> -->
- fallback: inline
<!-- used when email has no mail connector: inline | file:<path> -->
