# Project review generalization spike (#117)

## Recommendation

**Build `/project-review` as a thin command that launches a fresh orchestrator agent, which fans out read-only "lens" agents, synthesizes centrally, and (optionally) applies doc-level changes in one PR.** Mirror `/local-review-cycle`: command → manager agent → procedure skill, with lens agents discovered through the same three tiers. Project inputs go in one new overlay doc, `review.md`, resolved by the existing `project-config.sh find`; tracker and key documents stay in `governor.md`. Nine follow-up tickets (below), each one reviewable unit.

The source is a weekly review (here generalized to a periodic one) written for one private project: one orchestrator brief, five subtask briefs, a manual entry point. Most of it is generic choreography and review method; the project-specific part is repo coordinates, doc names, grep probes, and worked examples.

## Generic vs project-specific

| Piece | Generic | Project-specific |
| --- | --- | --- |
| Orchestration | Activity gate, one read-only snapshot of the default branch shared by all lenses, tracker pull with truncation check, abort-on-no-dedup, fan-out, central synthesis, cleanup on every exit path | Repo coordinates, scratch/clone paths, the gate's source/test path globs, "significant" threshold wording |
| Synthesis | Cross-lens dedup; tag `NEW` / `KNOWN` / `ALREADY TICKETED`; recurrence trail; 3+ unticketed sweeps escalates; priority order | Backlog and archive doc names |
| Act step | File only new P0 issues; never close/edit/redefine existing tickets; queue those as ready-to-run rows in a pending-actions file with an idempotent-update rule; mechanical doc fixes only; one PR, never merged | File names; PR title |
| Report | Grouped by lens, "verified clean" list, per-lens word caps; separate triage report | Recipient, subject lines, delivery channel (email) |
| Lens: architectural soundness | Boundary check, duplicated concept/near-identical-method/unadopted-pattern hunt, per-subsystem pattern pass with file:line evidence | Boundary rule and its probes, subsystem list and paths |
| Lens: code quality | Convention drift, data-layer consistency, build/test/tooling hygiene, CI trigger sanity | Every grep probe, style-guide names, known-exception notes, CI notes |
| Lens: document consistency | Docs vs code, docs vs docs, the review's own infrastructure, naming/placement, docs that no longer earn their place; mechanical-fix vs finding split | Which docs count as "top-level mechanism docs" |
| Lens: plan compatibility | Scope divergence, forward risk traced to a specific open epic, scaling headroom vs stated future numbers, short-term shortcuts | Planning doc names, stated capacity targets, worked examples |
| Lens: ticket triage | Duplicate detection, ticket-state consistency, tech-debt prioritization, work clustering for parallel runs, pending-actions format | Labels, "current focus" docs |
| Manual mode | Same lenses, read-only, inline report, no ticket or email steps | None |

## Per-project inputs

| Input | Where configured | Notes |
| --- | --- | --- |
| Repo coordinates, default branch | `repo_facts` (origin remote) | Nothing to configure |
| Tracker and provider | `governor.md` (tracker) + `start-ticket.conf` `provider` | Existing keys; GitHub first, others via the provider pattern in `tools/start-ticket-providers` |
| Planning docs (roadmap, milestones, todo) | `review.md` § Planning docs | Roles, not names: `roadmap`, `capacity-targets`, `current-focus`. **Ownership:** `review.md` owns the paths the review reads. `governor.md` § Key documents stays the governor's reading list and is the fallback when a role is absent from `review.md`; a path is never maintained in both |
| Backlog, archive, pending-actions docs | `review.md` § Review state | Paths the apply step may edit; absent = report-only |
| Cadence and activity gate | `review.md` § Cadence | `Window:` in days (default 7) and path globs; the gate skips a run with no significant activity in the window. The schedule itself lives in the routine, so each project sets its own |
| Subsystem map | `review.md` § Scope | Name → paths, feeds the architecture lens |
| Invariants and probes | `review.md` § Invariants | Deterministic commands with expected result; lenses run them instead of embedding greps |
| Conventions docs | `review.md` § Invariants | Style guide, contributor doc |
| Extra or skipped lenses | `review.md` § Lenses | `Skip:` list; extra lenses are agent files, not config |
| Delivery | `review.md` § Delivery | `inline` (default) \| `file:<path>` \| `email:<address>` |
| Scheduling | Outside the repo | Routine/cron definition holding one pointer sentence to `/project-review` |

**Why a new doc, not more `governor.md`:** `governor.md` is loaded into every governor session as prose context. Probes and subsystem maps would bloat every load for a periodic job. `review.md` uses the same repo-else-overlay resolution (`project-config.sh find review.md`; `find-doc` is name-generic) and ships as one more file in `tools/project-config-templates/`, which `init` already copies. Work-specific content lives only in the private overlay.

## Plug-in design

