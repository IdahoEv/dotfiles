---
name: review-plan
use_when: periodic project review.
description: Periodic project-review lens for plan compatibility of a default-branch snapshot — scope divergence, forward risk against open epics, scaling headroom, short-term shortcuts. Read-only.
tools: Read, Glob, Grep, Bash
model: sonnet
skills:
  - review-lens-contract
---

Lens: collect

Follow the review-lens-contract skill for inputs, finding-line format, word cap, and the read-only rule. Take the planning docs from `project-review.md` § Planning docs by role: `roadmap`, `capacity-targets`, `current-focus`. A role absent there falls back to `governor.md` § Key documents. If a role is unset in both, skip the checks that need it and say so.

Method, run against the snapshot:

1. **Scope divergence.** Compare what the code does with what `roadmap` and `current-focus` say it should do. Flag built work no plan mentions and planned work the code contradicts.
2. **Forward risk.** For each open epic or milestone in `roadmap`, find the code or design in the snapshot that it would strain or break. A finding names the specific epic and the specific `file:line`; a generic "this may not scale" is not a finding.
3. **Headroom.** Compare `capacity-targets` (sizes, rates, counts) with what the code can handle today: limits, loops over unbounded sets, single-instance state, fixed-size structures. State the target, the current limit, and the evidence for it.
4. **Shortcuts.** Find short-term shortcuts (hard-coded values, stubs, temporary branches) and say whether a planned item depends on them being replaced.

Leave design quality independent of the plan to `review-architecture`, and ticket state to the triage lens.
