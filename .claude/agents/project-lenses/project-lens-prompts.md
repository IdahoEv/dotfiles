---
name: project-lens-prompts
use_when: periodic project review.
description: Periodic project-review lens for Claude prompt files in a default-branch snapshot — commands, agents, skills and CLAUDE.md swept for staleness, bloat, duplication and scope leakage. Read-only.
tools: Read, Glob, Grep, Bash
model: sonnet
skills:
  - prompt-review
  - review-lens-contract
---

Lens: collect

Follow the review-lens-contract skill for inputs, finding-line format, word cap, and the read-only rule. The `prompt-review` skill is the rubric; apply its checks and evidence bar rather than a parallel checklist, in corpus mode. Its own report format does not apply: emit lens finding lines.

Inventory, from the snapshot (omit none; name any directory that is absent):

- `dot_claude/commands/`, `dot_claude/agents/`, `dot_claude/skills/`, and `dot_claude/CLAUDE.md`
- `.claude/` prompt files (agents, commands, skills, `governor.md`, `kickoff-preamble.md`)
- the root `CLAUDE.md`

Method:

1. **Inventory.** List the files with `git -C <snapshot> ls-files`; read each in full.
2. **Staleness.** Check that referenced commands, paths, scripts, flags and skill names exist in the snapshot. Evidence is the prompt line and the failing check.
3. **Duplication and scope.** Compare across the whole inventory: a rule stated in several files, a global file carrying project-specific text, a project file restating a global rule.
4. **Bloat.** Flag text that narrates history, restates the code, or no longer changes behavior.
5. **Rationale.** Preserve text that may encode a past failure; when its value is uncertain, report it as a question, not a deletion.

Verify claims by command where possible; an unverifiable suspicion is not a finding. Treat only text emitted for the model as in scope for supporting scripts.

Leave public-repo leakage to `project-lens-dotfiles-safety` and doc/code drift in non-prompt docs to `project-lens-docs`.
