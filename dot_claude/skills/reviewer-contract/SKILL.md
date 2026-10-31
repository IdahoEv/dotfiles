---
name: reviewer-contract
description: Shared contract for review agents — diff scope, finding-line format, read-only rule, triage context. Preloaded by every reviewer agent via skills:.
---

# Reviewer Contract

## Scope

The caller supplies the base ref, exact diff range, and ticket/acceptance criteria. Review only that diff and the nearby code needed to verify behavior. Do not report issues outside the diff.

If the caller supplies no diff range or ticket context, ask for the missing scope rather than guessing.

## Output

At most the findings cap the caller or your agent file sets, most severe first. One line per finding:

`SEVERITY | file:line | defect | concrete failing input/caller | minimal fix | verification`

Use Critical, High, Medium, or Low. Include only findings with evidence and a credible failure path, meaningful test gap, or material design cost. Say `no findings` when appropriate — a clean review is a real result. No praise or general summary.

Specialist focus, evidence bars, and any verdict header your agent defines (e.g. a DESIGN gate) come from your agent file; this contract does not override them. If your agent file or another preloaded skill specifies a different output format or review mode — `prompt-reviewer` follows the `prompt-review` rubric's format and may run in corpus mode, outside any single diff — follow that instead of the line above.

## Read-only

Do not edit files, commit, or push. Return findings only.

## Triage context

The caller lists findings already triaged in earlier rounds. Never re-raise a previously dismissed finding without new evidence. Do not restate findings the caller already holds; report only what is new in your assigned scope.

## Authoring convention

Every reviewer agent — global or project-local — ends its `description` with a `Use when: <conditions>.` clause naming the diff shapes and risk signals that justify invoking it. `/local-review-cycle` selects reviewers by matching these clauses against the changed files, so a reviewer without one is invisible to selection. When creating a new reviewer, write the clause in the diff's own terms: the file kinds, risk signals, or structural changes that fire it.

A reviewer may also live in `docs/local/reviewers/*.md` — same agent file format (`name`; `description` ending with a `Use when:` clause; optional `model`, `tools`; body = the reviewer brief) — for repos where committing a reviewer to `.claude/agents/` isn't appropriate. These files are not registered agents; the `local-review-cycle-procedure` skill §2 describes how a selected one is launched. `docs/local/` is globally gitignored and symlinked into `wm` worktrees, so reviewers there stay personal and uncommitted; to persist them across machines, point the repo's `docs/local/` at a checkout of a personal repo. The per-project overlay (`~/.config/project-overlays/<owner>/<repo>/claude/agents/`, keyed by the origin remote) is the same idea for agents a fresh clone should also find — new personal agents default there; existing `docs/local/reviewers/` keep working. Files in either place are launched the same way, per that §2.
