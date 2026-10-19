# Plan: fold git-tools into the dotfiles repo (single workflow source of truth)

Status: **agreed, not started.** Decided 2026-10-14; implement on a quiet day.

## Why

- Prompts (chezmoi) and the scripts they call (git-tools) version and sync
  separately, so a prompt can land before the script it needs.
- Two sync processes (direct-push to `main` vs. PR + 24h `--ff-only` external) have
  different latencies; they drift when unattended.
- Goal: one repo, one pull, prompt+script changes in one PR. Chezmoi stays the
  sync tool. Review flow is kept via worktrees + PRs.

Current state worth knowing: git-tools is *already* a chezmoi `git-repo` external
(`.chezmoiexternal.toml`, `--ff-only`, 24h refresh). A dirty tree or unpushed commit
in `~/Documents/Development/git-tools/main` makes that pull fail.

## Target layout

```text
~/Documents/Development/dotfiles/     bare repo (wm layout)
  main/        chezmoi sourceDir; stays on main; = "what is deployed"
    tools/     the git-tools scripts; chezmoi-ignored; PATH points here
  <branch>/    work worktrees created with wm
```

Change loop: worktree → edit → `chezmoi -S <worktree> diff|apply <target>` to try
it → PR (local review) → merge → `git pull` in `main/` → `chezmoi apply`.
Applying from a branch deploys unmerged state; the next apply from `main` reverts
it. Scripts run in place from a checkout, so they need no apply.

## Steps (per machine unless marked once)

Do both machines in one sitting so they are never skewed.

**Preconditions (once):** dotfiles and git-tools both clean and pushed
(`wf-context.sh` shows `chezmoi_source_dirty/ahead/behind` = 0); no open git-tools
PRs; no active worktrees in `git-tools/`.

1. **(once) Merge history.** In the dotfiles clone: add git-tools as a remote and
   merge its `main` into `tools/` (`git subtree add --prefix=tools <git-tools-url> main`
   or an unrelated-histories merge). Check `tools/*.sh` keep their executable bit.
2. **(once) Ignore `tools/`.** Add `tools` to `.chezmoiignore` so chezmoi does not
   deploy it. Remove the git-tools entry from `.chezmoiexternal.toml`. Update the
   hard-coded `Documents/Development/git-tools/main` path in:
   `dot_shell_modules/worktree-manager` (PATH), `dot_shell_modules/git-tools-freshness`
   (retarget at the dotfiles repo), `dot_claude/CLAUDE.md.tmpl`,
   `dot_claude/skills/workflow/executable_wf-context.sh`,
   `dot_productivity/git-tools-usage.md`. Re-grep afterwards; also grep `~/.claude`
   commands and skills for `git-tools`.
3. **Convert the clone.** `wm --init` in the dotfiles clone, producing `dotfiles/main/`.
   Rehearse on a throwaway copy first.
4. **Point chezmoi at it.** Set `sourceDir` in `~/.config/chezmoi/chezmoi.toml` to
   `.../dotfiles/main`. This file is per machine and not synced. Verify with
   `chezmoi source-path` and an empty `chezmoi status`.
5. **Fix PATH and remove the old checkout.** New shell → `which worktree-manager.sh`
   resolves into `dotfiles/main/tools`. Only then delete the old
   `git-tools/` directory (keep it until the old PATH entry is gone).
6. **Re-set per-clone git config** (not synced): `pull.rebase true`,
   `rebase.autoStash true` in the new `main/`.
7. **(once) Update `/workflow`.** §3 becomes: edit in a worktree, try with
   `chezmoi -S <wt>`, PR, merge, pull `main`, apply. `wf-context.sh srcpath` and the
   dirty/ahead/behind facts need to honor `-S`/the worktree. Remove the "never commit
   the dotfiles repo" rule only if you want PRs opened for dotfiles changes by Claude.
8. **(once) Archive** the `IdahoEv/git-tools` GitHub repo (read-only) after both
   machines are verified.

## Open checks before starting

- `open-pr.sh` provider lookup for a repo with no ticket tracker (the kardashev
  provider is the only shipped one). Likely needs a trivial default; test in a
  throwaway PR.
- `start-ticket.sh` / `wm` assume ticket providers; dotfiles work should use plain
  `wm <branch>`. Confirm nothing in `wm` requires a ticket.
- chezmoi symlink-directory support, if `~/.claude/{commands,skills,agents}` should
  become symlinks into `main/` (removes the apply step for prompts). Test on a
  throwaway target first. Not required for this plan; copying works.
- Fresh-machine bootstrap: `chezmoi init` expects a plain clone. Document the
  `git clone --bare` + `wm --init` + `sourceDir` sequence in the repo README.
- Work machine: `is_work`, the fireworks-owned settings keys, and the SSH host alias
  (`github.com` vs `github.com-personal`) differ per machine; confirm remotes
  after conversion.

## Rollback

Until step 5, the old `git-tools/` checkout and the old `sourceDir` are untouched:
revert `sourceDir` in `chezmoi.toml` and restore the external entry. After step 5,
recovery is a fresh clone of the archived git-tools repo, so do not delete the old
directory until both machines have run a normal day on the new layout.

## Follow-ups (after migration, separate PRs)

- Plain `CLAUDE.md` + `@`-import of a per-machine `machine.md` instead of the
  `is_work` template (verify `@path` import support first).
- Project commands extend global ones instead of shadowing: diff project
  `start.md`/`finalize.md` against global, move repo-specific parts to data files
  (as `kickoff-preamble.md` does), add a shadow check to `wf-context.sh`.
- Split work-only permissions and `$HOME`-derive hook paths in the settings merge
  script.
