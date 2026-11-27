# Agentic workflow sources for a second comparison round

Catalog of material not analyzed in [the first comparison](2026-11-27-agentic-workflow-comparison.md); sources already compared there are not repeated. Priority targets the dotfiles workflow's open questions: decision memory, context/cost budgets, model/effort routing, attention triage, and multi-host portability. Links were checked 2026-11-27; "not read" entries are leads, not summaries. "Mechanism" / "advice" / "counter-evidence" describes what the source appears to offer.

## Orchestration and multi-host workflow

| Source | What / why | Form | Surfaced by | Next-round question | Priority |
|---|---|---|---|---|---|
| [Claude Code platforms](https://code.claude.com/docs/en/platforms) / [cloud sessions](https://code.claude.com/docs/en/claude-code-on-the-web) / [mobile](https://code.claude.com/docs/en/mobile) | Same harness across CLI, desktop, IDE, browser, mobile; one-way cloud → terminal handoff | Mechanism + advice | Broad search | Host handoff constraints the adapters do not state | High |
| [HumanLayer 12-factor agents](https://github.com/humanlayer/12-factor-agents) | Ownership of context, state, control flow; source of the “dumb zone” claim | Advice | UG [context][UG-context] | Which factors map to command/agent/skill boundaries | High |
| [Liza](https://github.com/liza-mas/liza) | Coding control plane with role pairs, review quorum, checkpoint-latency and reviewer-accuracy gaps in its ledger | Mechanism | UG [observability][UG-obs] | Whether quorum and checkpoint telemetry fit the cycle manager | High |
| [Antigravity 2.0](https://antigravity.google/docs/projects), [subagents](https://antigravity.google/docs/subagents), [how agents work](https://antigravity.google/docs/learn/how-agents-work) | Per-launch local vs worktree mode; subagents `inherit`/`branch`/`share`; `/swarm`, `/teamwork` reviewer roles | Mechanism (churning) | Broad search | Per-launch isolation and named review roles for the Gemini adapter | Medium-high |
| [Vibe Kanban `v0.1.46`](https://github.com/BloopAI/vibe-kanban/tree/v0.1.46.1794744340) | Local kanban with branch/worktree/terminal per agent, inline diff comments routed back | Mechanism (community-maintained) | Broad search | Workspace-as-unit vs session-as-unit | Medium |
| [Orchestrator.inc `v0.15.6`](https://github.com/OrchestratorInc/agent-orchestrator/tree/v0.15.6) | Desktop/mobile/cloud supervisor with Working / Needs you / In review / Ready lanes and feedback routing | Mechanism (young) | Broad search | Lane definitions for the attention queue | Medium |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api) | Explicit state, checkpoints, replay, human-in-the-loop interruption | Mechanism | UG observability | Durable state vs file-based state for long chains | Medium |
| [Beads](https://github.com/steveyegge/beads) | Issue tracker built for agents, with dependency graphs | Mechanism | UG [task management][UG-tasks] | Whether dependency graphs should drive chains | Medium |
| [Spec Kit](https://github.com/github/spec-kit) | Spec-driven development commands and artifacts | Mechanism | General knowledge | Whether specs fill the plan/handoff gap | Medium |
| [OpenCode](https://github.com/sst/opencode) / [Codex CLI](https://github.com/openai/codex) / [Gemini CLI](https://github.com/google-gemini/gemini-cli) | Agent CLIs already supported or adjacent; session/thread state differs per host | Mechanism | UG ecosystem; dotfiles adapters | Status sources for the attention queue | Medium |
| [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) | Role-based workflow with document handoffs (analyst → PM → architect → dev → QA) | Advice + templates | General knowledge | Role handoffs vs fresh-context reviewers | Low |
| [Superpowers](https://github.com/obra/superpowers) | Skill collection for planning, TDD, debugging, review | Mechanism | General knowledge | Procedures worth borrowing at skill level | Low |

## Review cycles, prompts, and specialists

| Source | What / why | Form | Surfaced by | Next-round question | Priority |
|---|---|---|---|---|---|
| [claude-code-action](https://github.com/anthropics/claude-code-action) | Official GitHub Action behind GHW and ORO review workflows | Mechanism | GHW, ORO, UG | Permission model for review-only use here | High |
| [claude-code-security-review](https://github.com/anthropics/claude-code-security-review) | Anthropic security-review command and Action | Mechanism | ORO [security][ORO-security] | Marginal value over the existing security rubric | High |
| [CodeRabbit](https://docs.coderabbit.ai) | Commercial PR reviewer with configurable checks and path filters | Mechanism | UG, ORO | Marginal value vs Copilot and local reviewers; rule drift | High |
| [Codex app review](https://developers.openai.com/codex/app/review) / [GitHub review](https://developers.openai.com/codex/integrations/github) | PR inbox; `@codex review`; P0/P1-only posting; directory-scoped review rules (beyond the policy mechanism already compared) | Mechanism | Broad search | Severity floor and scoped rules as a test | High |
| [PR-Agent](https://github.com/qodo-ai/pr-agent) | Open-source review/describe/improve agent | Mechanism | General knowledge | Self-hosted review role and cost | Medium |
| [Greptile](https://www.greptile.com) | Cross-file/RAG reviewer | Mechanism | UG | Whether cross-file invariants are a real gap | Medium |
| [GitLab Duo Code Review Flow](https://docs.gitlab.com/user/duo_agent_platform/flows/foundational_flows/code_review/) | Native merge-request review with pre-scan and thread reuse | Mechanism | UG [multi-provider][UG-multi] | Non-GitHub parity for the review loop | Medium |
| [Uber uReview](https://www.youtube.com/watch?v=EL123UNokkI) | Production review with separate single-file and multi-file reviewers | Talk | UG multi-provider | Reviewer decomposition by file scope | Medium |
| [diffo](https://github.com/DiffoHQ/diffo) | Diff surface with typed reviewer threads (Change vs Question) | Mechanism | UG [reviewable changes][UG-notes] | Typed feedback for the repair agent | Medium |
| [glassbox](https://github.com/brianwestphal/glassbox) | Rationale stored as SARIF, re-anchored by snippet | Mechanism | UG reviewable changes | Rationale storage without stale anchors | Low |
| [hunk](https://github.com/modem-dev/hunk) / [drift](https://github.com/tothalex/drift) / [guidedreview](https://github.com/nshntarora/guidedreview) | Terminal/sidecar review, forge discussion reader, hunk grouping | Mechanism | UG reviewable changes | Local human review surface | Low |
| [ai-pr-review](https://github.com/houshuang/ai-pr-review) | Model-written PR walkthrough | Mechanism | UG reviewable changes | Security caveat: runs untrusted PR code | Low |
| [Reviewable](https://reviewable.io) | Review queue and diff discussion | Mechanism | General knowledge | Queue ordering lessons | Low |

## Token spend and cost measurement

| Source | What / why | Form | Surfaced by | Next-round question | Priority |
|---|---|---|---|---|---|
| [OpenTelemetry GenAI attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) | Standard agent/model/tool/token telemetry fields | Spec | UG observability | Whether `wf-event.sh` should emit OTel-compatible fields | High |
| [FinOps Foundation framework](https://www.finops.org/framework/phases/) | Inform/Optimize/Operate loop | Advice | UG [AI FinOps][UG-finops] | Cost-per-accepted-task on merged-ticket medians | High |
| [AWS Well-Architected Agentic AI Lens](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/cost-optimization.html) | Audit checklist for per-agent budgets, attribution, concurrency, latency | Advice | Broad search | Missing budgets and attribution in the current telemetry | High |
| [ccusage](https://github.com/ryoppippi/ccusage) | Local Claude Code token/cost reports | Mechanism | General knowledge | Cross-check `wf-report.sh --usage` | Medium |
| [Claude Code Usage Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) | Live usage/limit dashboard | Mechanism | General knowledge | Whether limit proximity should gate launches | Medium |
| [LiteLLM](https://github.com/BerriAI/litellm) | Gateway with budgets, virtual keys, allowlists | Mechanism | UG [API gateway][UG-finops] | Hard caps for unattended sessions | Medium |
| [Claude Code Router `v3.1.6`](https://github.com/musistudio/claude-code-router/tree/v3.1.6) | Local routing, fallbacks, credential pools, per-request logs | Mechanism (unofficial) | Broad search | Where routing/budget enforcement could live | Medium |
| [Langfuse](https://github.com/langfuse/langfuse) / [Helicone](https://github.com/Helicone/helicone) | LLM observability and cost tracing | Mechanism | General knowledge | Whether local JSONL is enough | Low |
| [OpenRouter](https://openrouter.ai) | Multi-provider routing and pricing | Mechanism | General knowledge | Provider portability and price comparison | Low |

## Response time and evaluation

| Source | What / why | Form | Surfaced by | Next-round question | Priority |
|---|---|---|---|---|---|
| [SWE-bench](https://www.swebench.com) / [Terminal-Bench](https://www.tbench.ai) | Agent evaluations with harness, model, and time budgets | Benchmark | General knowledge | Which benchmark predicts this workflow | Medium |
| [Artificial Analysis](https://artificialanalysis.ai) | Model latency/price/capability comparisons | Benchmark | General knowledge | Input to routing | Medium |
| [Aider leaderboards](https://aider.chat/docs/leaderboards/) | Task-level coding benchmarks with edit-format effects | Benchmark | General knowledge | Edit format vs review/fix latency | Low |
| [vLLM](https://github.com/vllm-project/vllm) / [SGLang](https://github.com/sgl-project/sglang) | Serving stacks for throughput and latency | Mechanism | General knowledge | Only for self-hosted inference | Low |
| [Groq](https://groq.com) / [Cerebras](https://www.cerebras.ai) | Fast-inference providers | Mechanism | General knowledge | Whether latency-critical roles need another provider | Low |

## Model selection and effort

| Source | What / why | Form | Surfaced by | Next-round question | Priority |
|---|---|---|---|---|---|
| [RouteLLM](https://github.com/lm-sys/RouteLLM) | Learned routing between strong and weak models | Mechanism | General knowledge | Risk-based routing vs fixed per-reviewer models | High |
| [FrugalGPT](https://arxiv.org/abs/2305.05176) | Model cascades with cost/quality trade-offs | Research | General knowledge | Cascade design for review escalation | Medium |
| [Martian](https://withmartian.com) / [NotDiamond](https://www.notdiamond.ai) | Commercial model routers | Mechanism | General knowledge | Vendor claims vs local measurement | Low |
| [Anthropic model config](https://code.claude.com/docs/en/model-config) | Per-session model/effort controls and defaults | Mechanism | Broad search | Which reviewer roles merit higher effort | High |

## Human attention and review comprehension

| Source | What / why | Form | Surfaced by | Next-round question | Priority |
|---|---|---|---|---|---|
| [Resisting Cognitive Surrender](https://knlb.dev/essays/surrender) | Reviewing machine output as a distinct mode; diff plus commentary plus reviewer column | Essay | UG [reviewable changes][UG-notes] | Whether an attention queue needs explanation beside the diff | High |
| [Anthropic 2026 Agentic Coding Trends Report](https://resources.anthropic.com/hubfs/2026%20Agentic%20Coding%20Trends%20Report.pdf) | Adoption, delegation, and oversight data cited by UG | Vendor report | UG [agent teams][UG-teams] | Evidence quality for attention/oversight claims | Medium |
| [Addy Osmani on agent teams](https://addyosmani.com/blog/claude-code-agent-teams/) | Independent read of coordination and context isolation | Essay | UG agent teams | Whether coordination-overhead data generalizes | Medium |
| [Devin](https://devin.ai) / [Factory](https://factory.ai) / [Cursor](https://cursor.com) | Commercial session dashboards and task queues | Mechanism | General knowledge | How they rank sessions needing a human | Medium |
| [GitHub notifications](https://docs.github.com/en/subscriptions-and-notifications) | Native review/notification queue | Mechanism | General knowledge | Baseline the attention queue should beat | Low |

## Counter-evidence and measurement quality

| Source | What / why | Form | Surfaced by | Next-round question | Priority |
|---|---|---|---|---|---|
| DORA 2025 report | Associates a 25% AI-adoption increase with ~1.5% lower throughput and ~7.2% lower stability | Research (reported) | Broad search | Whether these effects appear in local telemetry | High |
| Sonar developer survey (1,149 developers) | 38% say reviewing AI code takes more effort than a colleague's | Survey (reported) | Broad search | Measure review time per AI-written diff here | High |

Neither was independently verified for this round. Treat their numbers as hypotheses, not baselines, and pair any adoption with a before/after measurement from `wf-report.sh`.

[UG-context]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/core/context-engineering.md
[UG-tasks]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/task-management.md
[UG-obs]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/ops/observability.md
[UG-multi]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/multi-provider-code-review.md
[UG-notes]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/reviewable-agent-changes.md
[UG-finops]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/ops/ai-finops.md
[UG-teams]: https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/f97e4f7b9cde282b339f2757442e18762e028ba2/guide/workflows/agent-teams.md
[ORO-security]: https://github.com/OneRedOak/claude-code-workflows/blob/29a34c725313c7621f426f838ed31cf482473fb4/security-review/README.md
