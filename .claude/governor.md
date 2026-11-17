# Governor context

**Project:** dotfiles — personal config, applied via chezmoi on home and work machines
**People:** Evan (sole contributor)
**Primary worktree:** the main checkout (first entry of `git worktree list`)

## Key documents
- GitHub issues on this repo — the tracker. **Repo is public: never put sensitive information in issues, PRs, or commits.**
- Intake issues filed from other repos by `/workflow` land in this tracker and are triaged with the rest; their evidence is subject to the public-repo rule above.
- `docs/workflow-architecture.md` — review/workflow architecture; must be checked for updates in any PR that changes the workflow.
- `docs/platform-audit.md` — cross-platform support audit.
- `docs/workflow-telemetry.md` — workflow telemetry design.
- `docs/cloud-workflow.md` — how cloud agents run the workflow commands.

## Repositories
- **dotfiles** (this repo) — source of truth
- **chezmoi checkout** (`~/.local/share/chezmoi`) — deploy clone; the only universal sibling. Other nearby repos are examined only when Evan says so.

## Adjacent systems
- **chezmoi** — applies this repo to each machine

## Issue labels
Goal: make the full workstream command set (`/governor`, `/groom`, `/pick` through `/local-review-cycle` and `/finalize`) work identically across every backend and location.

| Label | Meaning |
| --- | --- |
| `agy-parity` | Command support parity for `agy` agents (all Claude Code workflow commands, including `/finalize` and `/groom`) |
| `codex-parity` | Command support parity for Codex agents |
| `tmux-parity` | Tmux dashboard feature parity with Claude Code's agents view |
| `cloud-claude-parity` | All workflow commands available in Claude Code cloud sessions |
| `cloud-agy-parity` | All workflow commands available in Antigravity/Gemini cloud sessions |
| `cloud-codex-parity` | All workflow commands available in ChatGPT Codex cloud sessions |
| `workflow` | Improvements or consistency to the workflow itself (existing commands, new commands, efficiency, developer UI) |

## Standing responsibilities
- Keep dotfiles free of project- or repo-specific information, especially work repos.
- Keep them fast and efficient (shell startup, hooks, scripts).
- Where they contain Claude or other AI prompts, keep them terse and minimal-token.
- Changes must transfer and apply cleanly machine to machine (home and work); flag anything machine-specific.
- Tickets must not contain sensitive or work-identifying details.
