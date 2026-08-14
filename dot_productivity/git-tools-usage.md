# git-tools / worktree-manager usage

Source: `~/Documents/Development/git-tools/worktree-manager.sh`

## One-time per repo

```
cd path/to/repo        # must be at repo root, clean working tree
wm --init
```

Converts a normal clone into a bare `.git` + per-branch worktree layout: `repo/main/`, `repo/<branch>/`, etc. Prints the `cd` command you need afterward (your shell is left in the old, now-gone directory).

## Day to day

From anywhere inside a converted repo (aliases from `.shell_modules/worktree-manager`):

| Alias | Effect |
|---|---|
| `wm` | Interactive `fzf` picker over existing worktrees + local + remote branches |
| `wm <branch>` | Create (or jump to, if it exists) a worktree for `<branch>` |
| `wms <ticket-id>` | Create a worktree from a Shortcut ticket — fetches the branch name via the `short` CLI, saves ticket details into `.ticket.local.md` in the new worktree |
| `wmc` / `wmc <branch>` | Same as `wm`, plus launches `claude` in the new worktree afterward |
| `wmsc <ticket-id>` | Shortcut-driven + opens Claude |

On creation it auto-symlinks untracked config from the main worktree (`.env*`, untracked `.claude/`, `docs/local/`) into the new worktree, and runs `npm`/`yarn`/`pnpm install` if it finds a lockfile.

Requires `fzf` for interactive mode and the `short` CLI for `--sc`.
