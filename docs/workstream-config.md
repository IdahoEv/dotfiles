# Workstream configuration

**Decision:** one `config.yaml` per layer, plus prose files referenced by name. It replaces `start-ticket.conf`, the `GT_*` env knobs, `.worktree-sync`, `lib/pr-risk.json` and the settings parts of `.claude/project-review.md`. The committed layer moves out of `.claude/` into `.workstream/`, so the tool stays separable from Claude's own files if it is opened to other developers (roadmap phase 4).

## Format

- YAML: comments and multiline strings. Top-level `version:` plus a published JSON Schema.
- Prose (prompts, templates) stays in `.md` files; `config.yaml` names them (`ticket_template: ticket`), never inlines them.
- Resolution lives in Python (`repo_facts.py` `conf-get` successor), dotted keys (`review.cadence.window`). Bash callers shell out to it.

## Layers

Lowest to highest precedence:

| Layer | Root |
| --- | --- |
| defaults | `tools/defaults/` (replaces `tools/project-config-templates/`) |
| user | `~/.config/workstream/` |
| machine | `~/.config/workstream/machine/` (open item) |
| project overlay | `<overlays-root>/<owner>/<repo>/`, keyed by the origin remote, outside the checkout |
| project committed | `<repo>/.workstream/` |
| workstream | `<worktree>/.workstream.json`, for that workstream only ([concept](workstream-concept.md)) |

Merge rules:

| Kind | Rule |
| --- | --- |
| scalar | higher layer overrides |
| map | deep merge |
| list | higher layer replaces; a key may opt into append |
| prose file | whole-file replace, first hit by layer order (as `find_doc` does today) |

Keys marked sensitive (hostnames, private repo names, credential references) are accepted only from the user, machine and overlay layers, never from the committed layer, because committed config can sit in a public repo.

## Layout (identical in every layer below workstream)

```
config.yaml
prompts/
  governor.md
  kickoff-preamble.md
  project-review.md
  templates/ ticket.md  pr.md  commit.md
agents/  commands/  skills/
```

`agents/ commands/ skills/` are backend-neutral. Per-backend adapters render them into `~/.claude`, `~/.gemini` and `~/.codex`.

## Separation from runtime state

`.workstream.json` (per-worktree record: phase, PR, sessions) holds runtime state. As the workstream layer, it also holds the settings that differ for that workstream, plus its copy of the step plan. Nothing under a config dir is written at runtime.

## Environment

`GT_*`, `GIT_TOOLS_PROJECTS_DIR` and `PROJECT_OVERLAYS_DIR` become a single `WS_*` prefix. Every key is also settable by env var for one-off overrides.

## Tooling

- `config explain <key>` prints the winning value and its layer (extends `conf_get_source`).
- Migration: the old `key=value` files stay readable as a lowest-precedence fallback layer until each consumer has moved. Migrating the existing projects is a one-time manual step.

## Field inventory

| Area | Fields | Source today |
| --- | --- | --- |
| Launch | `launcher`, backend, per-backend model | `start-ticket.conf`, roadmap |
| Labels and titles | noise words, words, slug words, max chars, `form`/`template` per surface | `GT_LABEL_*`, `workstream.py` layers |
| Git methods | `sync_method`, `merge_method`, `prune_force_delete`, default branch, push policy by environment | `start-ticket.conf`, CLAUDE.md |
| Ticket identity | provider, id scheme (`Is<N>`, `sc-<N>`), branch convention, Shortcut in-progress state | `start-ticket.conf`, `repo_facts.py` |
| PR | `openpr_provider`, PR title/body templates | `start-ticket.conf`, `open-pr.sh`, `pr_body.py` |
| Commit and ticket text | message templates, ticket-writing rules | prose, scattered |
| Project color | `color`, richer rules | `start-ticket.conf`, `tools/project-colors` |
| Worktree sync | `link`/`copy` manifest | `.worktree-sync` |
| Tests | FAST/FULL commands, test-file regex | CLAUDE.md prose, `WF_TEST_RE` |
| Review chain | reviewer set, per-reviewer model, `review_max_rounds`, lens skips, unattended mode | agent frontmatter, `reviewer-model.sh`, `review-unattended.sh` |
| PR risk | high/low path globs | `lib/pr-risk.json` |
| Project review | planning-doc roles, review-state paths, cadence, activity globs, scope map, invariants, actions, delivery, schedule | `.claude/project-review.md` |
| Governor | key documents, repositories, adjacent systems, people, primary worktree | `governor.md` |
| Approval policy | commit pause vs ticket auto-commit, checkpoints | global CLAUDE.md |
| Visibility | public/private flag (selects the safety reviewers) | implicit |
| Telemetry | on/off, log path | `WF_TELEMETRY*` |
| Phases | phase vocabulary, tags | `agent-phase.sh` |
| Credentials | references only (op://, env var names), never values | scattered |

Model pricing (`lib/model-pricing.json`) is reference data, not config, and stays separate.

## Open items

- Machine-layer location and per-host subdirectories.
- Backend adapters that render the neutral `agents/ commands/ skills/`.
- Whether any list keys need append semantics at launch.
