# Governor context

**Project:** dotfiles — personal config, applied via chezmoi on home and work machines
**People:** Evan (sole contributor)
**Primary worktree:** the main checkout (first entry of `git worktree list`)

## Key documents
- GitHub issues on this repo — the tracker. **Repo is public: never put sensitive information in issues, PRs, or commits.**
- Issues filed from other repos by `/workflow` intake are triaged here with the rest. They may describe another project, so the public-repo rule applies to their evidence too.

## Repositories
- **dotfiles** (this repo) — source of truth
- **chezmoi checkout** (`~/.local/share/chezmoi`) — deploy clone; the only universal sibling. Other nearby repos are examined only when Evan says so.

## Adjacent systems
- **chezmoi** — applies this repo to each machine

## Standing responsibilities
- Keep dotfiles free of project- or repo-specific information, especially work repos.
- Keep them fast and efficient (shell startup, hooks, scripts).
- Where they contain Claude or other AI prompts, keep them terse and minimal-token.
- Changes must transfer and apply cleanly machine to machine (home and work); flag anything machine-specific.
- Tickets must not contain sensitive or work-identifying details.
