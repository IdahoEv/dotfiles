# Published agentic workflows vs. the dotfiles workflow

The dotfiles workflow is stronger than the three named sources on review isolation, side-effect ownership, and measurement, and weaker on durable decision memory, persisted plan/handoff artifacts, and explicit cost/attention routing. A broad search added four first-party sources that most change the ranking: Anthropic's own review process (independent verification, 3-round cap, diff-only re-review), Claude Code's agent view (attention states derived from external state), OpenAI Symphony (tracker-as-queue with stall detection and turn/concurrency caps), and GitHub Agent HQ (PR-centric control plane across vendors). The highest-value adoptions are the review-pipeline changes, an attention queue, and review policy as a base-branch artifact; the ADR loop and measured model/effort routing remain worthwhile but rank lower.

## Sources and revisions

| Short | Repository | Revision reviewed | Form | Provider dependence |
|---|---|---|---|---|
| UG | [FlorianBruniaux/claude-code-ultimate-guide][UG] | `f97e4f7b9cde282b339f2757442e18762e028ba2` | Community guide plus runnable examples | Claude Code features; some pages name unverifiable model versions |
| GHW | [alirezarezvani/claude-code-github-workflow][GHW] | `d98f0eb1c5e9a41ec354f4fa6b2edf267d0c3a8d` | Copy-paste GitHub Actions blueprint (12 workflow files, 8 commands, 4 agents; the README advertises 8 workflows) | GitHub Actions, Projects v2, `gh`, Anthropic API key |
| ORO | [OneRedOak/claude-code-workflows][ORO] | `29a34c725313c7621f426f838ed31cf482473fb4` | Review workflows plus a 16-page orchestration playbook | Claude Code and Codex; GitHub Actions; Playwright MCP for design review |
| Symphony | [openai/symphony][SYM] | `v0.0.3` (`SPEC.md`) | Daemon spec: poll tracker, per-issue workspace, retry/stall handling | Linear + Codex app-server |
| Anthropic review | [Claude Code Code Review docs][CC-REVIEW]; [Anthropic team write-up][ANTH-REVIEW] | Accessed 2026-11-27 | Managed multi-agent PR review plus first-party process description | GitHub; Anthropic service |
| Agent view | [Claude Code agent view][CC-AGENTS] | Accessed 2026-11-27 | Background-session dashboard grouped by external state | Claude Code (research preview) |
| Agent HQ | [GitHub Agent HQ][GH-HQ]; [mission control][GH-MC] | Accessed 2026-11-27 | One control plane for Copilot, Claude, and Codex on issues/PRs | GitHub, including mobile |
| Cost/effort/latency | [Claude Code costs][CC-COST], [model and effort][CC-EFFORT], [prompt caching][CC-CACHE], [OpenAI latency][OAI-LAT], [Codex models][OAI-MODELS] | Accessed 2026-11-27 | First-party cost, effort, and latency guidance | Claude Code; OpenAI API/Codex |
| Review policy | [REVIEW.md][CC-REVIEWMD]; [Codex GitHub review][OAI-GHREVIEW] | Accessed 2026-11-27 | Review-only rules read from the base branch; severity floors | Claude Code; Codex |
| Queue and stacks | [CodeRabbit Triage][CR-TRIAGE]; [Graphite stacked review][GRAPHITE] | Accessed 2026-11-27 | P0–P3 queue with next action; stacked PRs and merge queue | GitHub Cloud; GitHub |

"Mechanism" below means code, config, spec, or a shipped product behavior. "Advice" means prose guidance with no runnable counterpart. Evidence is graded as mechanism, first-party metric, community benchmark, or advice; no source supplies a controlled comparison against this workflow.

## Comparison on the four axes

