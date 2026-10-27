# Workflow & Review Architecture

State as of #40 and #46 (2026-10). **Keep this current:** any change to the dotfiles workflow — commands, agents, skills, hooks, or the scripts behind them — must check whether this document needs updating.

## Flow: where review happens

```
implement → commit → /local-code-review-cycle → /open-pr → bot review → /review-comments → /finalize
```

Local review runs **before** the PR, on committed local fixes; `/review-comments` handles findings **after** the PR opens. The implementer never reviews its own work — both paths use fresh, read-only agents.

```mermaid
flowchart TD
    U[You: work a ticket] --> IM[/implement + commit/]
    IM --> LCR[/local-code-review-cycle/]
    LCR --> Q1{Findings\nactionable?}
    Q1 -- yes --> FIX[Fix + commit round\nmax 5 rounds] --> LCR
    Q1 -- no --> FULL[Run FULL test suite]
    FULL --> OP[/open-pr/]
    OP --> BOTS[Copilot / CodeRabbit\nbot review]
    BOTS --> RC[/review-comments\nAutomatic / Quick / Slow/]
    RC --> Q2{Unresolved\ncomments remain?}
    Q2 -- yes --> REPFIX[Repair agent round\n→ commit → push → reply] --> RC
    Q2 -- no --> MERGE[Merge PR]
    MERGE --> FIN[/finalize/]
```

## Files and why each is an agent, command, or skill

| File | Kind | Why |
|---|---|---|
| `commands/local-code-review-cycle.md.tmpl` | Command (.tmpl) | User entry point; orchestrates the whole cycle. Machine-conditional via `is_work`. |
| `agents/{correctness,architecture,robustness,prompt}-reviewer.md` | Agent | Fresh, isolated context; read-only leaf reviewers. |
| `agents/review-repair-agent.md` | Agent | Fresh context with edit tools; never commits/pushes/writes to GitHub. |
| `skills/reviewer-contract/SKILL.md` | Skill | Shared contract loaded into every reviewer; avoids per-agent duplication. |
| `skills/review-comments-procedure/SKILL.md` | Skill | 3-mode procedure loaded by the command and repair agent; not user-invocable. |
| `commands/review-comments.md` | Command | Routes mode, launches agent, owns commits and GitHub writes. |
| `commands/prompt-audit.md` + `skills/prompt-review/` | Command + skill | Corpus-level prompt rubric; runs through `prompt-reviewer`. |
| `tools/wf-event.sh`, `tools/wf-report.sh`, `tools/lib/telemetry.sh` | Script | Telemetry: one event per triaged finding, one per cycle. |
| `tools/agent-phase.sh`, `review-state.sh` | Script | Statusline bookkeeping (`[REVIEW]` etc.); no review logic. |

## Patterns

1. **Risk-based selection.** Each reviewer's `description` ends with a `Use when:` clause; the orchestrator matches clauses against `git diff --name-only BASE...HEAD` and risk signals. Smallest set that covers the risks; no code reviewer on prompt-only diffs; deterministic issues go to formatter/linter/tests.
2. **Shrinking rounds.** Round 1 reviews `BASE...HEAD`; round k+1 reviews only round k's fix commits plus a correctness pass on touched files.
3. **Evidence bar + triage.** Findings need a credible failure path, test gap, or material design cost. Already-triaged findings pass forward; nothing is resurrected without new evidence.
4. **Gates and caps.** `DESIGN: unsound` halts before code changes; max 5 rounds; `FAST` per round, `FULL` once at finish; `--confirm-commits` (default on where `is_work`).
5. **Isolation of side effects.** Reviewers read-only; repair agent edits only; commands own commits and all GitHub writes. Planned GitHub replies are posted only after the parent pushes.
6. **Measured.** Every triaged finding → `wf-event.sh review.finding`; cycle end → `review.result`. `wf-report.sh` shows which reviewers earn their tokens.

## Commands: what to use when

| Situation | Command |
|---|---|
| Non-trivial change committed, pre-PR | `/local-code-review-cycle` (auto-invoked by CLAUDE.md after ticket implementation) |
| PR opened, bot comments arrived | `/review-comments` → Automatic (agent round), Quick (one agent turn), Slow (ask me per comment) |
| Review of the prompt corpus itself | `/prompt-audit`, `/prompt-review` |
| Merged | `/finalize` |

## Agent invocation sequence

```mermaid
sequenceDiagram
    participant Impl as Implementer session
    participant R as Reviewer agents
    participant Cmd as /review-comments
    participant RA as review-repair-agent
    participant GH as GitHub

    Note over Impl: implement + commit (FAST green)
    loop up to 5 rounds
        Impl->>R: launch selected reviewers in parallel<br/>(diff scope, ticket criteria, triaged list)
        R-->>Impl: findings (one line each, DESIGN gate)
        Impl->>Impl: triage → wf-event review.finding per finding
        Impl->>Impl: fix + FAST + commit round
        Note over Impl: round k+1 scope = round k fix commits only
    end
    Impl->>Impl: FULL once → wf-event review.result
    Impl->>Cmd: /open-pr (PR body carries review summary)
    Cmd->>GH: open PR
    GH-->>Cmd: bot review comments
    loop unresolved comments remain
        Cmd->>RA: launch one Automatic round<br/>(pinned repo, PR, cwd)
        RA->>RA: validate findings, apply high-confidence fixes
        RA-->>Cmd: report + planned replies + commit message
        Cmd->>Cmd: approval (AskUserQuestion)
        Cmd->>GH: commit → push → post replies → resolve threads
    end
```

## Ownership and output visibility

```mermaid
flowchart LR
    subgraph Parent[Implementer / orchestrator session]
        direction TB
        C1[Owns: edits, commits, telemetry events,<br/>PR body, AskUserQuestion approvals]
    end
    subgraph LeafReview[Leaf reviewers — read-only]
        L1[correctness-reviewer]
        L2[architecture-reviewer]
        L3[robustness-reviewer]
        L4[prompt-reviewer]
    end
    subgraph Repair[review-repair-agent — edits only]
        R1[Owns: working-tree edits,<br/>planned replies, proposed commit message]
    end
    Parent -->|launch: diff scope,<br/>criteria, triaged list| LeafReview
    LeafReview -->|findings only,<br/>no edits| Parent
    Parent -->|launch: pinned repo/PR/cwd| Repair
    Repair -->|report + planned actions,<br/>never commits/pushes/GitHub| Parent
    Parent -->|posts replies only<br/>after push| GitHub[GitHub PR]
    Contract[reviewer-contract skill<br/>preloaded into every reviewer] -.-> LeafReview
    Contract -.-> Repair
```

Key invariant: outputs always flow **up** to the parent, which owns every irreversible action (commit, push, GitHub write). Children never talk to each other or to GitHub.

## Machine- and project-specific extensions

- **Machine:** the cycle is a `.tmpl` branching on `is_work` (e.g. `--confirm-commits` default on at work). Machine behavior lives in templates and `is_*` data, never in agent bodies.
- **Project reviewers:** agent-format file ending in a `Use when:` clause, in the repo's `.claude/agents/` (precedence over global); reference it from the project's `CLAUDE.md`.
- **Personal, work-machine reviewers for shared repos:** `docs/local/reviewers/*.md` — globally gitignored, symlinked into every worktree by `wm`. No work content in dotfiles.
- **New reviewer:** follow `reviewer-contract`'s authoring convention and cite it from project docs; the orchestrator must never invent reviewers mid-cycle.
