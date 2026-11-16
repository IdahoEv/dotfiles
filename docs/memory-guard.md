# Memory monitoring and launch guard

Running several `agy`, `claude` and `codex` sessions at once can exhaust a Mac's memory. `mem-guard.sh` attributes memory to sessions, shows the host's memory pressure, and refuses to *launch more work* while pressure is dangerous. It never kills a session or discards work.

```bash
mem-guard.sh report                     # every agent session on the machine, plus host pressure
mem-guard.sh report --session agy-foo   # also label tmux windows of an agy-tmux session
mem-guard.sh report --json              # same data, machine-readable
mem-guard.sh check [--force] [--quiet]  # the guard: exit 0 = go, exit 3 = blocked
```

The `agy-tmux` dashboard shows the same figures: a `Mem` column per window and the host pressure line in the title. It gets them from `mem-guard.sh report --json` through an optional `--mem-cmd` provider that `agy-tmux.sh` passes, sampled on a background thread every ~10 s; the dashboard itself never imports or depends on the measurement code.

## What is measured

| Signal | Source | Used for |
| --- | --- | --- |
| **Host pressure** | macOS: `sysctl kern.memorystatus_vm_pressure_level` (1 normal, 2 warn, 4 critical — the kernel's own verdict) plus the free-memory percentage from `memory_pressure`. Linux: `MemAvailable / MemTotal` from `/proc/meminfo` (no OS level). | **Warning and blocking decisions.** |
| **Per-session memory** | One `ps -axo pid=,ppid=,rss=,comm=` snapshot; RSS summed over the session's process tree. | Attribution and per-session *warnings* only. Never blocks. |

### Why the per-session figures are estimates

- RSS counts a shared page once in every process that maps it, so a tree of node/python subprocesses **over-counts**.
- macOS compressed and swapped pages are not in RSS, so under pressure it **under-counts** — exactly when it matters most.
- Figures are rounded and prefixed with `~` (`~340 MB`, `~1.4 GB`). Trust the host pressure line over them.
- `footprint`/`vmmap` give better per-process numbers on macOS but cost seconds per process and need permissions; they are not used. Follow-up if the estimate proves too coarse.

### No double counting

Each process belongs to exactly one session: its **nearest root ancestor**. Subagents, nested CLIs and tool subprocesses are inside their parent's tree. If a managed root sits inside another root, the inner one claims its own subtree and the outer one gets the rest. Parent cycles and processes that exit between samples are tolerated; a root that is gone shows as `exited` with no figure (not `0`).

## Coverage

| Path | Attributed as | Notes |
| --- | --- | --- |
| `agy-tmux.sh` windows | One row per tmux window (workstream key). | Window 0 (the dashboard) is excluded. Exited panes are listed as `exited`. |
| `claude` / `agy` / `codex` started anywhere else (iTerm tab from `start-ticket.sh`, `claude --bg`, a plain terminal) | Found by **executable name**; matched to a workstream when the process's working directory (via one `lsof` call) is inside a worktree with `.workstream.json`, otherwise listed as `claude pid 1234 [dir] *`. | The `*` marks "started outside the launcher". |
| The Claude **desktop app** (`Claude.app` bundles and helpers) and any `.app` bundle | **Not counted** as agent sessions; they still lower free memory and show in host pressure. |
| Agents under a different executable name (e.g. a Node wrapper that shows as `node`) | **Not detected.** | Add the name: `mem_agent_names=claude,agy,codex,mytool` (or `MEM_GUARD_AGENT_NAMES`). Sessions that run inside a counted agent are included regardless. |
| Memory used by non-agent processes (browsers, Docker, IDEs) | Not attributed. | They still lower free memory, so the host pressure line and the guard see them. |

`claude --bg` sessions are daemon-managed and appear as ordinary processes; inspect them with `mem-guard.sh report` or `claude agents`.

**Launch paths guarded** (all call `mem-guard.sh check`):

| Launch path | Behaviour when blocked |
| --- | --- |
| `start-ticket.sh <id>` (full launch) | Dies before any worktree or tracker write. |
| `start-ticket.sh --no-tab` (`/start` step 1, `agy-tmux.sh`) | Not guarded: it launches nothing. The later `--tab-only` call is the gate for `/start` (it can die after the worktree and in-progress mark exist; retrying reuses the worktree), and `agy-tmux.sh` guards each group itself. |
| `start-ticket.sh --tab-only` (iTerm and `bg` launchers, `/start` step 3), `--session` (`/discuss`) | Dies before the session starts. |
| `agy-tmux.sh <groups…>` | Each group is checked separately; blocked groups are skipped, others still launch if pressure allows. `--force` overrides. |
| `launcher=none`, `--print-title`, cloud `--in-place` runs | Not guarded: nothing is launched locally. |
| Codex | **No launcher in this repo**, so no launch guard. Inspect Codex sessions with `mem-guard.sh report`; the guard still counts them in host pressure. |
| Sessions you start by typing `claude`, `agy` or `codex` yourself | Not guarded (nothing intercepts them). Run `mem-guard.sh check` first, or `mem-guard.sh report` to see what is running. |

## Thresholds and overrides

All settings resolve `env > project > machine > user conf > default`, via the same `.start-ticket.conf` layers as other workflow settings (`key=value`). Env var is `MEM_GUARD_<NAME>` upper-cased.

| Conf key | Default | Effect |
| --- | --- | --- |
| `mem_warn_free_pct` | `20` | Free memory below this → warn, launch continues. |
| `mem_block_free_pct` | `8` | Free memory at or below this → **block**. macOS level `critical` also blocks; `warn` warns. |
| `mem_session_warn_mb` | `4096` | A session's estimate above this → warn (never blocks). `0` disables. |
| `mem_agents_warn_mb` | `0` (off) | All agent sessions together above this → warn. |
| `mem_fail` | `open` | Host pressure unreadable: `open` warns and launches; `closed` blocks. |
| `mem_agent_names` | `claude,agy,codex` | Executable names treated as agents (basename, or `<name>/versions/<file>` for native installs). A directory merely named like an agent does not match. |
| `mem_enabled` | `on` | `off` disables the guard entirely (report still works). |

**Override a block** (explicit, per launch): `agy-tmux.sh --force …`, `mem-guard.sh check --force`, or `MEM_GUARD_OVERRIDE=1 start-ticket.sh …`. An override is announced on stderr. `agy-tmux.sh --force` scopes the override to its own guard checks and the `start-ticket.sh` it calls; it is removed from the environment before tmux starts, so agent panes and any `/start` they run do not inherit it. A block prints the largest sessions and says nothing was killed. Agents running `/start` must **not** set the override themselves: report the block and let the user decide.

### Failure behaviour

| Situation | Result |
| --- | --- |
| Host pressure unreadable (sysctl missing, unsupported OS), or the macOS pressure level unreadable while free % is still available | Free % is still judged against the thresholds; if nothing trips, warn and launch (`mem_fail=open`) or block (`closed`). `--force` always wins. Linux has no OS level by design (`n/a`) and is judged on free % alone. |
| `ps` fails | Per-session figures omitted; host pressure still decides. Reported as "process table unreadable". |
| `lsof`/`tmux` missing or failing | Sessions fall back to name-only matching / no tmux labels. `lsof` exiting 1 because one pid vanished still yields the cwds of the others. |
| `mem-guard.sh` missing or crashes (exit other than 0/3) | `start-ticket.sh` and `agy-tmux.sh` both warn explicitly and launch. The guard is a safeguard, not a gate on a broken install. |
| Invalid threshold value (non-numeric, negative, `nan`, `inf`) | Ignored with a message; the default is used. |

## Privacy and overhead

- Only the executable name from `ps comm=` is read — never command-line arguments, so prompts, tokens and flags cannot reach the output. Labels are workstream keys, pids and the working directory's basename.
- Cost: one `ps`, one `sysctl`, one `memory_pressure` (macOS), and one `lsof` only when agents exist outside the managed tmux session. The dashboard samples at most every 10 s even though it redraws every 2 s.

## Validation status

Unit and integration tests (`tools/lib/mem_guard_test.py`, `tools/mem-guard.test.sh`, plus launch-path cases in `start-ticket.test.sh` and `agy-tmux.test.sh`) run on Linux with fixtures for host pressure. The macOS reading was **not validated on a real Mac** when this was written. Check on a Mac before relying on it:

1. `sysctl -n kern.memorystatus_vm_pressure_level` prints `1`, `2` or `4`.
2. `memory_pressure | grep 'free percentage'` prints a percentage (the guard treats a missing line as "free % unknown", not an error).
3. `mem-guard.sh report` lists a running `claude`/`agy`/`codex`; if a native-installer `claude` shows its version number instead of `claude`, the install path is not matched by `mem_agent_names` and needs adding.
4. Force a block without real pressure: `MEM_GUARD_HOST_FIXTURE='level=critical free_pct=3' mem-guard.sh check` (a test hook, as is `MEM_GUARD_PS_FIXTURE`).
