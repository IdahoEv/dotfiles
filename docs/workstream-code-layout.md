# Workflow code modules and file layout

**Decision:** Fovea is one Python 3.13 package: a `fovea` CLI, a `fovea-hook` entry for agent hooks, and eight internal layers — `contracts`, `record`, `lifecycle`, `settings`, `adapters`, `telemetry`, `ui`, `install` — composed only by `commands` and its two entry points. Imports point one way; `record` imports nothing but the standard library. Fovea owns the whole workflow and ships defaults for anything stylistic, which user layers override. Machine provisioning and general-purpose agents and writing skills stay in dotfiles, which remains the working implementation until Fovea reaches parity.

This is the target design for `IdahoEv/Fovea`. It finalizes the code boundaries implied by [record schemas](workstream-schema.md), [record lifecycles](workstream-lifecycle.md), [settings](workstream-config.md) and [telemetry](workflow-telemetry.md). Nothing here is built.

## Runtime and distribution

| Topic | Decision |
| --- | --- |
| Language | Python 3.13, `from __future__ import annotations`, full type hints, `match` where it clarifies |
| Dependencies | Standard library plus PyYAML for the settings `config.yaml`; nothing else at runtime |
| Packaging | Provisional, pending the distribution decision in [Open](#open): `pyproject.toml`, `src/` layout, console scripts `fovea` and `fovea-hook`, installed with `uv tool install` (supplies the 3.13 interpreter on hosts that lack it) |
| Dev tooling | pytest, ruff, mypy strict, import-linter |
| Hot paths | Targets, not today's numbers: `fovea statusline` ≤ 45 ms p50 and `fovea-hook` ≤ 40 ms p50, against the shell medians of 45.5 ms and 41.2 ms measured in the [spike](2026-10-26-shell-to-python-spike.md#hot-paths). Phase 6 gates each entry on that spike's harness on both machines; an entry that misses on either is replaced by that entry's compiled shim ([below](#hot-path-shims)), not by a daemon. |
| Outside Fovea | `dot_claude/hooks/executable_no-cd-write.py` stays a standalone hook: it guards Bash calls, owns no workflow state, and already meets its 13 ms budget. |

No daemon or background record writer runs. Records are files, and a hook or the next command notices changes. The only detached process is the post-PR review watch.

### Hot-path shims

A missed budget replaces one entry; it never adds a daemon.

- **Scope.** One shim per entry, covering only that surface's verbs (`fovea statusline`, `fovea-hook <event>`); every other verb stays Python. The shim reads the same record files and settings layers and writes no state.
- **Artifact.** Source lives in `shims/<entry>/`, outside `src/fovea/`, so no layer imports it and the boundary test is unaffected. It builds into the same release archive and version as the Python package, with its own checksum; the [Open](#open) distribution decision sets how.
- **Interface.** Same command name, argv, stdin JSON and one-line stdout as the Python entry, held to the same parity fixtures, so no caller can tell which implementation runs.
- **Selection.** Fixed when the archive is built, per platform: that entry's console script in `pyproject.toml` names the shim, and a source checkout always runs Python. There is no runtime branch or call-time fallback.
- **Stop.** If no shim brings an entry under budget, Phase 6 does not exit: the phase stops for a decision rather than shipping a slower entry or a daemon.

## Repository layout

```
fovea/
├── pyproject.toml               scripts: fovea, fovea-hook; pytest/ruff/mypy/import-linter config
├── src/fovea/
│   ├── cli.py                   argv → command; exit codes
│   ├── hook.py                  agent hook event → one lifecycle use case
│   ├── contracts.py             frozen fact and use-case dataclasses shared across layers
│   ├── commands/                one file per CLI verb
│   │   ├── start.py  discuss.py  iterate.py
│   │   ├── open_pr.py  sync.py  merge.py  land.py  finalize.py  drop.py
│   │   ├── takeover.py  session.py  workstream.py  phase.py
│   │   ├── review.py  prune.py  config.py  telemetry.py  context.py
│   │   ├── statusline.py  snapshot.py  dashboard.py  worktree.py
│   │   └── project_review.py  install.py
│   ├── record/                  schema, atomic storage, locks, migration, queries
│   ├── lifecycle/               every state transition and policy decision
│   ├── settings/                layered config.yaml and prose-asset resolution
│   ├── telemetry/               event schema, emitter, reports, analyses
│   ├── ui/                      surface-neutral view models and renderers
│   ├── install/                 per-backend rendering of assets, config and hooks
│   └── adapters/
│       ├── agent/               claude, codex, opencode, agy
│       ├── tracker/             github, shortcut, github-mcp
│       ├── forge/               github PRs, reviews, branches
│       ├── worktree/            git worktrees, sibling repos, sync links
│       ├── launcher/            claude, codex, opencode, agy, tmux
│       ├── host/                memory guard, machine facts
│       ├── ui/                  claude-statusline, tmux, herdr, opencode, aoe
│       └── telemetry/           jsonl sink; later remote sinks
├── assets/
│   ├── defaults/                config.yaml defaults
│   ├── commands/                slash-command bodies
│   ├── agents/                  reviewers, lenses, managers
│   ├── skills/                  procedures and contracts
│   ├── prompts/                 kickoff, governor, project-review, backends
│   ├── templates/               statusline, branch, worktree, session, PR, commit
│   └── data/                    model pricing, reference tables
├── shims/                       per-entry hot-path replacements, built per platform
├── docs/                        this file and the design docs it links
└── tests/                       pytest, boundary test, parity fixtures
```

## Modules: responsibility, entry points, dependencies

Allowed imports are exhaustive. Every module may use the Python standard library. `contracts` and `record/schema` are the only modules that define shared types.

| Module | Files | Responsibility | Public entry points | May import |
| --- | --- | --- | --- | --- |
| **Contracts** | `contracts.py` | Frozen dataclasses for facts crossing a boundary and for use-case arguments | `TicketFact`, `RepoFacts`, `PrFacts`, `AgentSessionFacts`, `LaunchSpec`, `WorktreeFacts`, `MemorySample`, `ReviewFacts`, `FinishVerdict` | stdlib only |
| **CLI** | `cli.py` | Parse argv, dispatch, map errors to exit codes | `main(argv)` | commands |
| **Hooks** | `hook.py` | Read an agent payload, call one lifecycle use case | `main(event, stdin)` | contracts, lifecycle, settings, adapters/agent, adapters/telemetry, telemetry |
| **Session record** | `record/session.py`, `record/schema/session.py` | Session v0 type, validation, load by `id` | `read_session`, `read_sessions(workstream_id=…, cwd=…)` | record/* |
| **Workstream record** | `record/workstream.py`, `record/schema/workstream.py` | Workstream v0 type, validation, load, legacy conversion | `read_workstream(dir)`, `read_workstream_by_id(id)` | record/* |
| **Record writes** | `record/write.py` | The only write surface: validates, locks, bumps `updated_at`, writes atomically | `write_session`, `write_workstream`, `write_index`, `remove_index`, `destroy` | record/* |
| **Record store** | `record/store.py`, `record/lock.py`, `record/paths.py` | Atomic write, per-worktree lock, XDG and worktree paths, `.git/info/exclude` | `with_record_lock`, `read_json`, `write_json_atomic` | record/* |
| **Record index** | `record/index.py` | One open-workstream entry per workstream on this host | `read_index(id)`, `list_index()` | record/* |
| **Pending queue** | `record/pending.py` | Pending-actions file: lock, atomic upsert, dedup key | `upsert_action`, `list_actions` | record/* |
| **Schema gate** | `record/schema/version.py` | Reject a higher `schema_version`; shared field validators | `assert_readable`, `validate` | record/* |
| **Migration** | `record/migrate.py` | Convert legacy `.workstream.json` and `<git-dir>/chain` on write | `to_v0`, `is_legacy` | record/* |
| **Record queries** | `record/query.py` | Read-only joins used by displays | `session_views`, `workstream_view` | record/* |
| **Settings layers** | `settings/layers.py`, `settings/legacy.py` | Layer roots and precedence, shipped defaults in `assets/defaults`; legacy `start-ticket.conf`, `GT_*`, `.worktree-sync` fallback | `layer_roots`, `load_legacy` | settings/*, assets/defaults (data) |
| **Settings resolve** | `settings/resolve.py`, `settings/schema.py` | Dotted keys, `WS_*` env, explanation, YAML schema, prose-asset lookup by name | `resolve(key, ctx)`, `explain(key, ctx)`, `find_asset(kind, name, ctx)` | settings/* |
| **Lifecycle: session** | `lifecycle/session.py` | Start, resume, clear, fork, end, purpose, link, activity | `start`, `end`, `set_purpose`, `set_activity` | contracts, record, settings, telemetry |
| **Lifecycle: workstream** | `lifecycle/workstream.py` | Create, update, stage, rename, finish, drop | `create`, `set_stage`, `finish`, `drop` | contracts, record, settings, telemetry |
| **Lifecycle: lead** | `lifecycle/lead.py` | Lead check, takeover, role moves | `check`, `takeover`, `assign_role` | contracts, record, telemetry |
| **Lifecycle: reviews** | `lifecycle/reviews.py` | Start, accept, reset, rounds, ready-to-merge over caller-supplied facts and settings | `start`, `accept`, `reset`, `ready_to_merge` | contracts, record, settings, telemetry |
| **Lifecycle: PRs** | `lifecycle/pr.py` | Open, merged, closed, head updates, expected-versus-surprising policy | `opened`, `merged`, `head`, `assert_expected` | contracts, record, telemetry |
| **Lifecycle: attention** | `lifecycle/attention.py` | Raise and clear entries by subject, including on stage change | `raise_entry`, `clear` | contracts, record, telemetry |
| **Lifecycle: gates** | `lifecycle/sync_gate.py`, `lifecycle/finish_verdict.py` | Pure rung logic over caller-supplied facts | `sync_verdict`, `finish_verdict`, `agent_phase` | contracts |
| **Lifecycle: names** | `lifecycle/names.py` | Slug, title and ticket-derived key | `draft_slug`, `derive_key` | contracts, settings |
| **Agent adapters** | `adapters/agent/{base,claude,codex,opencode,agy}.py` | Hook payloads, running check, transcript lookup | `AgentAdapter` | contracts, settings, adapters/exec |
| **Tracker adapters** | `adapters/tracker/{base,github,shortcut,github_mcp}.py` | List (reporting truncation), read, assign and create tickets | `TrackerAdapter` | contracts, settings, adapters/exec |
| **Forge adapter** | `adapters/forge/{base,github}.py` | PR open/merge/read, reviews, branch delete, review request | `ForgeAdapter` | contracts, settings, adapters/exec |
| **Worktree adapter** | `adapters/worktree/{base,git,siblings}.py` | Create/remove/move worktrees, branch facts, link/copy sync, sibling repos | `WorktreeAdapter` | contracts, settings, adapters/exec |
| **Launcher adapters** | `adapters/launcher/{base,claude,codex,opencode,agy,tmux}.py` | Start a session in a worktree with a declared link, role and purpose | `LauncherAdapter` | contracts, settings, adapters/exec |
| **Host adapter** | `adapters/host/{base,memory}.py` | Memory pressure, per-session attribution, launch guard | `HostAdapter` | contracts, settings, adapters/exec |
| **UI adapters** | `adapters/ui/{base,claude_statusline,tmux,herdr,opencode,aoe}.py` | Read surface input and write a rendered view to that surface | `UiAdapter` | contracts, settings, ui, adapters/exec |
| **Telemetry sink** | `adapters/telemetry/{base,jsonl}.py` | Append events locally; later remote sinks implement the same contract | `JsonlSink` | contracts, telemetry |
| **Exec** | `adapters/exec.py` | Subprocess, environment, `gh` shim awareness, exit codes | `run`, `run_json` | contracts |
| **Telemetry emit** | `telemetry/events.py`, `telemetry/emit.py` | Event union, current sink, run id, truncation, disable switch | `configure(sink)`, `emit(event)` | telemetry/* |
| **Telemetry reports** | `telemetry/report.py`, `telemetry/analyze/*.py` | Reports, usage, memory, review gaps, backfill | `report`, `usage`, `review_gaps`, `backfill` | telemetry/* |
| **UI view** | `ui/view.py`, `ui/tags.py` | Surface-neutral view model and PLAN/WIP/review/MERGED/PR/`!` tags | `build_view`, `tags` | contracts, settings, record/query |
| **UI renderers** | `ui/statusline.py`, `ui/snapshot.py`, `ui/documents.py`, `ui/names.py` | Statusline text, list/show text and JSON, kickoff, PR body and titles, commit text, branch/worktree/session/PR names | `render_statusline`, `render_snapshot`, `pr_body`, `kickoff`, `surface_name` | contracts, settings, record/query |
| **UI dashboard** | `ui/dashboard/*` | tmux dashboard over record reads and caller-supplied host samples | `run_dashboard` | contracts, settings, ui/*, record/query |
| **Commands** | `commands/*.py` | One handler per CLI verb; gathers facts, calls lifecycle | `main` per command | all eight layers — `record` includes reads and `record/pending.py`, never `record/write.py` |
| **Install** | `install/{backend,claude,codex,opencode,agy,cloud,manifest}.py` | Render resolved assets, config and hooks for one backend; release archive and checksums | `install(backend)`, `manifest` | contracts, settings, assets |

Rules the table encodes:

- `record` owns persistence, schema validation, locks, migration and read queries. It imports neither `settings` nor `contracts`: arguments are primitives and its own types. Record types stay inside `record`, `lifecycle` and the `record/query` consumers in `ui`; `lifecycle` projects them into `contracts` dataclasses before calling an adapter or emitting telemetry, so a schema change touches one projection per use case and never an adapter.
- `lifecycle` owns every allowed transition and the [expected-versus-surprising](workstream-concept.md#records-and-storage) policy. It never imports `adapters` or `commands`; facts arrive as `contracts` dataclasses. Setup and delivery commands call the same use cases.
- `adapters` return and accept `contracts` dataclasses, never record types. They may read settings. They never emit telemetry; the caller does. `adapters/ui` may import `ui` and `adapters/telemetry` may import `telemetry`, each to implement its contract. `adapters/exec` is the only subprocess and `gh` seam: the other adapters call it instead of `subprocess`, it imports `contracts` alone, and no adapter imports another adapter's module.
- `settings` resolves a key from the layer roots, the shipped defaults and a context; it never reads records. A command reads the workstream record and passes its `settings` object in the context.
- `telemetry` is a leaf with a configured sink; the sink itself is an adapter, so `commands`, `hook` and the dashboard command construct one and configure it once at startup before lifecycle emits.
- `ui` builds views from record reads and passed facts, and opens neither git nor the network itself: record reads go through `record/query`, and asset text arrives from `settings`. `adapters/ui` handles the surface protocol.
- `install` reads `assets/`, settings and the release artifact; it never reads records or lifecycle state.
- `commands` composes downward and is the only place where a CLI verb is named. The entry points wire only their own rows: `cli` dispatches to a command, and `hook` parses one agent payload into a fact, configures the telemetry sink and calls one lifecycle use case, with the agent and telemetry-sink adapters as its only adapter imports.
- Writes are narrower than reads: `record/write.py` is importable only from `lifecycle/`; `record/pending.py` also from `commands/` for the project-review queue.

Enforcement: import-linter declares one contract per row plus the write guard, and `tests/test_boundaries.py` fails when a `src/fovea/` directory has no contract. A deliberate violation is the skeleton's exit test.

## Core mechanism versus personal style

Fovea ships a working default and treats prose and presentation as configuration. Core code must not contain one person's prompt wording, project names or aesthetic choices.

| Core, not overridable | Shipped as a default, overridable or removable |
| --- | --- |
| Record schemas and lifecycle transitions | Kickoff, governor and project-review prose |
| Adapter contracts and event schema | Command bodies, agent and skill files |
| Command wiring, flags and exit codes | Reviewer and lens sets, review cadence and models |
| Purpose behaviours for `talk`, `governor`, `project-review`, `iterate`, `implement` | Purpose labels beyond those five |
| Format placeholders and layer precedence | Statusline, branch, worktree, session and PR formats |
| Telemetry field names | Labels, colors, tests, required checks, guard thresholds, sinks |

- Commands load prose by name (`prompt: kickoff`, `template: statusline`) from the first layer that supplies it, per [settings](workstream-config.md#layers). They never inline prose or a personal name.
- The resolved asset set, not the core tree, decides which slash commands, agents and skills are installed. A user can override one file, add a personal reviewer, or omit a default.
- The five core purposes have behaviour: talk and governor are never linked, project-review is unlinked and logged, iterate creates a workstream in place, implement is the default for work. Any other purpose is a label with no behaviour.

## The record/lifecycle seam

```
command or hook                    lifecycle                     record
──────────────────                 ─────────                     ──────
fovea start 280   ── TicketFact, WorktreeFacts ─▶  workstream.create  ──write──▶  workstream
                                                  index.add        ──write──▶  index
fovea open-pr     ── PrFacts ───────────────▶   pr.opened          ──write──▶  workstream
fovea sync        ── RepoFacts, PrFacts ────▶   pr.head            ──write──▶  workstream
fovea merge       ── PrFacts ───────────────▶   pr.merged          ──write──▶  workstream
fovea finalize    ── FinishVerdict ─────────▶   workstream.finish  ──log────▶  telemetry
                                                                  ──destroy──▶ session, workstream, index
```

- `/start` fetches a ticket, creates a worktree and launches an agent, then passes those facts to `lifecycle.workstream.create`; it never opens a record file. `/discuss` creates no workstream — it opens an unlinked talk session in the existing checkout, with no ticket, branch or worktree — and only a later promotion reaches `workstream.create`. `/iterate` will also reach it; it is not built yet.
- A delivery command (`open-pr`, `sync`, `merge`, `finalize`, `drop`) reads git and forge state through adapters, then calls one lifecycle use case with the result. The use case decides whether the change is expected; a surprise pauses the command and asks, per the concept.
- Hooks take the same path: `hook.py` parses an agent payload into a `contracts` fact and calls `lifecycle.session.start`, exactly as a command would.
- Nothing in `lifecycle` knows that `/open-pr` exists, and `/finalize` adds no record code of its own. Reads work the same way: readers reach records through `record/` — displays through `record/query.py` — `ui` is the only layer that formats them, and no reader opens a record file.

## What each current entry point becomes

**Keep** means ported with the same invocation surface. **Consolidate** means several files become one command or one adapter. **Retire** means deleted with no successor.

| Current | Target | Action |
| --- | --- | --- |
| `tools/lib/workstream.py` (1,217), `tools/workstream.sh` | `record/*`, `lifecycle/*`, `commands/workstream.py`, `ui/*` | Consolidate |
| `tools/start-ticket.sh` (740), `tools/start-ticket-providers/*` | `commands/start.py`, `commands/discuss.py`, `adapters/{tracker,worktree,launcher}`, `assets/prompts/kickoff*` | Consolidate |
| `tools/tracker.sh` | `adapters/tracker/*`, `commands/{start,project_review}.py`; keeps `list`/`create`, the `truncated` flag and exit 2 | Consolidate |
| `tools/open-pr.sh` (487), `tools/open-pr-providers/*` | `commands/open_pr.py`, `ui/documents.py`, `adapters/{forge,tracker}` | Consolidate |
| `tools/pr-body.sh`, `tools/lib/pr_body.py`, `tools/lib/pr-risk.json` | `ui/documents.py`, `assets/templates/pr.md`, settings `pr.risk` | Consolidate |
| `tools/lib/model-pricing.json` | `assets/data/model-pricing.json` | Keep, moved |
| `tools/finalize-check.sh`, `tools/lib/finalize_check.py`, `tools/finalize-run.sh`, `tools/lib/finalize_run.py` | `commands/finalize.py`, `lifecycle/finish_verdict.py`, `adapters/worktree`, `commands/prune.py` (shared verdict) | Consolidate |
| `tools/sync-gate.sh`, `tools/lib/sync_gate.py` | `lifecycle/sync_gate.py` + facts from `adapters/worktree` and `adapters/forge` | Consolidate |
| `tools/sync-run.sh`, `tools/lib/sync_run.py` | `commands/sync.py` | Consolidate |
| `tools/merge-run.sh`, `tools/lib/merge_run.py`, `dot_claude/commands/land.md` | `commands/merge.py`, `commands/land.py` | Consolidate |
| `tools/prune-worktrees.sh`, `tools/lib/prune_worktrees.py` | `commands/prune.py`, `adapters/worktree` | Consolidate |
| `tools/sibling-worktrees.sh`, `tools/lib/sibling_worktrees.py` | `adapters/worktree/siblings.py` | Consolidate |
| `tools/worktree-manager.sh` (1,172), `wm` alias | `adapters/worktree/git.py`, `commands/worktree.py`; `wm` remains an alias | Keep |
| `tools/agent-phase.sh`, `tools/session-label.sh`, `dot_claude/skills/github-review-procedure/executable_{github-review-state,github-review-poll}.sh` | `commands/phase.py`, `lifecycle/{reviews,workstream}`, `ui/{tags,names}.py`, `adapters/ui/claude_agent_view.py`, `adapters/forge` poll | Consolidate |
| `tools/review-unattended.sh`, `tools/request-review.sh`, `tools/open-pr-watch.sh` | settings `review.unattended`, `commands/review.py`, `adapters/forge` watch | Consolidate |
| `tools/wf-event.sh`, `tools/lib/telemetry.sh`, `tools/wf-*.sh`, `tools/lib/wf_*.py` | `telemetry/*`, `adapters/telemetry/jsonl.py`, `src/fovea/hook.py` | Consolidate |
| `tools/lib/repo_facts.py`, `tools/lib/repo-facts.sh`, `tools/project-config.sh` | `settings/*`, `adapters/worktree` (branch facts), `commands/config.py` | Consolidate |
| `tools/project-review-*.sh`, `tools/pending-actions.sh`, `tools/lib/pending_actions.py` | `commands/project_review.py`, `record/pending.py`; lenses stay assets | Consolidate |
| `tools/agy-tmux.sh`, `tools/lib/agy_tmux_dashboard.py` | `commands/dashboard.py`, `ui/dashboard/*`, `adapters/ui/tmux.py`, `adapters/launcher/tmux.py` | Keep |
| `tools/codex-workflow.sh`, `tools/lib/codex_{workflow,rpc}.py` | `adapters/{agent,launcher}/codex.py` for the daemon RPC and thread control, `commands/start.py` and `commands/discuss.py` for `start`, `launch` and `discuss`, `commands/session.py` for the thread verbs `status`, `resume`, `send` and `name`, `commands/context.py` for `instructions`; `codex-workflow.sh` keeps all eight verbs as a shim until `workflow/adapters/codex-local.md` switches in the same phase | Consolidate |
| `tools/workflow-session.sh` | `commands/session.py`, `commands/takeover.py` | Consolidate |
| `tools/mem-guard.sh`, `tools/lib/mem_guard.py` | `adapters/host/memory.py`; memory samples become telemetry events and a dashboard column | Keep |
| `tools/cloud-workflow-bootstrap.sh`, `tools/workflow-manifest.sh` | `install/{cloud,manifest}.py` for post-install cloud rendering and the manifest; a one-file `bootstrap.sh` ships in the release and stays bash (`curl`, `tar`, checksum tool only) because it runs before Python exists, fetching the pinned archive and running its installer | Retire both scripts; keep the pre-Python bootstrap |
| `tools/cloud-gh-shim.py` | stays a Python shim, moved under `install/` | Keep |
| `tools/migrate-use-when.sh` | none | Retire |
| `tools/reviewer-model.sh` | settings `review.models` | Consolidate |
| `tools/session-kickoff.md`, `tools/project-colors`, `tools/project-config-templates/*` | `assets/{prompts,templates}/*`, settings `project.color` | Keep, moved |
| `tools/bootstrap-*.sh`, `tools/lib/packages.tsv`, `tools/mcp-notion.sh`, chezmoi wiring | — | Stay in dotfiles |
| `dot_claude/executable_statusline.sh` | `ui/statusline.py`, `adapters/ui/claude_statusline.py`, `commands/statusline.py` | Keep |
| `dot_claude/hooks/executable_no-cd-write.py` | — | Stay a standalone hook |
| `dot_claude/commands/{start,discuss,open-pr,github-review-comments,local-review-cycle,project-review,project-review-apply,finalize,merge,land,sync,pick,groom,governor,prompt-audit,implement}.md`, `agents/{pr-reviewers,project-lenses,local-review-cycle-manager,project-review-manager,github-review-repair-agent}.md`, `skills/{github-review-procedure,local-review-cycle-procedure,project-review-procedure,project-review-apply-procedure,reviewer-contract,review-lens-contract,security-review-rubric,prompt-review}/` | `assets/{commands,agents,skills}`, resolved through settings layers | Keep, moved |
| `dot_claude/agents/{codebase-*,productivity-coach,test-generator,web-search-researcher}.md`, `commands/{research_codebase,generate_prd,literal_create_plan,remind}.md`, `skills/{terse-docs,tighten,workflow}/` except the context executable | — | Stay in dotfiles |
| `dot_gemini/config/{AGENTS.md.tmpl,skills.json}`, `dot_config/opencode/commands/*` | `install/{agy,opencode}.py` renders them from the same resolved assets | Keep, moved |
| `dot_claude/skills/workflow/executable_wf-context.sh` | `commands/context.py`, `assets/prompts/workflow-context.md` | Consolidate |
| `workflow/adapters/*.md` | `assets/prompts/backends/*.md` | Keep |

Test suites move with their module. Black-box parity fixtures captured from the dotfiles scripts become `tests/parity/<command>/` and are deleted only in the retirement phase.

## Compatibility while both implementations exist

| Surface | Requirement |
| --- | --- |
| `<worktree>/.workstream.json` | Fovea reads both the v0 format and the legacy format, and converts on write exactly per [the migration table](workstream-schema.md#migrating-workstreamjson). Dotfiles readers keep working because phase 2 also teaches `tools/lib/workstream.py` to read v0 (`schema_version`, `slug`, `prs`, `stage`, deriving `key`) and teaches the other readers in that table the v0 shapes they depend on: `repo_facts.py` and `repo-facts.sh` from the file, `open-pr.sh` (`ticket_provider`, `desc`) and `github-review-state.sh` (`pr.head`) through `workstream.sh show`. The reader changes and Fovea's first real conversion ship together, and no legacy key is written back. |
| Legacy `<git-dir>/chain` | Read-only loader during the overlap; no new files written. |
| Session records | New format, Fovea-only. Nothing in dotfiles reads them, so no fallback is needed. |
| CLI invoked by prompts | Same subcommand name, flags, stdout contract and exit codes as the script it replaces; prompts switch in the PR that flips the shim. |
| `tools/*.sh` on `PATH` | Each ported script becomes a one-line shim that `exec`s `fovea <verb> "$@"`, removed one release after its prompt switches. |
| `gh` | The forge adapter shells to `gh`, never an SDK, so `cloud-gh-shim.py` keeps intercepting cloud sessions. |
| Environment | `WS_*` is canonical; `GT_*`, `GIT_TOOLS_PROJECTS_DIR` and `PROJECT_OVERLAYS_DIR` remain fallbacks until the last dotfiles consumer is gone. |
| Config | `start-ticket.conf`, `GT_*` and `.worktree-sync` are readable as the lowest settings layer per [settings](workstream-config.md#tooling). |
| Prose and formats | Existing user files stay authoritative: the resolver finds them before Fovea's defaults. |
| Statusline | Same stdin JSON and one-line stdout; rendering read-only. |
| Hooks | Same Claude/Codex/agy event names and payload shapes; OpenCode keeps command wrappers. |
| Telemetry log | Append the existing JSONL schema, with the same `run_id` and field names, plus a memory sample event, so dotfiles reports can read Fovea events and vice versa. |
| `wm` | Alias preserved by `install`. |
| Cloud bootstrap | One pinned release archive with a checksum plus a one-file bash bootstrap that fetches and installs it before Python exists, replacing per-file fetch and `workflow/manifest.txt`. |

## Walkthrough: session launch

1. `fovea start 280` in `commands/start.py` resolves settings, then asks `adapters/tracker/github` for the ticket and `adapters/worktree` for the repo's branch convention.
2. The worktree adapter creates the branch and worktree; `lifecycle.workstream.create` assigns `ws-…`, writes the workstream record and index entry, registers `.git/info/exclude`, and emits `ticket.start`.
3. The command resolves the kickoff prose and formats through `settings`, renders them with `ui`, then calls `adapters/launcher/claude.launch` with the declared purpose `implement` and role `lead`. The launcher writes no records.
4. Claude fires `SessionStart`; `fovea-hook session-start` reads the payload through `adapters/agent/claude`, and `lifecycle.session.start` loads the workstream by `cwd`, creates the session record linked to it, applies the declared role and purpose, and returns added context.
5. The hook only prompts the agent to run `fovea session check`, which runs on every start: it reads the lead session with `read_sessions(workstream_id=…)`, resolves running state for it through `adapters/agent/<tool>`, and passes that fact to `lifecycle.lead.check`, which takes the role when the lead is `ended` or confirmed not running and asks when there is no lead record or it cannot tell.
6. The statusline command reads records through `record/query.py`, gathers local git facts through `adapters/worktree`, builds a view with `ui/view.py`, renders it with `ui/statusline.py`, and hands it to `adapters/ui/claude_statusline.py`.

Codex and agy reach the same lifecycle code through their hook payload adapter; OpenCode reaches it through its plugin or command wrapper. Only steps 3, 4 and 6 differ per agent and surface.

## Walkthrough: workstream handoff

1. `fovea takeover --workstream ws-9c41e07a52bd --to codex` reads the index entry, then the workstream record.
2. `fovea takeover` reads the linked lead session with `read_sessions(workstream_id=…)` and resolves its running state through `adapters/agent/<tool>` from `tool`, `native_id` and `process`; `lifecycle.lead.check` then applies that fact, per the [lead check](workstream-lifecycle.md#lead-check-and-takeover). A running lead is replaced only on the user's explicit request.
3. `lifecycle.lead.takeover` marks the old record `ended` (`replaced`) and leaves it holding the role, so a failed launch is still findable.
4. `adapters/launcher/codex.launch` starts the new session in the worktree with the workstream ID, transcript path and purpose `implement`.
5. The new session's start hook links it through `lifecycle.session.start`; `lifecycle.lead.assign_role` makes it lead and demotes the old record to `helper`.
6. The session end and start events are logged for the handoff. If the launch fails, the old record is `ended` but still lead; the next lead check can fill it.

## Migration order

Each phase ends with its exit criterion met and is a separate PR in Fovea; a phase that names a dotfiles-side change ships it as a companion PR.

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 1. Skeleton, contracts, settings | Package, two entries, `contracts.py`, dependency rules and boundary test; settings layers, resolve, explain, prose lookup, legacy fallback; `commands/config.py` with `explain` only | A deliberate cross-layer import fails CI; `fovea config explain` matches `repo_facts conf-get` over the fixture matrix. |
| 2. Record | Types, validators, store, lock, paths, index, pending queue, queries, legacy conversion, with a companion dotfiles change teaching `tools/lib/workstream.py` and the other readers in [the migration table](workstream-schema.md#migrating-workstreamjson) — `repo_facts.py`, `repo-facts.sh`, `open-pr.sh`, `github-review-state.sh` — to read v0 | Round-trip and migration fixtures match the schema doc; converting a real old record leaves every dotfiles reader working. |
| 3. Lifecycle and telemetry | Session, workstream, lead, reviews, PRs, attention, gates, names; event schema, emitter and local sink | State-machine tests, including finish/drop ordering and the surprise policy; lifecycle imports no adapter and no command. |
| 4. Adapters | Agent, tracker, forge, worktree, launcher, host, UI; exec | Fixture parity with the current `gh`, `git` and launcher command shapes; running check agrees with dotfiles on live sessions. |
| 5. Commands | `phase`, `session`, `workstream`, `context`, `snapshot`, then `start` with `discuss` and `iterate`, `open-pr`, `sync`, `merge`, `finalize`, `drop`, `land`, `review`, `prune`, `takeover`, `worktree`, `project_review`; the `ui` modules they render with — `tags`, `view`, `names`, `documents`, `snapshot` | Each command passes its parity fixtures; its `tools/*.sh` shim flips in the same PR. |
| 6. Telemetry reports and UI | `telemetry`, `statusline`, `dashboard`; report, usage, memory, gaps, backfill; the statusline, dashboard and surface renderers | Statusline byte parity on fixture records and each entry's hot-path budget, met by the Python entry or its shim; telemetry events readable by the dotfiles report. |
| 7. Assets and install | Default prompts, agents, skills and templates; layer overrides; backend renderers and hooks; release archive and checksums | A clean machine installs Claude, Codex, OpenCode and agy from Fovea alone; a user layer overrides a default without editing Fovea. |
| 8. Cutover | Switch prompts and hooks to Fovea, keep `.workstream.json` compatibility, move the memory guard, delete dotfiles implementations and shims | One full ticket runs on each backend with no dotfiles workflow code on `PATH`; then delete. |

Order follows dependencies: contracts and settings are leaves; record needs neither; lifecycle needs record and telemetry; adapters need contracts and settings; commands need everything; UI surfaces and reports come last because nothing depends on them, except the tag, view, name, document and snapshot renderers the phase-5 commands need. Telemetry emission lands in phase 3 with a local sink so later phases can emit, while its reports land in phase 6.

## Open

- Distribution: `uv tool install` from a release archive, a PyInstaller-style binary, or the chezmoi install path. This decides the cloud bootstrap artifact.
- Which TUI library the dashboard uses; `ui/dashboard/` stays library-independent.
- The provisional session fields and the session storage path inherited from [the schema](workstream-schema.md#open).
- Remote telemetry and analytics providers, and whether they are sinks, readers or both.
- Whether `executable_no-cd-write.py` eventually moves into Fovea's install.
