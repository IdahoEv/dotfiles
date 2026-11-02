# Shell → Python spike (#54)

## Recommendation

**Convert, in stages, for reviewability.** The motivation is that the bash is not being read: the owner reviews Python and does not review shell, so the large scripts run on trust. Speed does not decide this. Measured startup is a non-issue off the hot path (Python adds roughly 5–20 ms to calls that already cost 7–40 ms and sit next to multi-second `gh` calls). Hot paths (statusline, per-event hooks) are judged separately below.

| Order | Script | Cost (points) | Why here |
| --- | --- | --- | --- |
| 1 | `lib/repo-facts.sh` → `lib/repo_facts.py` (+ CLI) | 3 | Every large script depends on it; porting it first lets each later port import instead of shell out |
| 2 | `finalize-check.sh` | 3 | Read-only, 12 `gh`/`jq` call sites, mostly JSON shaping; lowest-risk large port, proves the contract |
| 3 | `start-ticket.sh` | 3 | State machine plus provider plugins; `--print-title` is a cheap parity probe |
| 4 | `worktree-manager.sh` | 5 | Largest; interactive (fzf), `--init` is destructive. Split into modules only if one file exceeds review size |
| 5 | `open-pr.sh` (+ providers) | 2 | Same JSON/`gh` shape as step 2 |
| 6 | `lib/telemetry.sh` + `wf-event.sh` | 2 | Hot path; convert only after the prototype in "Hot paths" beats bash |
| — | everything else | — | See table; leave unless touched for another reason |

Total for steps 1–5: **16 points**, each its own PR. Step 4 is the real question and the real payoff: 1,182 lines, the least reviewable file, and the one a bug in could damage a checkout.

## Inventory

State: LOC from `wc -l` at the merge of `origin/main` (telemetry scripts included); timings below were taken at base `46e28e8`, before the later edits to `start-ticket.sh` and `wf-event.sh`, so those two rows are approximate. "Constrains" = whether the invocation surface limits the language.

| Script | LOC | Surface | Constrains? | Verdict | Effort |
| --- | --- | --- | --- | --- | --- |
| `worktree-manager.sh` | 1,182 | human CLI (`wm` alias); called by `start-ticket`, `workflow-session`, tighten, `wf-context` | No; stdout/exit parity needed | convert | 5 |
| `start-ticket.sh` | 563 | slash command (`/start`, `/discuss`, `/open-pr`), shell freshness module | No | convert | 3 |
| `finalize-check.sh` | 520 | slash command (`/finalize`); `sibling-worktrees` | No; stdout is parsed by the command | convert | 3 |
| `lib/repo-facts.sh` | 416 | sourced by 8 scripts and `wf-context` | **Yes** while any bash caller remains | convert (first) | 3 |
| `open-pr.sh` | 319 | slash command | No | convert | 2 |
| `agent-phase.sh` | 192 | slash commands, statusline reads its state file; already embeds a Python heredoc | No | convert (with `session-label`) | 1 |
| `sibling-worktrees.sh` | 161 | slash command, `finalize-check` | No | convert with `finalize-check` | 1 |
| `session-label.sh` | 149 | slash commands; embeds Python heredoc | No | convert (with `agent-phase`) | 1 |
| `workflow-session.sh` | 129 | human CLI (governor) | No | defer; below the readability pain line | 1 |
| `lib/telemetry.sh` | 89 | sourced by 5 scripts (`agent-phase`, `finalize-check`, `open-pr`, `start-ticket`, `wf-event`) | **Yes** while bash callers remain | convert with step 6 | 1 |
| `cloud-workflow-bootstrap.sh` | 98 | cloud-agent bootstrap; must run before anything is installed | **Yes**: runs on hosts where only `bash` is assured | keep bash | — |
| `request-review.sh` | 80 | slash command | No | defer (80 lines, readable) | 1 |
| `project-config.sh` | 73 | slash command (`/governor`); sourced by repo-facts | No | defer | 1 |
| `wf-event.sh` | 73 | **hook** (SessionStart/End, StopFailure, SubagentStop) and prompts | **Yes**: hot path | see "Hot paths" | 1 |
| `setup-ticket-profile.sh` | 45 | one-time human CLI | No | keep bash | — |
| `wf-report.sh` | 18 | human CLI; `exec`s `lib/wf_report.py` | No | keep (already a wrapper) | — |
| `lib/wf_report.py`, `wf_usage.py` | 547, 172 | Python already | — | — | — |
| `project-colors`, `session-kickoff.md`, `model-pricing.json`, templates, providers | data / <70 each | data or plugin fragments | Follows parent | follows parent | — |
| `dot_claude/executable_statusline.sh` (outside `tools/`) | 133 | **statusline**, every render | **Yes** | keep bash (see below) | — |
| `dot_claude/hooks/executable_no-cd-write.py` | 81 | **hook** (PreToolUse Bash) | Already Python | — | — |

Also bash outside `tools/` and out of scope: `skills/workflow/executable_wf-context.sh` (704), `github-review-poll.sh` (154), `github-review-state.sh` (88), `tighten-worktree.sh` (117), `prompt-metrics.sh` (65). `wf-context.sh` is larger than all but the top three here and is the next candidate if this works.

