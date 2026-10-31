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

- Every prerequisite ticket is **merged**, or is **earlier in the same chain** (see below).
  A prerequisite whose PR is open, or that is in no chain of the pick, makes the ticket
  "ready after #N", not ready.
- Acceptance criteria and an estimate exist. Missing either → not ready; list it under
  *Needs refinement*.
- Design is decided; no open question or unresolved spike upstream.
- Not already assigned to a worktree, PR, or session.
- Not sourced from a draft planning doc marked "for local review".

## Build chains

Group the ready tickets into **chains**: ordered runs worked serially in one worktree,
one session, one PR. Chains run side by side with each other. Judge from ticket text and
a quick look at the code areas named; don't read implementations in depth.

- **At most 3 links** per chain. A single ticket is a chain of one.
- **Within a chain**, tickets may overlap in files and may depend on each other; order
  them so each prerequisite comes first. Chain tickets that share files or are
  dependency-ordered rather than leaving them to collide as separate sessions.
- **Between chains**, no shared files or modules likely to be edited by both.
- **At most one chain** touches each of: DB schema/migrations, lockfiles or dependency
  changes, shared config, public API contracts, generated code.
- No dependency between two chains, directly or via a third ticket.
- Keep chains small enough for one reviewable PR; don't chain unrelated work just to fill
  the limit. If two chains collide, keep the one that unblocks more downstream work and
  demote the other.

Prefer the set that unblocks the most downstream work, then decided design, then fit to
`$ARGUMENTS` (count, theme, time). Default to at most 4 chains — review bandwidth is the
limit.

## Report

Lead with the set; end on the table and the `/start` line.

1. **Needs refinement / blocked** — one line each, naming the missing piece or blocking
   ticket and its state. Omit if empty.
2. **Ready but held back** — ready tickets left out of the set, with the collision or
   reason. Omit if empty.
3. **Pick** — table, one row per ticket, rows of a chain adjacent and in chain order:

| Chain | Ticket | Title | Est. | Touches | Unblocks | Why in the set |
|-------|--------|-------|------|---------|----------|----------------|

   Chain is a letter (`A`, `B`, …), the same for every link of a chain.
4. **Start line** — last, in a code block so it can be pasted: one space-separated group
   per chain, ids comma-separated in chain order, e.g. `/start 12,13 14 15,16,17`.
   Chains need the GitHub provider; on a Shortcut-provider repo every chain is a single
   ticket, so the line is space-separated ids only.

State anything you couldn't determine (e.g. unreadable tracker, unclear code area)
rather than guessing. Don't offer to start the tickets; the start line is the next step.

$ARGUMENTS
