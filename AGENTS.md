# dotfiles

Chezmoi source for Evan's machines. The repo is also the source of `~/.Codex`, so editing it edits Codex's own config.

## Layout

| Path | Deploys to |
| --- | --- |
| `dot_claude/` | `~/.Codex` (commands, skills, agents, hooks, settings, global AGENTS.md) |
| `dot_*`, `*.tmpl` | `$HOME` dotfiles (templates branch on `is_work`) |
| `tools/` | Not deployed; `*.sh` are symlinked into `~/.local/bin` by `run_after_link-tools.sh` and run in place from the deploy clone |
| `.Codex/` | Project config, not deployed. `kickoff-preamble.md` and `governor.md` are tracked; the rest is local and gitignored |
| `workflow/` | Not deployed; per-host adapters that let non-Codex cloud agents run the commands (see `docs/cloud-workflow.md`) |
| `docs/`, `AGENTS.md` | Not deployed |

## Two checkouts

- **Dev copy**: `~/Documents/Development/dotfiles` (bare repo). Ticket worktrees live here; all edits and commits happen in a worktree.
- **Deploy clone**: `~/.local/share/chezmoi`, main only. Never edit or commit there. Merged work reaches the machine by pulling it and running `chezmoi apply`.

Create worktrees with `/start` or `wm`, not raw `git worktree add`. Changes go ticket → branch → PR. `/finalize` cleans up after merge.

Delivery mechanics — source naming, `chezmoi -S <worktree> diff|apply`, the merge/pull/apply flow — are in `/workflow`'s `delivery.md`.

`docs/workflow-architecture.md` documents the review/workflow architecture. Any change to the workflow — commands, agents, skills, hooks, or the scripts behind them — must check whether that document needs updating in the same PR.