Test suites: `.test.sh` beside `open-pr`, `start-ticket`, `session-label`, `project-config`, `workflow-session`, `cloud-workflow-*`, `lib/repo-facts`, `lib/telemetry` (~1,350 lines); no suite for `worktree-manager.sh` or `finalize-check.sh`. Python precedent for tests: `lib/wf_report_test.py`, `skills/tighten/test_tighten.py`.

## Measurements (home)

Machine: macOS 15.6.1, arm64, bash 3.2.57 (`/bin/bash`), jq 1.7.1. Harness (`bench.py`, kept outside the repo): `import subprocess,sys,time,statistics as st; n=int(sys.argv[1]); t=[]; [(lambda s:(subprocess.run(sys.argv[3:],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL),t.append((time.perf_counter()-s)*1000)))(time.perf_counter()) for _ in range(n)]; t.sort(); print(st.median(t),t[0],t[int(.9*n)-1])`. Command line: `python3 bench.py <N> -- <cmd...>` (argv[2] ignored); N=40 unless noted. Stub = `python3 -c "import argparse, json, subprocess, pathlib, sys, shutil, re, os; argparse.ArgumentParser().parse_args([])"`. Work-machine timings were not taken; only its interpreter version and provenance are recorded (next sections), and the "both machines" gates below are open until they are.

### Interpreter and stub startup

| Command | Median ms | Min | p90 |
| --- | --- | --- | --- |
| `bash -c :` | 2.1 | 2.0 | 2.6 |
| `python3 -c pass` (pyenv shim → 3.13.5) | 8.6 | 8.3 | 8.9 |
| `python3 -I -S -c pass` | 7.1 | 6.7 | 7.4 |
| `~/.pyenv/versions/3.13.5/bin/python3 -c pass` | 8.8 | 8.1 | 9.8 |
| `/usr/bin/python3 -c pass` (3.9.6, Xcode CLT) | 15.5 | 14.9 | 17.0 |
| `/opt/homebrew/bin/python3 -c pass` (3.14.8) | 14.4 | 13.7 | 15.4 |
| stub, `python3` (shim) | 19.7 | 18.9 | 20.5 |
| stub, direct 3.13.5 | 19.5 | 18.9 | 20.3 |
| stub, `/usr/bin/python3` | 26.1 | 25.3 | 26.7 |

The pyenv shim adds no measurable cost here. The stub's imports (`argparse`, `subprocess`, `re`, `json`, …) cost about 11 ms over bare Python; `-S`/`-I` save about 1.5 ms. A Python port of any large script starts in **≈20 ms** (≈26 ms on the system interpreter).

### Entry points, bash vs stub

| Entry point | Command | Median ms | Min | p90 |
| --- | --- | --- | --- | --- |
| `worktree-manager.sh` | `--help` | 6.8 | 6.6 | 8.1 |
| `finalize-check.sh` | `--help` | 7.1 | 6.7 | 8.0 |
| `start-ticket.sh` | `--help` | 38.8 | 37.6 | 40.6 |
| Python stub | see above | 19.7 | 18.9 | 20.5 |

`--help` exits before the scripts source libraries or call `git`/`gh`, so the first two numbers are a floor, not a working cost. `start-ticket.sh` sources `repo-facts` and telemetry first, hence 39 ms. **Startup delta, Python vs bash: about +13 ms (`worktree-manager`, `finalize-check`) and −19 ms (`start-ticket`).** All are human-imperceptible against the work they front.

### End to end

| Run | Command | Median | Notes |
| --- | --- | --- | --- |
| `worktree-manager.sh` create worktree | `worktree-manager.sh bench-<i>` in a throwaway bare-layout repo, stdin `/dev/null`, worktree and branch removed after each run (n=10) | **146 ms** (min 140, max 156) | Local git only |
| `start-ticket.sh` | `start-ticket.sh 54 --print-title` (n=20) | **1,930 ms** (min 1,706, p90 2,503) | Dominated by the `gh` network call |

Python's ≈20 ms startup is 14% of the `worktree-manager` run and 1% of `start-ticket`. The `gh` call, not the interpreter, sets the time, so a port neither helps nor hurts there.

## Hot paths

| Caller | Today (median) | Verdict |
| --- | --- | --- |
| Statusline (`statusline.sh`, 133 LOC, fed a canned JSON payload) | **45.5 ms** | Keep bash. Its cost is forks: one `git rev-parse` (8.3 ms), one `git status` (11.8 ms), `jq` (2.5 ms), `awk`/`sed`. A Python version needs the same two `git` calls plus 8.6 ms startup, a floor of about 29 ms, below today's cost. The estimate omits the `awk`/`sed` replacement work and rests on startup that was 15.5 ms on the system interpreter, so it is not trusted. **Rejected until a working prototype measures under 45 ms on both machines.** Not blocking; revisit after step 6. |
| `no-cd-write.py` (PreToolUse, every Bash call) | 12.9 ms | Already Python; the cost the other hooks must beat. |
| `wf-event.sh --hook` (session start/end/fail, subagent stop) | 41.2 ms with telemetry on; 8.7 ms with `WF_TELEMETRY=0` | Fires on four low-frequency events, not per tool call. Forks `jq`, `perl` (twice) and two `git` calls. A Python port is estimated at 25 ms (8.6 start + two `git` calls) and drops the `jq`/`perl` dependency, so it would not regress. Step 6, gated on a measured prototype. |
| `agent-phase.sh` | not measured | Called by commands, not hooks or the statusline. Its embedded `python3` already costs the startup. |

