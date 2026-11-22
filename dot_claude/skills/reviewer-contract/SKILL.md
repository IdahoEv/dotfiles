---
name: reviewer-contract
description: Shared contract for review agents — diff scope, retrieval of callers/readers/neighbors/seams within a fixed budget, grounded finding format, read-only rule, triage context. Preloaded by every reviewer agent via skills:.
---

# Reviewer Contract

## Scope

The caller supplies the base ref, exact diff range, and ticket/acceptance criteria. Report findings only on changed lines. Read outside the diff freely for evidence — callers, readers, tests, docs and generated files are where a change's defects usually show. Do not report issues outside the diff, except a stale seam counterpart (see Retrieval): report it at the changed line that caused it and name the counterpart.

If the caller supplies no diff range or ticket context, ask for the missing scope rather than guessing.

## Retrieval

The diff shows what changed; retrieval shows whether it connects. Before writing findings, for every symbol, flag, config key, command, schema field, or registry entry the diff adds or changes:

- **Callers and readers.** Grep the name in production code. A new field with no reader, or one only tests read, is a finding. Same for a flag nothing passes, a command no doc or script invokes, or a schema field nothing writes.
- **Neighbors.** Read the call site, the callee it invokes, the sibling command or agent that already does this job, and the test that covers it. Confirm the change matches what they expect.
- **Seams.** Check every place old and new code must agree: registries, schemas, manifests, generated files, help text, docs and contracts, adapter tables. When the repo documents a test or generator that validates that agreement (project `CLAUDE.md`, manifest or generator scripts), run it and cite its output, or list the seam as unverified — do not infer it from the diff. One side updated and the other not is a finding.
- **Docs as claims.** A changed doc, spec or contract statement about the code is a claim: read the code path it names and verify it.

For a diff with no symbols (docs, prompts, config), treat each factual claim or referenced path as the symbol.

Build a retrieval table in your reasoning before writing findings: one row per changed symbol, with its production caller/reader, the neighbor you read, and the seam you checked. A blank cell is either a finding or a name in the unverified list. The table stays internal; the output is still the finding lines.

**Budget.** At most 20 retrieval calls per reviewer launch — Read, Glob, Grep, or a read-only Bash command — and no more than 3 on one symbol. Stop when every changed symbol has a caller/reader answer and its seams checked, or when the budget is spent. If the budget runs out first, name the symbols left unverified; an unverified symbol is not a finding.

**Grounding.** Every finding must cite what retrieval showed: the `file:line` call site, the grep result, the test that does not cover the path, or the seam left stale. Put it in the finding's concrete failing input/caller field. Drop a finding you cannot ground — "no caller found" is itself the evidence, not a reason to soften the claim.

## Output

At most the findings cap the caller or your agent file sets, most severe first. One line per finding:

`SEVERITY | file:line | defect | concrete failing input/caller | minimal fix | verification`

Use Critical, High, Medium, or Low. Include only findings with evidence and a credible failure path, meaningful test gap, or material design cost. Say `no findings` when appropriate — a clean review is a real result. No praise or general summary.

Specialist focus, evidence bars, and any verdict header your agent defines (e.g. a DESIGN gate) come from your agent file; this contract does not override them. If your agent file or another preloaded skill specifies a different output format or review mode — `pr-reviewer-prompt` follows the `prompt-review` rubric's format and may run in corpus mode, outside any single diff — follow that instead of the line above.

*Terminology:* PR/workstream diff reviewers use `pr-reviewer-*` under this contract (`dot_claude/agents/pr-reviewers/`); periodic whole-project snapshot reviewers use `project-lens-*` under `review-lens-contract` (`dot_claude/agents/project-lenses/`).

## Read-only

Do not edit files, commit, or push. Return findings only.

## Triage context

The caller lists findings already triaged in earlier rounds. Never re-raise a previously dismissed finding without new evidence. Do not restate findings the caller already holds; report only what is new in your assigned scope.

## Authoring convention

Every reviewer agent — global or project-local — carries a `use_when: <conditions>.` frontmatter key directly above `description:`, naming the diff shapes and risk signals that justify invoking it; `description` stays a one-line summary with no trigger clause. `/local-review-cycle` selects reviewers by matching `use_when:` against the changed files, so a reviewer with neither the key nor a legacy single-line `Use when:` description clause is invisible to selection (a legacy clause still selects, and the cycle report asks for migration). When creating a new reviewer, write the conditions in the diff's own terms: the file kinds, risk signals, or structural changes that fire it.

A reviewer may also live in `docs/local/reviewers/*.md` — same agent file format (`name`; `use_when`; `description`; optional `model`, `tools`; body = the reviewer brief) — for repos where committing a reviewer to `.claude/agents/` isn't appropriate. These files are not registered agents; the `local-review-cycle-procedure` skill §2 describes how a selected one is launched. `docs/local/` is globally gitignored and symlinked into `wm` worktrees, so reviewers there stay personal and uncommitted; to persist them across machines, point the repo's `docs/local/` at a checkout of a personal repo. The per-project overlay (`~/.config/project-overlays/<owner>/<repo>/claude/agents/`, keyed by the origin remote) is the same idea for agents a fresh clone should also find — new personal agents default there; existing `docs/local/reviewers/` keep working. Files in either place are launched the same way, per that §2.