| Axis | Dotfiles | UG | GHW | ORO |
|---|---|---|---|---|
| **Plan and track** | Ticket → `/start` worktree + `.workstream.json`; plan approval gate; chains as one PR; `/pick` groups, `/groom` refines tickets; phase tags and PR/review state in the record | [Plan pipeline][UG-plan-pipeline]: PRD analysis → technical analysis → scope tier (0–4) → parallel research team → `plan-*.md` + ADRs + metrics; two validation layers; worktree execution to PR. [RPI][UG-rpi]: RESEARCH.md/PLAN.md with GO/NO-GO and plan gates. [Tasks API][UG-tasks]: disk-persisted hierarchy with dependencies | Plan JSON (max 10 tasks) → [issues + labels + project board][GHW-arch], auto branch on ready issue, status labels synced to board columns; no plan-review gate | No planning system. [Review triage manifest][ORO-triage] records every finding decision |
| **Context and handoff** | Fresh review manager and leaf reviewers; `reviewer-contract`; kickoff preamble; `.workstream.json` resume; project overlays; no formal plan or progress artifact | [`/clear` between stages][UG-plan-pipeline-context] with files on disk as handoffs; [dual-instance contract][UG-dual] binds approval to a revision; [progress.md and session lifecycle][UG-task-progress]; [context budget, pointer strategy, 120-line CLAUDE.md][UG-context] | `CLAUDE.md` plus plan JSON → issues; status labels/board as state; no session handoff artifact | [Review manifest before edits][ORO-skill] with source, location, confidence, decision, rationale; four-pillar context/tools/workflows/verification advice |
| **Parallel isolation** | Worktree per ticket/chain; tmux, OpenCode session, and Codex launchers; memory guard; sibling-repo fan-out; read-only reviewers; repair agent edits only; commands own pushes and GitHub writes; one PR per chain | Worktrees; [`isolation: 'worktree'` per agent][UG-dynamic]; [Agent Teams git-based locking][UG-teams] (experimental); separate dual-instance sessions; isolated Best-of-N candidates | [Actions concurrency groups and cancel-in-progress][GHW-scale]; fork PRs read-only; branch protection; no worktree model | Dual loop (slash command + CI); subagent keeps the main thread's context; one Action run per PR; [subagent has write tools][ORO-subagent], so isolation is weaker than a read-only reviewer |
| **Verify and review** | Pre-PR local cycle in a fresh manager; [risk-selected reviewers][LOCAL-arch]; shrinking rounds; 20-call retrieval budget; evidence bar; DESIGN gate; 5-round cap; FAST/FULL; per-reviewer telemetry; bot loop + repair agent; periodic project lenses | [Managed Code Review][UG-codereview] find/verify/rank; [role-separated multi-provider review][UG-multiprovider]; CI-gate and dedupe guidance; delta review; batching over 75 files; [adversarial verification][UG-dynamic-adv]; [Best-of-N verification][UG-bon]; [rationale notes][UG-notes] | [Quality gates, secret scan, `/review-pr`][GHW-commands]; squash-only merge; branch protection; no fresh-context reviewer protocol or finding-validation loop | [Pragmatic hierarchy][ORO-subagent] (architecture/correctness/security first), Critical/Improvement/Nit triage, security non-negotiable; [per-source confidence priors][ORO-triage]; [bounded CI fix loop][ORO-skill] (2 attempts, 1 flaky rerun, 30-minute cap); 10-second report; [Playwright design review][ORO-design] |

## What the added sources contribute

| Source | Contribution | Evidence | Provider |
|---|---|---|---|
| [Symphony spec][SYM] | Tracker is the queue; `WORKFLOW.md` is repo-versioned policy; per-issue workspace; stall timeout (300 s), `max_turns` (20), `max_concurrent_agents` (10), capped backoff, credential stripping; fresh clones rather than worktrees | Spec + mechanism; authors call it a preview | Linear + Codex |
| [Anthropic review process][ANTH-REVIEW] | Find agents in parallel, a separate group votes per finding, style/cleanup findings dropped, Important/Nit/Pre-existing; 3-round cap; diff-only re-review; no repeated findings; risk-tiered human approval (low none, medium one, high two); incident-derived eval set | Mechanism + first-party metrics (one-round pass 65→78%, five-plus rounds 8.9→1.5%); unaudited | GitHub + Anthropic |
| [Agent view][CC-AGENTS] | Groups sessions as Ready for review / Needs input / Working / Completed; state comes from PR, checks, permission prompts, and explicit questions, not agent self-report; `claude agents --json` exposes `waiting`/`waitingFor` | Shipped mechanism; preview | Claude Code |
| [Agent HQ][GH-HQ] | Assign one issue to several agents, compare draft PRs, watch logs, pause/refine/restart; coordination lives on the PR | Shipped product | GitHub, multi-vendor |
| [Harness Engineering][OAI-HARNESS] | Repo as knowledge base, ~100-line `AGENTS.md` map, agent-to-agent review, periodic drift cleanup; optimizes human time, not agent volume | Advice, single team, self-reported | Neutral |
| [Cost][CC-COST], [effort][CC-EFFORT], [caching][CC-CACHE] | Cost is context size × turns × concurrent contexts; tool results are resent every turn; effort changes files read and verification performed, not just thinking; keep the prompt prefix stable and do not switch model mid-conversation | Advice + in-product mechanisms | Claude Code |
| [Latency guide][OAI-LAT] | Fewer input tokens, stable prefix, fewer sequential calls, parallel and async tools, output caps, `previous_response_id` | Advice | OpenAI API |
| [Codex models][OAI-MODELS] | Six-level effort ladder; Ultra fans out to subagents; subagent workflows cost more than single-agent runs | Advice + config | Codex |
| [CodeRabbit Triage][CR-TRIAGE] | Queue ranked P0–P3 from severity, risk, blast radius, review effort, blocked-behind count, plus one “next action” per card | Shipped mechanism; weights unpublished | GitHub Cloud |
| [REVIEW.md][CC-REVIEWMD] / [Codex review rules][OAI-GHREVIEW] | Review-only rules injected at highest priority and read from the base branch; Codex posts only P0/P1; directory-scoped rules | Shipped mechanisms | Claude Code / Codex |
| [Graphite][GRAPHITE] | Stacked PRs and a review inbox; smaller diffs, review in parallel with authoring, ordered merge | Mechanism + vendor case studies | GitHub |