No other script runs per tool call or per render.

## Interpreter availability

| | Home | Work |
| --- | --- | --- |
| `python3 --version` | 3.13.5 | 3.13.9 |
| Provenance | pyenv shim (`~/.pyenv/shims/python3`); also `/usr/bin/python3` 3.9.6 (Xcode CLT) and Homebrew 3.14.8 | pyenv shim → `~/.pyenv/versions/3.13.9/bin/python3`; also `/usr/bin/python3` 3.9.6 (Xcode CLT) |

Commands used: `python3 --version; command -v python3; python3 -c 'import sys; print(sys.executable)'; /usr/bin/python3 --version`.

Verdict on a deployed `python3` dependency: **safe on both machines.** Both resolve `python3` to a pyenv 3.13. **The floor is 3.13.** 3.14 adds nothing these scripts use and would force an upgrade on both machines. The system 3.9.6 (Xcode CLT, EOL) is deliberately not supported, so scripts can use `match`, `X | Y` unions and `tomllib` freely. `agent-phase.sh` and `session-label.sh` already guard with `command -v python3 || exit 0`, and `docs/platform-audit.md` flags `python3` as a previously accepted assumption. Do not depend on pyenv being on `PATH`: under a hook or cloud agent the shim may be absent, so the shebang is `#!/usr/bin/env python3` and each script exits with one install-hint line if the version is below 3.13.

## Porting contract

1. **Stdlib only, one entry file per command.** No venv, no pip. Shared code lives in `tools/lib/*.py`; entry scripts import it. Do not run entry points with `python3 -I` when they import siblings: it drops the script directory from `sys.path` and breaks the import (the existing `wf-report.sh` wrapper uses `-I` and puts `lib/` on the path itself). Python resolves the `~/.local/bin` symlink to the real directory, so `import repo_facts` works without path edits.
2. **Invocation surface unchanged.** Same file name and executable bit, so symlinks, `settings`, slash commands and the `wm` alias keep working. A `.sh` that becomes `.py` keeps a one-line `.sh` shim for one release (`exec python3 "$(dirname "$0")/x.py" "$@"`) so callers outside this repo don't break; remove it after callers are updated.
3. **Parity.** Identical exit codes and byte-identical stdout for every documented flag. stderr text may change. Each port's PR runs the old `.sh` and the new `.py` over the same fixtures and diffs output; those fixtures become the pytest cases.
4. **`repo-facts`: importable module plus a CLI.** `tools/lib/repo_facts.py` exposes functions; `repo-facts get <key>` prints one fact for the bash scripts still sourcing it. The sourced `repo-facts.sh` stays until its last bash consumer is gone (cost: each remaining caller pays ≈20 ms per call instead of a sourced function call). Same pattern for `telemetry`.
5. **Tests.** The existing `.test.sh` suites run unchanged against the new entry point as black-box parity tests during the port. Each port then adds pytest unit tests (fixtures with a temporary git repo; `gh` stubbed through a `PATH` shim, as the shell suites already do) and retires the `.test.sh` once pytest covers the same cases. `worktree-manager.sh` and `finalize-check.sh` have no suite today; **write the pytest cases before porting**, against the bash.
6. **Reviewable by design.** The point is that the owner can read the result. Small functions, type hints, `argparse`, `subprocess.run(..., check=False)` with explicit return-code handling, `pathlib`, no clever one-liners, no function over about 40 lines. A PR that is not readable fails review whatever the speed.
7. **Hot-path gate.** A script that runs on a hook or the statusline merges only with a before/after median from this doc's harness on home and work.

## Revisiting deferred and kept scripts

| Script | Stays bash because | Revisit when |
| --- | --- | --- |
| Statusline | 45.5 ms today; port unmeasured | A prototype measures under 45 ms on both machines |
| `wf-event.sh` | Hot path | Step 6 prototype beats 41 ms |
| `cloud-workflow-bootstrap.sh` | Runs before any dependency is installed | The cloud adapter can assume `python3` |
| `workflow-session.sh`, `request-review.sh`, `project-config.sh` | 70–130 lines, readable | One grows past about 200 lines, or is edited twice in a quarter |
| `setup-ticket-profile.sh`, `wf-report.sh` | One-time or a wrapper | Never expected |

## Method notes

Scratch files (`bench.py`, stubs, a throwaway bare-layout repo) lived in the job tmp directory outside the repo. Home numbers are single-machine and single-session; treat differences under about 2 ms as noise. Nothing under `tools/` changed.
