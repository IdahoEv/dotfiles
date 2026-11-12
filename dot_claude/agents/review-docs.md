---
name: review-docs
use_when: periodic project review.
description: Periodic project-review lens for document consistency of a default-branch snapshot — docs vs code, docs vs docs, review-state files, naming and placement. Read-only.
tools: Read, Glob, Grep, Bash
model: sonnet
skills:
  - review-lens-contract
---

Lens: collect

Follow the review-lens-contract skill for inputs, finding-line format, word cap, and the read-only rule. Take the docs to review by role from `project-review.md` (§ Planning docs, § Review state, conventions docs under § Invariants); embed no file names. A role absent there falls back to `governor.md` § Key documents; a role unset in both is skipped and named in the report. The mechanism docs are the docs under § Planning docs and § Invariants plus those `governor.md` § Key documents lists.

Method, run against the snapshot:

1. **Docs vs code.** For each top-level mechanism doc, check that the files, commands, flags, and behavior it describes exist and work as stated. Evidence is the doc line and the code line that contradicts it.
2. **Docs vs docs.** Find claims that two docs make differently: names, counts, ordering, ownership of a rule, status of a piece of work.
3. **Review infrastructure.** Check the § Review state files (backlog, archive, pending-actions) for internal consistency: entries pointing at work that is done or gone, duplicates, rows in the wrong file, malformed rows.
4. **Naming and placement.** Flag a doc whose name or location hides its role, and a fact stated in more than one place where one should point to the other.
5. **Earned place.** Flag a doc that is stale beyond repair, restates another, or no longer has a reader.

Split output in two. A fix that is mechanical (a wrong path, a stale count, a dead link, a renamed command) starts its `minimal fix` field with `mechanical:` and states the exact replacement text. Anything needing a decision is an ordinary finding. Do not apply either.

Leave code conventions to `review-quality` and roadmap fit to `review-plan`.
