---
description: Governor — scan the project's tickets and pick a set that are ready to start and safe to run in parallel
argument-hint: [optional: max count, theme, or time available]
---

# Pick

Scan this project's tickets and choose a **set** that can start now and run side by
side in separate worktrees. Read-only: no tickets created or edited, no sessions
started. Intended for a Governor session; follow `/governor`'s conduct (reply style, stay
in the primary worktree).

## Gather

Read `.claude/governor.md` for the tracker and planning docs; if it's missing, say so
and stop. Then, in parallel:

- Open tickets from the tracker named there, with dependencies, estimates, and status.
- Work already in flight: `git worktree list`, open PRs, and other sessions via
  `ListAgents`. Ticket refs found there are **taken**, not candidates.
- Local planning docs (`docs/`, `TODO.md`) for sequencing the tracker doesn't encode.

## Filter: ready

A ticket is ready only if all hold:

- Every prerequisite ticket is **merged**, not just in review or open as a PR. A
  prerequisite whose PR is open is "ready after #N", not ready.
- Acceptance criteria and an estimate exist. Missing either → not ready; list it under
  *Needs refinement*.
- Design is decided; no open question or unresolved spike upstream.
- Not already assigned to a worktree, PR, or session.
- Not sourced from a draft planning doc marked "for local review".

## Filter: parallel-safe

From the ready tickets, build a set where members don't collide. Judge from ticket
text and a quick look at the code areas named; don't read implementations in depth.

- **No shared files or modules** likely to be edited by two members.
- **At most one** touching each of: DB schema/migrations, lockfiles or dependency
  changes, shared config, public API contracts, generated code.
- Neither member depends on the other's output, directly or via a third ticket.
- If two collide, keep the one that unblocks more downstream work and demote the other.

Prefer the set that unblocks the most downstream work, then decided design, then fit to
`$ARGUMENTS` (count, theme, time). Default to at most 4 — review bandwidth is the limit.

## Report

Lead with the set; end on the table.

1. **Needs refinement / blocked** — one line each, naming the missing piece or blocking
   ticket and its state. Omit if empty.
2. **Ready but held back** — ready tickets left out of the set, with the collision or
   reason. Omit if empty.
3. **Pick** — table, last:

| Ticket | Title | Est. | Touches | Unblocks | Why in the set |
|--------|-------|------|---------|----------|----------------|

State anything you couldn't determine (e.g. unreadable tracker, unclear code area)
rather than guessing. Don't offer to start the tickets; `/start <ref>` is the next step.

$ARGUMENTS
