# `agy-tmux` — Parallel Workstreams & Tmux Guide

`agy-tmux.sh` launches one or more tickets/chains via `start-ticket.sh --no-tab`, starts an interactive `agy` session (`--mode plan`) in each worktree, and opens a live dashboard in tmux window `0`.

## Launching

From inside a repository:

```bash
agy-tmux.sh 12,13 14 15        # chain 12+13, plus tickets 14 and 15
agy-tmux.sh --session my-work 183
agy-tmux.sh --force 12 13       # launch even if mem-guard blocks on memory pressure
agy-tmux.sh                     # re-attach to an existing session
```

Before each group launches, `mem-guard.sh check` runs; under dangerous memory pressure that group is skipped (nothing is killed) unless `--force`. See `docs/memory-guard.md`.

## Dashboard & Switching

You land directly on **window `0` (dashboard)**:

| Key | Action |
| --- | --- |
| `↑` / `↓` or `j` / `k` | Select a workstream |
| `Enter` (or `1`–`9`) | Switch into that `agy` window |
| `Ctrl-z` *(inside any agent)* | Return to the dashboard (no prefix; scoped to `agy-tmux` sessions) |
| `r` | Force refresh |
| `x` | Close an `exited` workstream window |
| `q` | Detach from tmux (agents keep running in the background) |

The `Mem` column is an estimate of each window's process tree (`~1.2 GB`; `-` = not measured or exited), and the title line shows host memory pressure (`[WARN]`/`[BLOCK]` when thresholds are crossed). Details and limits: `docs/memory-guard.md`.

## Essential Tmux Keys

Tmux's **prefix** is `Ctrl-b` (press `Ctrl-b`, release, then press the next key):

| Action | Keys |
| --- | --- |
| Detach without stopping agents | `Ctrl-b` then `d` |
| List all windows with live preview | `Ctrl-b` then `w` (arrows + `Enter`) |
| Scroll back through `agy` output | `Ctrl-b` then `[` (arrows / `PgUp` / `PgDn`; `q` to exit scroll) |
| Close the current window | `Ctrl-b` then `&` (confirm `y`) |

## Re-attaching Later

```bash
tmux attach -t agy-<repo>
# or simply:
agy-tmux.sh
```

## Adding, Resuming, and Governor Windows

The dashboard and `mem-guard.sh` track every non-`0` window in `agy-<repo>`, including windows added manually.

- **Add a new workstream to a running session:**
  - From inside an `agy` window (e.g., `/governor`) in an `@agy_dashboard=1` session, `/start <id>` automatically routes to `start-ticket.sh --launcher agy-tmux` (`agy-tmux.sh --window`), appending the new workstream window without stealing focus.
  - From a shell:
    ```bash
    agy-tmux.sh <id>                # appends window to agy-<repo> and attaches
    agy-tmux.sh --no-attach <id>    # appends without attaching
    ```
- **Resume an orphaned workstream (after a crash/reboot):** `agy-tmux.sh <id>` reuses the existing worktree and commits without resetting them, but regenerates the original ticket kickoff (so tell the new session to inspect `git status`/`git log`/`gh pr view`). For workstreams already in review or ready for a PR, open a window with `/remind` instead once `agy-<repo>` exists:
  ```bash
  tmux new-window -t =agy-<repo>: -n <label> -c <worktree-path> "agy --mode plan --prompt-interactive '/remind'"
  ```
- **Run a governor session in the dashboard:**
  ```bash
  tmux new-window -t =agy-<repo>: -n governor -c <main-worktree-path> "agy --mode plan --prompt-interactive '/governor'"
  ```
