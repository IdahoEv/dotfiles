# `agy-tmux` — Parallel Workstreams & Tmux Guide

`agy-tmux.sh` launches one or more tickets/chains via `start-ticket.sh --no-tab`, starts an interactive `agy` session (`--mode plan`) in each worktree, and opens a live dashboard in tmux window `0`.

## Launching

From inside a repository:

```bash
agy-tmux.sh 12,13 14 15        # chain 12+13, plus tickets 14 and 15
agy-tmux.sh --session my-work 183
agy-tmux.sh                     # re-attach to an existing session
```

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
