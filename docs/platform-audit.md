# Platform assumption audit — #12

Repo sweep (2026-10-26, branch `12-audit-dotfiles-for-platform-assumptions`). Windows scope, per #12: **both native PowerShell and WSL are first-class targets.** No `.chezmoi.os` template branching exists anywhere; `.is_work` is the only branch (machine role). WSL columns ≈ Linux except where noted (Windows-side clipboard/terminal, `wslpath`).

**Headline findings:**
- ~24 hard-coded `/Users/evan` paths — breaks Linux, WSL, and any other username on macOS. Prereq for everything else.
- Linux/WSL: 90% works. Breakers: iTerm/osascript/pbcopy coupling in tools, `~/Library` writes, the `/Users/evan` paths, one broken `readlink -f` fallback.
- Native PowerShell: 100% of scripts, hooks, statusline, and shell modules fail — all POSIX shell; zero PowerShell variants exist. Symlink/exec-bit tool delivery (`run_after_link-tools.sh`) has no Windows mechanism.

OS key: **L** = Linux, **W** = WSL, **PS** = native PowerShell. "L" without W means WSL inherits the same fix.

## Shell config

| File | Assumption | Breaks on | Proposed fix |
| --- | --- | --- | --- |
| `dot_zshrc.tmpl:1` | `/opt/homebrew/bin/brew` (Apple-Silicon brew path) | L, PS | Template on `.chezmoi.os`; guard with `command -v brew` |
| `dot_zshrc.tmpl:5` | `/usr/libexec/path_helper` | L, PS | Guard: `[[ -x /usr/libexec/path_helper ]] && eval "$(...)"` |
| `dot_zshrc.tmpl:16` | Literal `/Users/evan/.local/bin` (redundant with `$HOME` on L4) | L, PS | Fixed in #65 — duplicate line deleted |
| `dot_shell_modules/directories:1` | `DEV=/Users/evan/Documents/Development` | L, PS | Fixed in #65 — `$HOME/Documents/Development` |
| `dot_shell_modules/development:1–2` | `export DEV="~/Documents/…"` — quoted tilde never expands (bug); duplicates `directories` | all | Fixed in #65 — merged into `directories`, module deleted |
| `dot_shell_modules/zz-fzf:9–10` | `source $(brew --prefix)/opt/fzf/...` — Homebrew layout only | L, PS | Per-OS completion paths (Linux: `/usr/share/doc/fzf/examples/`); guard |
| `dot_shell_modules/zz-fzf:4`, `git-fzf.sh:25`, `git:41,251`, `chezmoi:1`, `direnv:4` | `brew install …` hints | L, PS | Per-OS hint (apt/dnf/winget) or drop to "install X" |
| `dot_shell_modules/git-fzf.sh:198` | `readlink -f` with a `/usr/bin/ruby` macOS fallback that's absent on Linux | L | Portable `realpath`/loop fallback (see `agent-phase.sh` pattern) |
| `dot_shell_modules/git-fzf.sh:147–164` | — | — | Already handles `open`/`start`/`xdg-open`/`powershell.exe` via `$OSTYPE`; the model to copy |
| `dot_shell_modules/git-tools-freshness:17` | `stat -f %m` BSD / `stat -c %Y` GNU | — | Already dual-handled; correct pattern |
| `dot_shell_modules/00-utils:44` | `~/.ssh/id_*` glob errors in zsh when no match | all | `(N)` qualifier or null_glob |
| `dot_config/iterm2/symlink_AppSupport` | Hard-coded `/Users/evan/Library/Application Support/iTerm2` | L, PS, macOS-other-user | Home dir templated in #65 (`symlink_AppSupport.tmpl`); per-OS ignore still open (sub-issue 3) |
| All zsh modules (`claude.tmpl`, `chezmoi`, `git-tools-freshness`, `git-fzf.sh`) | `compdef`, `${1:A}`, `${(f)}`, `$~pattern`, `(N)`, `setopt`, `print -P`, `&!` | PS | Not portable command-by-command — requires a PS profile rewrite (sub-issue 4) |

## tools/

| File | Assumption | Breaks on | Proposed fix |
| --- | --- | --- | --- |
| `tools/start-ticket.sh:219,227–280` | `osascript` AppleScript controlling iTerm2 | L, W, PS | Terminal abstraction layer: iTerm (macOS) / `wt.exe` (Windows) / print-instructions fallback (exists) |
| `tools/start-ticket.sh:212,256` | `pbcopy` | L, W, PS | `command -v pbcopy \|\| xclip/wl-copy/clip.exe` fallback |
| `tools/setup-ticket-profile.sh:5,15,40` | Writes `~/Library/Application Support/iTerm2/DynamicProfiles` | L, W, PS | Guard on macOS + iTerm presence; no-op elsewhere |
| `tools/worktree-manager.sh:425,546` | `brew install short/fzf` hints | L, PS | Per-OS hints |
| `tools/open-pr.sh:122`, `request-review.sh:44` | `gh` hard requirement | PS | gh is cross-platform; works in PS once the wrapper is PS |
| `request-review.sh:64`, `finalize-check.sh:165–202`, `wf-event.sh:25–29` | `gh --jq` / `jq` | PS | Native PS: `ConvertFrom-Json`; keep jq on POSIX |
| all `tools/*.sh` | `#!/usr/bin/env bash`, `set -euo pipefail`, `sed -n` help extraction, symlink-resolution `readlink` loops, git worktrees | PS | `*.ps1` siblings per script (sub-issue 6) |
| `run_after_link-tools.sh` | `ln -sfn` symlinks + exec bits into `~/.local/bin` | PS | Windows: copy/shim strategy (`run_after_` PS script, or winget-style shim dir on PATH) |
| `tools/*.test.sh` | bash + jq + fake gh + mktemp | PS | PS-native test harness or run under git-for-windows in CI |
| `agent-phase.sh:120`, `session-label.sh:121`, `wf-report.sh:20` | `python3` assumed present | PS (usually fine L) | Guard + install hint; python.org/winget on Windows |