## Ranked practices

| Rank | Practice (source) | Problem here | Evidence | Cost / limitation | Form | Provider |
|---|---|---|---|---|---|---|
| 1 | **Independent verification, 3-round cap, diff-only re-review, drop style and cleanup findings** (Anthropic review) | The cycle manager both triages and fixes; findings get one judgment; the 5-round cap keeps going after reviewers mostly rediscover old code | [Team write-up][ANTH-REVIEW] reports a separate vote per finding, 3-round cap, diff-only re-review, and findings “only about style, diagnostics, or cleanup” dropped; metrics 65→78% one-round pass and 8.9→1.5% five-plus rounds; vendor, unaudited | Extra verifier calls; a drop rule can mislabel a real defect as style and hide it; a 3-round cap can cut off legitimate long fixes | Mechanism + first-party metrics | GitHub + Anthropic; logic portable |
| 2 | **Attention queue derived from external state** (agent view, CodeRabbit, Agent HQ) | `[!]` and statusline are per session; nothing aggregates “needs input”, “ready for review”, “checks failing” across worktrees, and phase tags are partly model-set | [Agent view][CC-AGENTS] derives states from PR/checks/permission prompts; `claude agents --json` exposes `waiting`/`waitingFor`; [Triage][CR-TRIAGE] adds priority plus next action | Cross-host state mapping; extra API calls; stale or false “needs me” | Shipped mechanisms, no efficacy data | Host-specific discovery |
| 3 | **Review policy as a base-branch artifact** (REVIEW.md, Codex rules) | Reviewer contracts and project overlays exist, but there is no single review-policy file, and a cloud install takes its reviewer files from `WORKFLOW_REF` (default `main`), so an install pointed at a branch supplies the files that branch is reviewed against | [REVIEW.md][CC-REVIEWMD] is auto-discovered, read from the base branch, and can cap nits and skip generated paths; [Codex][OAI-GHREVIEW] scopes rules by directory | Another config surface; drift from `CLAUDE.md` and reviewer contracts | Shipped mechanism | Claude Code / Codex |
| 4 | **Tracker-as-state-machine contract** (Symphony, Agent HQ) | Orchestration is session-driven; retry, stall detection, turn and concurrency caps live in prose or not at all; telemetry notices a stall only after 24 h | [Symphony spec][SYM] defines retries, 300 s stall timeout, `max_turns` 20, concurrency 10, backoff; [Agent HQ][GH-HQ] moves coordination to the PR | Wholesale adoption means a daemon and fresh clones; Symphony is a preview; Agent HQ is GitHub lock-in | Spec + shipped products | Linear/Codex; GitHub |
| 5 | **ADR decision-memory loop with maturity levels** (UG) | Architecture decisions are re-litigated in plan gates; rationale lives in PRs and prose, not a consultable record; `/groom` sharpens ACs but records no decisions | [Plan pipeline][UG-plan-pipeline-adr] claims 20 plans auto-resolve ~80% of decisions and gives a 3-ADR “Confirmed” threshold; advice, no measurement | Authoring and trimming ADRs; stale rules can auto-resolve wrongly; converts judgment into rules | Advice + example; loop not implemented | Neutral |
| 6 | **Context, turn, and concurrency budget before model routing** (Anthropic cost, OpenAI latency) | Telemetry measures tokens and stage time, but nothing budgets context size, turn count, or fan-out per ticket; reviewer fan-out is unbounded by a token budget | [Cost docs][CC-COST]: tool results are resent every turn and output tokens are priced above input; levers include `/clear`, `/context`, subagent isolation, fewer servers; [latency][OAI-LAT] adds stable prefix and parallel/async tools; [caching][CC-CACHE] warns against changing tools or model mid-conversation | Instrumentation work; over-trimming can remove needed context; cache metrics depend on host logs | Advice + mechanisms | Claude Code / OpenAI |
| 7 | **Model/effort routing measured by `wf-report.sh`** (Anthropic effort, Codex models) | Reviewers default to one model; `reviewer-model.sh` is a global toggle, not risk-based; per-reviewer token use and validity are already logged but unused for routing | [Effort article][CC-EFFORT]: effort changes files read and verification, and a smaller model can burn more total tokens; [Codex models][OAI-MODELS]: six levels, Ultra fans out; dotfiles logs model/effort/validity/overlap | Misroute causes retries or weaker review; model IDs differ per host; switching mid-run invalidates the cache | Advice + config; telemetry present | Model names provider-specific |
| 8 | **Persisted plan/handoff artifact** (UG RPI, dual-instance, progress.md) | Plan approval is conversational; resume after compaction or interruption relies on `.workstream.json` plus prose; no base revision, checks, blockers, or next action in one place | [RPI gates][UG-rpi], [dual-instance contract][UG-dual], and [progress.md][UG-task-progress] supply templates; guide cites an Anthropic harness result, not a comparison | Artifact drift from code and record; extra write step; deciding whether it is committed or worktree-local | Templates + advice; no enforcement | Neutral |
| 9 | **Triage manifest with priority and next action** (ORO, CodeRabbit) | Verdicts and reasons are logged, but there is no per-round human-readable manifest or single “what is the next action” field across local, human, and bot findings | [Triage template][ORO-triage] records every decision including skips; [Triage queue][CR-TRIAGE] adds P0–P3 and one next action; weights unpublished | Format drift; model compliance; duplicates the verdicts file and telemetry | Templates + advice; queue is a product | Forge-neutral manifest; queue GitHub-only |
| 10 | **Best-of-N at the design gate** (UG) | The first plausible plan wins; a wrong architecture discovered late is the expensive failure | [Best-of-N protocol][UG-bon]: frozen rubric, independent candidates, blind scoring, external verification; [evidence boundary][UG-bon-evidence] says research supports sampling on reasoning tasks, not software changes | 3× plan tokens, rubric authoring, selection bias, longer gate; only pays when candidates differ materially | Template + skill; no local measurement | Neutral; needs isolated contexts |

