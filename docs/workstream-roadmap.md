# Workstream Workflow & Tmux Dashboard Roadmap

**Goal:** Evolve the ticket workflow (prompts, agents, skills, `.workstream.json`, scripts) and tmux dashboard into a **backend-agnostic agentic workflow** supporting `claude`, `agy`, and `codex` as peer backends—cleanly extractable from `dotfiles` into a standalone project.

> **Partly outdated.** [workstream-concept.md](workstream-concept.md) defines a workstream and replaces this roadmap wherever they disagree. Outdated here: reading `.workstream.json` directly as the contract (access goes through workstream commands); the Phase 2 session fields and distilled handoff (handoff is transcript only for now); and the Phase 3 poller and context bundle (herdr or a similar tool is evaluated first, and host moves come later).

## Architecture Boundary

- **Core contract:** `<worktree>/.workstream.json` + tmux window options (`@ws_backend`, `@ws_dashboard`, `@ws_phase`). In Phase 2, `.workstream.json` evolves `claude_sessions` into a provider-agnostic `sessions` list (`provider`, `id`, `log_path`, `context_dir`, `started_at`) for crash recovery and cross-provider handoff.
- **Dashboard isolation:** `agy_tmux_dashboard.py` (future `ws_tmux_dashboard.py`) depends only on tmux and `.workstream.json`—never on `start-ticket.sh`, `gh`, or a specific agent CLI. The one optional seam is `--mem-cmd`: any command printing the `mem-guard.sh report --json` shape adds a memory column, sampled on a background thread; without it the dashboard has no memory dependency.
- **Canonical core vs. adapters:** Long-term, prompts/commands/agents/skills move from `dot_claude/` into a neutral workflow core, with thin per-backend bindings for `~/.claude`, `~/.gemini`, and `~/.codex`.

## Phases

| Phase | Scope | Target |
| --- | --- | --- |
| **1. Local dashboard parity** | Per-project colors ([#187](https://github.com/IdahoEv/dotfiles/issues/187), done), group-by-project & group-by-state views ([#189](https://github.com/IdahoEv/dotfiles/issues/189), done), `.workstream.json` phase/PR tags ([#188](https://github.com/IdahoEv/dotfiles/issues/188)), auto-launch `/start` into active `agy-tmux` ([#198](https://github.com/IdahoEv/dotfiles/issues/198)) | `dotfiles` (`agy-tmux`) |
| **2. Backend-agnostic multiplexer** | Rename `agy-tmux` → `ws-tmux`; add `--backend claude\|agy\|codex` and `Backend` column; add `--launcher tmux` to `start-ticket.sh`; custom 256-color palette & `PR` column; record `sessions` in `.workstream.json` (`workstream.sh record-session`, wired per provider as shims join `ws-tmux`) + `resume-workstream` / dashboard `resume` for crash recovery and distilled handoff for provider switches | `dotfiles` (`ws-tmux`) |
| **3. Cross-machine dashboard** | Async SSH status poller (`Host` column) across laptop + desktop; `Enter` on remote row attaches via `ssh -t <host> tmux attach`; cross-machine handoff via `.workstream.json` + distilled context bundle | `ws-tmux` |
| **4. Standalone extraction** | Invert `dot_claude/` → neutral workflow core + per-backend installers; extract workflow + `ws-tmux` into its own repository; unify config into layered `config.yaml` under `.workstream/` ([design](workstream-config.md)) | Standalone repo |

Target repository layout, module boundaries and migration order: [workstream-code-layout.md](workstream-code-layout.md).
