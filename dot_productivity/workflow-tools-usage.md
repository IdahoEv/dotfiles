# workflow-tools / worktree-manager usage

Source: `~/.local/share/chezmoi/tools/worktree-manager.sh`

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

## Per-project config (outside the project repo)

For repos you don't own, or whose config must not reach a public remote. A per-machine overlay is keyed by the `origin` URL, so every worktree and fresh clone of a repo finds the same files and nothing is ever inside the checkout:

```
$PROJECT_OVERLAYS_DIR (default ~/.config/project-overlays)/<owner>/<repo>/
  governor.md  kickoff-preamble.md  start-ticket.conf   (init scaffolds governor.md and start-ticket.conf; create the preamble when you have one)
  claude/                     personal, project-scoped Claude assets
    agents/*.md               agent files (name/description/model frontmatter + brief)
    commands/*.md             command markdown
    skills/<name>/SKILL.md    skills
```

| File | Lookup order (first hit wins) |
|---|---|
| `governor.md`, `kickoff-preamble.md` | `<repo>/.claude/<name>` → overlay. Whole file; no merging, so a committed file fully replaces the overlay's |
| `start-ticket.conf` keys (`provider`, `label_noise`, `launcher`, `openpr_provider`, `color`, …) | per key: `<worktree>/.start-ticket.conf` → `<main repo>/.start-ticket.conf` → overlay `start-ticket.conf` → `~/.config/start-ticket/config` |
| `claude/` agents, commands, skills | Claude Code registers these only from the repo's `.claude/` and `~/.claude`, so overlay assets are injected by instruction instead: `start-ticket.sh` appends a "Personal project Claude assets" section to every kickoff listing them, and `/governor` announces them at startup. Agents are launched as `general-purpose` with the file body as brief (same pattern as `docs/local/reviewers/`); commands and skills are read and followed inline. A repo-defined same-named asset wins. |

Used by `/governor` (says which file it loaded), `start-ticket.sh`, `open-pr.sh`, `worktree-manager.sh`.

```
project-config.sh init                 # scaffold the overlay for the current repo (never overwrites)
project-config.sh find governor.md     # which file would load, and from where
project-config.sh dir                  # overlay path
project-config.sh claude-dir           # overlay claude/ dir
project-config.sh list [agents|commands|skills]   # overlay claude/ asset paths
project-config.sh store-init [<url>]   # git-init the overlays root; you commit and push
```

**Overlay vs `docs/local/`.** Both hold personal, uncommitted project content; the rule is survival of a fresh clone. If a brand-new clone of the repo needs it — governor.md, conf keys, preambles, personal agents — it belongs in the overlay, keyed by remote. If it is tied to this checkout's tree — scratch notes, temporary docs, throwaway experiments — it belongs in `docs/local/` (globally gitignored, symlinked into worktrees by `wm`). Existing `docs/local/reviewers/` keep working; new personal agents default to the overlay's `claude/agents/`.

**Session color.** `session-label.sh --color project` (run by `/start` and `/governor`) resolves: `color=` in `start-ticket.conf` (lookup order above) → `tools/project-colors` (by directory name) → none. Palette: red blue green yellow purple orange pink cyan; any other value is an error saying whether it came from `start-ticket.conf` (any layer) or `project-colors`. Put `color=` in the overlay for a repo you don't own so its name stays out of the dotfiles repo. `session-label.sh --show` prints the result. A repo can also commit `color=green` in its own `.start-ticket.conf`, which makes its `project-colors` line redundant.

The overlays root is a plain directory and can be its own git repo, so the config can be versioned somewhere other than the dotfiles repo (e.g. a work-hosted private repo). Its paths name your projects, so keep that remote as private as the config. `PROJECT_OVERLAYS_DIR` points it at an existing clone (the pre-rename `GIT_TOOLS_PROJECTS_DIR` still resolves, with a deprecation warning). The overlay root was renamed from `~/.config/git-tools/` (pre-#87): `chezmoi apply` runs `run_once_before_migrate-project-overlays.sh` once, which moves the old root — flattening `projects/` and dot-prefixing the provider dirs — without reading any overlay content.
