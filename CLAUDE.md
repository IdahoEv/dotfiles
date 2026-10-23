# dotfiles

Chezmoi source for Evan's machines. The repo is also the source of `~/.claude`, so editing it edits Claude's own config.

## Layout

| Path | Deploys to |
| --- | --- |
| `dot_claude/` | `~/.claude` (commands, skills, agents, hooks, settings, global CLAUDE.md) |
| `dot_*`, `*.tmpl` | `$HOME` dotfiles (templates branch on `is_work`) |
| `tools/` | Not deployed; `*.sh` are symlinked into `~/.local/bin` by `run_after_link-tools.sh.tmpl` and run in place from the deploy clone |
| `.claude/` | Project config, not deployed. Only `kickoff-preamble.md` is tracked; the rest (e.g. `governor.md`) is local and gitignored |
| `docs/`, `CLAUDE.md` | Not deployed |

## Two checkouts

- **Dev copy**: `~/Documents/Development/dotfiles` (bare repo). Ticket worktrees live here; all edits and commits happen in a worktree.
- **Deploy clone**: `~/.local/share/chezmoi`, main only. Never edit or commit there. Merged work reaches the machine by pulling it and running `chezmoi apply`.

`/workflow`'s "chezmoi source is the working copy" and "never commit the dotfiles repo" rules do not apply here; this repo is committed through ticket worktrees.

Create worktrees with `/start` or `wm`, not raw `git worktree add`. Changes go ticket → branch → PR. `/finalize` cleans up after merge.

## Trying a change before merge

```bash
chezmoi -S <worktree> diff ~/.claude/<path>     # read-only preview
chezmoi -S <worktree> apply ~/.claude/<path>    # writes to $HOME; diff first
```

Always name the target. A bare `apply` writes every managed file, reverting anything on main that this branch lacks.

Re-apply from the deploy clone after the merge to return to main's state.
