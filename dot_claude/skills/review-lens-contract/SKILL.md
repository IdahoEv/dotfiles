---
name: review-lens-contract
description: Shared contract for periodic project-review lens agents — snapshot scope, finding-line format, word cap, read-only rule, and lens discovery. Preloaded by every lens via skills:; the diff-scoped counterpart is reviewer-contract.
---

# Review Lens Contract

A lens reviews a read-only snapshot of the default branch, not a diff. `reviewer-contract` does not apply.

## Inputs

The caller supplies:

- Snapshot path (read-only checkout of the default branch).
- Path to `project-review.md`. Scope, probes, doc roles and conventions come from it; a lens holds no project text. A value still in `<...>` placeholder form counts as unset.
- Word cap for the report.
- Findings already ticketed or triaged in earlier runs, to tag as `KNOWN` or `ALREADY TICKETED`.

Missing snapshot or word cap: ask, don't guess. Missing `project-review.md` or an unset section: report-only for that section, say so.

## Output

Within the word cap, most severe first. One line per finding:

`SEVERITY | LENS | file:line | defect | evidence | minimal fix`

- Severity: P0, P1, P2, P3.
- `LENS` is the lens's own `name`.
- Evidence is a path and line in the snapshot, or a probe command with its output. No evidence, no finding.
- Then `Verified clean:` listing what was checked and found sound. A clean lens says so; no praise, no summary.

## Read-only

No edits, commits, pushes, or tracker writes. Tracker reads only through the provider seam, and only for a lens tagged `Lens: triage`. Return findings only.

## Authoring

Agent file with `name`, `use_when: periodic project review.` directly above `description:`, optional `model`, `tools`, and the brief as body. The body states method and output only, under 60 lines, and begins with a `Lens: collect` or `Lens: triage` line. `use_when:` is required metadata here, not a selection filter.

## Discovery

Same tiers and name-dedup as `/local-review-cycle` (`local-review-cycle-procedure` §2). An earlier tier wins when names collide, so a project lens overrides a global lens of the same `name`.

1. Repo `.claude/agents/` (and `dot_claude/agents/` in a chezmoi dotfiles repo).
2. Personal `docs/local/reviewers/*.md` and overlay `claude/agents/*.md` (`project-config.sh list agents`).
3. Global `~/.claude/agents/`.

Then:

- Keep only files that declare `Lens: collect` or `Lens: triage`. Ordinary agents never launch as lenses.
- Run every remaining lens unless its `name` is in the `Skip:` line of `project-review.md` § Lenses (`project-config.sh find project-review.md`).
- No `use_when:` matching: there is no diff to match against.
- Tier 2 files are not registered agent types. Launch one as a `general-purpose` agent whose prompt is the file body, honoring its `model` frontmatter, prefixed with the inputs above and an instruction to follow this contract. `tools` frontmatter is not enforced there; the read-only rule is the guard.
