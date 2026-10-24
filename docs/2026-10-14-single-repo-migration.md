# Plan: fold git-tools into the dotfiles repo (single workflow source of truth)

Status: **in progress.** Epic #5; steps map to sub-issues #6–#10.

## Why

- Prompts (chezmoi) and the scripts they call (git-tools) versioned and synced
  separately, so a prompt could land before the script it needs.
- One repo, one pull, prompt+script changes in one PR. Chezmoi stays the sync tool.

## Target layout: two checkouts

| Checkout | Path | Role |
|---|---|---|
| Deploy | `~/.local/share/chezmoi` (plain clone, `main` only) | chezmoi source; `tools/` on `PATH`; only fast-forwards |
| Dev | `$DEV/dotfiles` (bare, `wm` layout) | all edits, as ticket worktrees + PRs |

Why two: no per-machine `sourceDir` override, plain `chezmoi init` bootstraps a
fresh machine, and a broken branch can't break the tools on `PATH`.

Change loop: dev worktree → edit → `chezmoi -S <worktree> diff|apply <target>` to
try it → PR → merge → `git pull` in the deploy clone → `chezmoi apply`. Applying from a
branch deploys unmerged state; the next apply from the deploy clone reverts it.
`tools/` is chezmoi-ignored and runs in place, so it needs no apply.

## Steps (do both machines in one sitting)

| # | Step | Ticket |
|---|---|---|
| 1 | **(once)** Preconditions: both repos clean and pushed, no open git-tools PRs | #6 |
| 2 | **(once)** `git subtree add --prefix=tools <git-tools main>` keeps history and exec bits | #6 |
| 3 | **(once)** Add `tools` to `.chezmoiignore`; drop the git-tools external; repoint hard-coded paths to `~/.local/share/chezmoi/tools` | #6 |
| 4 | Create the dev bare repo (`wm` layout); retire `Documents/Development/git-tools/` once `PATH` no longer uses it | #7 |
| 5 | **(once)** `open-pr.sh` generic GitHub provider (no ticket tracker needed) | #8 |
| 6 | **(once)** Update `/workflow` and `wf-context.sh`: edit in a dev worktree, `chezmoi -S`, PR, merge, pull deploy clone, apply; `srcpath` and dirty/ahead/behind facts honor `-S` | #9 — done |
| 7 | Work laptop; then **(once)** archive `IdahoEv/git-tools` (read-only) after both machines are verified | #10 |

Done for #6: `chezmoi status` empty and `which worktree-manager.sh` resolves into
`~/.local/share/chezmoi/tools`. That needs the branch merged and pulled into the deploy clone.

## Open checks

- `start-ticket.sh` / `wm` assume ticket providers; dotfiles work should use plain
  `wm <branch>`. Confirm nothing in `wm` requires a ticket.
- chezmoi symlink-directory support, if `~/.claude/{commands,skills,agents}` should
  become symlinks into the deploy clone. Not required; copying works.
- Fresh-machine bootstrap: `chezmoi init` plus a dev `git clone --bare` + `wm --init`.
  Document in the repo README.
- Work machine: `is_work`, fireworks-owned settings keys, and the SSH host alias
  (`github.com` vs `github.com-personal`) differ per machine; confirm remotes.

## Rollback

Until #7 retires the old checkout, `Documents/Development/git-tools/main` is intact:
restore the external entry and the old `PATH` line. After that, recovery is a fresh
clone of the git-tools repo, so keep it unarchived and the old directory until both
machines have run a normal day on the new layout.

## Follow-ups (separate PRs)

- Plain `CLAUDE.md` + `@`-import of a per-machine `machine.md` instead of the
  `is_work` template (verify `@path` import support first).
- Project commands extend global ones instead of shadowing: diff project
  `start.md`/`finalize.md` against global, move repo-specific parts to data files
  (as `kickoff-preamble.md` does), add a shadow check to `wf-context.sh`.
- Split work-only permissions and `$HOME`-derive hook paths in the settings merge script.
