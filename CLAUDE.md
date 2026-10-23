# dotfiles

Chezmoi source for Evan's machines. The repo is also the source of `~/.claude`, so editing it edits Claude's own config.

## Layout

| Path | Deploys to |
| --- | --- |
| `dot_claude/` | `~/.claude` (commands, skills, agents, hooks, settings, global CLAUDE.md) |
| `dot_*`, `*.tmpl` | `$HOME` dotfiles (templates branch on `is_work`) |
| `tools/` | Not deployed; run in place from the deploy clone via `PATH` |
| `.claude/` | This repo's own project config (governor context, kickoff preamble); not deployed |
| `docs/`, `CLAUDE.md` | Not deployed |

## Two checkouts

- **Dev copy**: `~/Documents/Development/dotfiles` (bare repo). Ticket worktrees live here; all edits and commits happen in a worktree.
- **Deploy clone**: `~/.local/share/chezmoi`, main only. Never edit or commit there. Merged work reaches the machine by pulling it and running `chezmoi apply`.

Create worktrees with `/start` or `wm`, not raw `git worktree add`. Changes go ticket → branch → PR. `/finalize` cleans up after merge.

## Trying a change before merge

```bash
chezmoi -S <worktree> diff     # read-only preview against $HOME
chezmoi -S <worktree> apply    # writes to $HOME; diff first
```

Re-apply from the deploy clone after the merge to return to main's state.