## Proposed experiments

Each is small enough for one ticket; all are reversible.

| Experiment | Design decision informed | Signal |
|---|---|---|
| Add a refute-only verifier vote on Critical/High findings in `/local-review-cycle`; test a 3-round cap against the current 5 | Verifier placement (cycle manager vs separate leaf); whether to cap rounds by count or by new-finding rate | Fixed-then-reverted changes, dismissed-finding validity, unresolved findings at cap, rounds |
| Derive an attention queue from `.workstream.json`, PR/check state, and `claude agents --json` `waitingFor`; rank needs-input → failing checks → ready for review → stalled → working | Whether phase/tags stay the single source or an aggregate status service is needed | Time from `[!]`/`waiting` to first human action; missed stalls |
| Add a `REVIEW.md` here, read from the base branch, with severity definitions, nit cap, and generated-path skips | Whether review policy lives in `REVIEW.md`, reviewer contracts, or project overlays | Repeated findings, nit volume, rule-drift incidents |
| Define explicit record states (queued, working, needs-input, in-review, ready, merged) and borrow Symphony's stall/retry/turn caps as validation, without a daemon | How far `.workstream.json` should model orchestration | Stalled runs caught before 24 h; retries; concurrent launches |
| Seed `docs/adr/` with 3 decisions already made here; adopt the 3-ADR “Confirmed” threshold; have `/groom` and the plan gate consult ADRs | Whether the record references ADRs; whether project review gains an ADR lens | Plan-gate questions, reversals, ADR edits per ticket |
| Record context size at phase boundaries and per-ticket turn counts; set a fan-out budget for reviewers | Which context levers matter here; where a token budget belongs | Tokens per merged ticket, context at DESIGN gate, reviewer tokens |
| Route security/supply-chain reviewers (or high-risk diffs) to a stronger model/effort for ~10 runs; compare with `wf-report.sh` | Whether routing lives in reviewer frontmatter, a table, or a cycle flag | Validity, overlap, rounds, tokens, cost per merged ticket |
| Write a worktree-local plan note for design-gated tickets (scope, base SHA, ACs, checks, blockers, next action); have resume read it | Plan location (committed doc vs worktree-local); relation to ticket ACs and the record | Clarification turns after resume; wrong-assumption incidents |
| Add a Markdown triage manifest beside the bot verdicts file, with priority and next action | Whether the manifest is local, committed, or a PR comment | Triage time; unexplained skips |
| Offer 3 plan candidates behind a design-gate flag; score blind against a frozen rubric | Whether the gate supports `--candidates`; how plan isolation works | Plan revisions, rework, added tokens per accepted ticket |
| Add `gh api rate_limit` preflight to `open-pr.sh` and tracker writes; queue below threshold | Threshold and fallback path | Partial-operation incidents, blocked runs, queue depth |