| Aspect | Design |
| --- | --- |
| Lens file | Agent-format file; `use_when: periodic project review` key above `description:` (see below), plus a `Lens: collect \| triage` tag. Read-only. Own contract skill, `review-lens-contract` (snapshot path in, findings out, file:line evidence, `lens` tag, word cap), because `reviewer-contract` is diff-scoped |
| Discovery | Same tiers and name-dedup as `/local-review-cycle`: repo `.claude/agents/` → personal `docs/local/reviewers/*.md` and overlay `claude/agents/` (`project-config.sh list agents`) → global `dot_claude/agents/`. A project lens with a global lens's name overrides it. Personal and overlay files are not registered agent types, so they launch the way the cycle launches them (read the file, run its body as a `general-purpose` brief) |
| Selection | Discovered files are first filtered to those declaring `Lens: collect | triage`, so ordinary agents (`local-review-cycle-manager`, `correctness-reviewer`) never launch as lenses. Every remaining lens runs unless named in `review.md` `Skip:`. No `use_when:` matching: unlike diff review, there is no diff to match against |
| Global defaults | `review-architecture`, `review-quality`, `review-docs`, `review-plan`, `review-triage`. They read `review.md` for scope, probes, and doc roles; they hold no project text |
| Per-project lenses | Overlay agents for domain checks the globals can't express (e.g. a module-boundary specialist) |
| Tracker access | Triage and apply go through the provider seam, not hard-coded `gh`. The seam today (`tools/start-ticket-providers/*.sh`) covers only ticket fetch, worktree, and in-progress; #135 and #137 extend it with list/search, create issue, comment, and label/state update. A provider that lacks them falls back to report-only: triage reports, `--apply` refuses to file or edit |

## `use_when:` placement (both review kinds)

`Use when:` is easy to miss as the last sentence of a long `description`. Every reviewer and lens carries it as its own `use_when:` frontmatter key directly above `description:`; the clause leaves `description`. This changes the existing `/local-review-cycle` reviewers too (#140): the contract's authoring convention, procedure §2 selection, and the architecture doc move together. Catalog visibility is the cost: the agent catalog lists `description` only, so selection reads reviewer files, as it already does for overlay reviewers. #140 settles that detail.

## Form and placement

| Decision | Choice | Reason |
| --- | --- | --- |
| Form | Command + `project-review-manager` agent + `project-review-procedure` skill | Matches the proven `/local-review-cycle` split; the command stays a launcher and holds no findings |
| Where it runs | Fresh manager agent, launched from any session, scheduled or manual. Not a sibling session | A governor session's history would bias the lenses (same reason `/local-review-cycle` never reads the diff). The governor consumes the report afterwards, e.g. to feed `/groom` |
| Modes | Default read-only, inline report. `--apply` adds P0 filing, pending-actions and backlog updates, one PR | The source's manual path was already read-only; mutation belongs only to the scheduled run |
| Scheduling | A `/schedule` routine at any cadence the project picks; its stored prompt is one pointer sentence | The source found any extra text in a stored prompt is drift; keep the logic in the repo |
| Prompts | Lens briefs state method and output only; probes and names come from `review.md`. Target under 60 lines per lens | Terse, minimal-token, and nothing project-specific in the public repo |

## Constraints and flags

| Concern | Handling |
| --- | --- |
| Public repo | No project names, paths, ticket text, or probes in lenses, templates, or docs; the template uses placeholders only. `dotfiles-safety-reviewer` (a diff reviewer for this repo, not a periodic lens) runs on every follow-up PR. No generic safety lens ships; a project wanting a periodic safety check supplies one as an overlay lens |
| Machine-specific | A scheduled run needs authenticated tracker access and a delivery channel on the executing host. Email delivery needs a mail connector; absent, fall back to `file:` or `inline`. Overlay content (and so work-specific config) exists only where that overlay is synced. Snapshot uses a repo-local scratch dir, which must be gitignored |
| Safety invariants carried over | Abort if the tracker pull fails or truncates; never mutate an existing ticket; idempotent pending-actions rows keyed `(issue, action)`; clean up the snapshot on every exit |
| Telemetry | New `wf-event.sh` events per lens finding and run result, following `review.finding`/`review.result`. `wf::emit` writes nothing outside a ticket branch unless `ticket=`/`scheme=` are passed, and a scheduled default-branch run has neither. #138 defines a stable run identity (e.g. `ticket=project-review-<date>`) passed explicitly, and how `wf-report` shows these non-diff runs, before telemetry is claimed |
| Adapters | `workflow/adapters/*` and `tools/cloud-workflow-adapter.test.sh` need a decision on whether the command is covered |

## Follow-up tickets

Ordered; each is one reviewable unit. **#140 lands first and alone**: it changes live selection for every existing reviewer, so nothing else merges until it does.

| Issue | Ticket | Depends on |
| --- | --- | --- |
| #140 | Move `Use when:` to its own `use_when:` frontmatter key for all reviewers (local and periodic); update contract, procedure, architecture doc | — |
| #132 | `review.md` overlay template with sections Planning docs, Review state, Cadence (`Window:`, path globs), Scope, Invariants, Lenses, Delivery; `project-config` init/find coverage and tests; `workflow-tools-usage.md` entry | #140 |
| #133 | `review-lens-contract` skill and lens discovery rules (tiers, override, `Skip:`), using `use_when:` | #132, #140 |
| #134 | Global lenses: architecture, quality, docs, plan; driven by `review.md` | #133 |
| #135 | Triage lens plus pending-actions file protocol; tracker via provider seam | #133 |
| #136 | `/project-review` command, manager agent, procedure skill: gate, snapshot, fan-out, synthesis, inline report | #134 |
| #137 | `--apply` mode: P0 filing, backlog and pending-actions updates, single PR; delivery channels | #135, #136 |
| #138 | Telemetry events and `wf-report` section; `docs/workflow-architecture.md`; adapter decision | #136 |
| #139 | Scheduling guide: routine setup, per-project cadence, home/work flags, overlay seeding | #137 |