## dot_claude/ (settings, hooks, statusline, commands)

| File | Assumption | Breaks on | Proposed fix |
| --- | --- | --- | --- |
| `modify_private_settings.json.tmpl:61` | Permission allowlist entry with literal `/Users/evan/.claude/skills/...` | L, W, PS | Fixed in #65 — `{{ .chezmoi.homeDir }}` |
| `modify_private_settings.json.tmpl:87–274` (~18 hook commands) | Literal `/Users/evan/.config/iterm2/cc-status` paths; iTerm OSC-6 `\033]6;1;bg;…` sequences via `/dev/tty` | L, W, PS | homeDir templated in #65; OSC-6 TERM_PROGRAM guard and per-OS hook swap still open |
| `executable_statusline.sh` | bash, `jq`, process substitution, `find -mmin`, `/dev/tty` OSC-8, `$HOME` path sed | PS | PS statusline variant (sub-issue 5) |
| `hooks/executable_no-cd-write.py` | `#!/usr/bin/env python3` shebang; invoked by path in settings | PS | Invoked via `python3 <path>` with guard; PS hooks need a wrapper |
| `commands/*.md` (open-pr, finalize, start, review-comments, implement, pick, discuss, prompt-audit, create_plan, generate_prd) | Instruct Claude to run bash, `mktemp`, heredocs, `git worktree`, `$'…'` bashisms, `short` CLI, `poll-pr.sh` | PS | Per-OS command selection in the command bodies (Claude can adapt if told the platform); PS-native poll-pr/review-state |
| `skills/workflow`, `tighten`, `review-comments-procedure` | bash executables, `python3`, `gh` | PS | Same as commands; `wf-context.sh:345` already guards `timeout` — copy that pattern |
| `CLAUDE.md.tmpl:70,91`, `local-code-review-cycle.md.tmpl:5`, `claude.tmpl:28–30` | `.is_work` branching | — | Machine-role, not OS — no change needed, but document that it's orthogonal to `.chezmoi.os` |

## chezmoi mechanics

| Item | Assumption | Breaks on | Proposed fix |
| --- | --- | --- | --- |
| No `.chezmoi.os` usage anywhere | Templates assume macOS target implicitly | L, W, PS | Introduce `.chezmoi.os`/`.chezmoi.arch` branching; per-OS `.chezmoiignore` |
| Exec bits on `tools/*.sh`, `executable_*` | POSIX exec-bit delivery | PS | On Windows chezmoi can't set exec bits; needs the shim strategy + `.ps1` naming |
| `.chezmoiignore` | No OS logic; target-path patterns only | — | Add per-OS ignores (iterm2 config, iTerm DynamicProfiles, shell modules) |
| No `.chezmoi.toml.tmpl` in repo | Config template lives outside (unmanaged) | — | Decision point: bring OS/data vars into the repo-managed template |

Confirmed absences (don't re-investigate): no `sed -i ''`, `date -j`, or `stat -f` unguarded in tools/; no `open` (Finder) calls; no `osascript` outside `start-ticket.sh`; agents/*.md prompts shell out to nothing.

## Recommended order → sub-issues for epic #11

| # | Sub-issue | Scope | Why this order |
| --- | --- | --- | --- |
| 1 | De-hardcode paths | `/Users/evan` → `{{ .chezmoi.homeDir }}`/`$HOME` across zshrc, shell modules, settings template, iterm2 symlink; fix quoted-tilde `DEV` bug | Breaks Linux today; prereq for every port. **Done — #65** |
| 2 | Linux/WSL cleanup | iTerm/pbcopy guards, `~/Library` write guards, `readlink -f` portable fallback, per-OS install hints, fzf sourcing paths | Cheap wins; makes WSL near-fully working |
| 3 | chezmoi OS branching + Windows delivery | `.chezmoi.os` logic, per-OS `.chezmoiignore`, Windows script-install mechanism replacing symlink/exec-bit delivery | Foundation for any Windows content |
| 4 | PowerShell profile | `Microsoft.PowerShell_profile.ps1` equivalent: oh-my-posh prompt, fzf, aliases, directory/`DEV` conventions | First real PS artifact; validates #3 |
| 5 | Claude config Windows surface | PS statusline, hooks per-OS in settings template, command bodies with platform branches, PS-native poll-pr/review-state | Builds on #3–4 |
| 6 | tools/ PowerShell port | `wm`, `start-ticket` (wt.exe), `open-pr` `.ps1` siblings; `gh`/`ConvertFrom-Json` | Largest effort; depends on #3 |
| 7 | Docs / support matrix | README + CLAUDE.md cross-platform notes, per-OS install instructions | Last; reflects the finished state |