## Considered but not recommended now

| Practice | Why not now |
|---|---|
| Adopt Symphony/Agent HQ/Vibe Kanban/Orchestrator wholesale | Large migration to a daemon or hosted control plane; Symphony is a preview, Agent HQ is GitHub lock-in; borrow the state machine, stall/retry caps, and attention semantics instead |
| Dynamic-workflow JS orchestrator, Agent Teams, Tasks API persistence | Claude Code-version-specific and experimental; dotfiles already has bounded subagent fan-out, per-ticket worktrees, and file-based state that works across hosts |
| GitHub Projects v2 board sync | GitHub-only; creates a second source of truth beside `.workstream.json`, with drift and API cost |
| Global kill switch | Round caps, memory guard, and provider exit codes already stop most runaway paths; a kill switch adds a surface with no current failure to justify it |
| Rationale note per hunk in git notes | [The guide's own evidence review][UG-notes-limit] finds no study showing better defect detection, and notes are self-reported and stale-prone; the capped PR-body Summary/risk sections cover the same need more cheaply |
| Delta-review marker | The local cycle already scopes later rounds to fix commits; remote bots own their re-review scope |
| Per-reviewer worktree isolation | Reviewers are read-only; full repo copies add seconds and disk for no protection beyond what the read-only contract already gives |
| Stacked PRs (Graphite) | Single-owner repo with one PR per chain; stacking adds rebase and merge-queue overhead without parallel reviewers to unblock |
| Severity-floor suppression (Codex posts only P0/P1) | Might hide medium findings that matter here; test alongside the verifier rather than adopt |
| Claude Code Router or mid-task model switching | Unofficial gateway with credential/protocol risk; adapters already exist; switching mid-conversation invalidates the prompt cache |
| CI diff batching by domain | No current PR here is large enough; revisit if a ticket routinely exceeds ~75 files |
| Per-step test gates (RPI) | Per-ticket commits plus FAST/FULL already gate progress; per-step gates would slow chains without new coverage |
| Hard cap of 10 tasks per plan | The chain rule (“one large ticket”) bounds scope by effort rather than by an arbitrary count |

## Limits

- The named sources are community or vendor material; the added sources are first-party vendor docs and shipped products. None reports a controlled comparison with another workflow. UG's version- and model-specific claims were not independently verified, and some named model versions may not exist.
- First-party metrics (Anthropic review pass rates, Symphony defaults, Graphite customer stories) are unaudited and, for review, vendor-reported. GHW's 99%+ gate and 3–5× productivity claims are marketing and were not used.
- This review reads documents, specs, and templates; it did not run the added products.
- Adoption is not free: the search surfaced counter-evidence that AI-assisted teams can see lower throughput and stability (DORA 2025) and that reviewing AI code is often harder than reviewing a colleague's (Sonar survey, 1,149 developers). Neither was independently checked here, but both argue against treating agent volume as free.
- Dotfiles figures come from [workflow-architecture.md](workflow-architecture.md) and [workflow-telemetry.md](workflow-telemetry.md), which describe current behavior, not measured outcomes of adopting anything above.
- The additional-source catalog in [2026-11-27-agentic-workflow-comparison-sources.md](2026-11-27-agentic-workflow-comparison-sources.md) lists material for a later round, including sources cited by these three that were not analyzed here.

[UG]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/tree/f97e4f7b9cde282b339f2757442e18762e028ba2
[GHW]: https://github.com/alirezarezvani/claude-code-github-workflow/tree/d98f0eb1c5e9a41ec354f4fa6b2edf267d0c3a8d
[ORO]: https://github.com/OneRedOak/claude-code-workflows/tree/29a34c725313c7621f426f838ed31cf482473fb4
[LOCAL-arch]: workflow-architecture.md
[SYM]: https://github.com/openai/symphony/blob/v0.0.3/SPEC.md
[ANTH-REVIEW]: https://claude.dev/blog/solving-code-review-at-anthropic/
[CC-REVIEW]: https://code.claude.com/docs/en/code-review
[CC-AGENTS]: https://code.claude.com/docs/en/agent-view
[GH-HQ]: https://github.blog/news-insights/company-news/pick-your-agent-use-claude-and-codex-on-agent-hq/
[GH-MC]: https://github.blog/ai-and-ml/github-copilot/how-to-orchestrate-agents-using-mission-control
[OAI-HARNESS]: https://openai.com/index/harness-engineering
[CC-COST]: https://code.claude.com/docs/en/costs
[CC-EFFORT]: https://claude.com/blog/claude-model-and-effort-level-in-claude-code
[CC-CACHE]: https://claude.com/blog/lessons-from-building-claude-code-prompt-caching-is-everything
[OAI-LAT]: https://developers.openai.com/api/docs/guides/latency-optimization
[OAI-MODELS]: https://developers.openai.com/codex/models
[CR-TRIAGE]: https://docs.coderabbit.ai/triage/prioritization
[CC-REVIEWMD]: https://code.claude.com/docs/en/code-review-customize
[OAI-GHREVIEW]: https://developers.openai.com/codex/integrations/github
[GRAPHITE]: https://graphite.com/docs/best-practices-for-reviewing-stacks
[UG-plan-pipeline]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/plan-pipeline.md
[UG-plan-pipeline-adr]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/plan-pipeline.md#adr-learning-loop
[UG-plan-pipeline-context]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/plan-pipeline.md#context-management
[UG-rpi]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/rpi.md#how-the-gates-work
[UG-tasks]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/task-management.md
[UG-task-progress]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/task-management.md#the-continuity-artifact-progressmd
[UG-dual]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/dual-instance-planning.md#plan-template
[UG-context]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/core/context-engineering.md
[UG-dynamic]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/dynamic-workflows.md
[UG-dynamic-adv]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/dynamic-workflows.md#adversarial-verification
[UG-teams]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/agent-teams.md
[UG-codereview]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/code-review.md
[UG-multiprovider]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/multi-provider-code-review.md
[UG-bon]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/best-of-n.md#decision-rule
[UG-bon-evidence]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/best-of-n.md#evidence-boundary
[UG-notes]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/reviewable-agent-changes.md
[UG-notes-limit]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/reviewable-agent-changes.md#what-is-not-established
[GHW-arch]: https://github.com/alirezarezvani/claude-code-github-workflow/blob/d98f0eb1c5e9a41ec354f4fa6b2edf267d0c3a8d/docs/ARCHITECTURE.md
[GHW-scale]: https://github.com/alirezarezvani/claude-code-github-workflow/blob/d98f0eb1c5e9a41ec354f4fa6b2edf267d0c3a8d/docs/ARCHITECTURE.md#scalability-considerations
[GHW-commands]: https://github.com/alirezarezvani/claude-code-github-workflow/blob/d98f0eb1c5e9a41ec354f4fa6b2edf267d0c3a8d/docs/COMMANDS.md
[ORO-triage]: https://github.com/OneRedOak/claude-code-workflows/blob/29a34c725313c7621f426f838ed31cf482473fb4/guides/orchestration-layer/templates/review-triage.md
[ORO-skill]: https://github.com/OneRedOak/claude-code-workflows/blob/29a34c725313c7621f426f838ed31cf482473fb4/guides/orchestration-layer/templates/review-skill-example.md
[ORO-subagent]: https://github.com/OneRedOak/claude-code-workflows/blob/29a34c725313c7621f426f838ed31cf482473fb4/code-review/pragmatic-code-review-subagent.md
[ORO-design]: https://github.com/OneRedOak/claude-code-workflows/blob/29a34c725313c7621f426f838ed31cf482473fb4/design-review/README.md
