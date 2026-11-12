# Project review config

Inputs for the periodic, whole-project review (`/project-review`). Not for PR or diff review. Lenses read this file; keep project facts here, not in lens agents.

## Planning docs
Roles, not names. A role absent here falls back to `governor.md` § Key documents.
- roadmap: `<path>`
- capacity-targets: `<path>`
- current-focus: `<path>`

## Review state
Paths the apply step may edit. Omit a line to make that item report-only.
- backlog: `<path>`
- archive: `<path>`
- pending-actions: `<path>`

## Cadence
- Window: 7
- Activity globs: `<glob>`, `<glob>`

## Scope
Subsystem → paths, for the architecture lens.
- <subsystem>: `<path>`, `<path>`

## Invariants
Each probe is a deterministic command with its expected result.
- <invariant>: `<command>` → <expected result>

Conventions docs:
- `<path>` — <what it governs>

## Lenses
Skip: <lens-name>, <lens-name>

## Delivery
inline
<!-- inline | file:<path> | email:<address> -->
