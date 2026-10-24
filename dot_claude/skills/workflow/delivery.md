# Delivery (dotfiles repo)

Read this when `wf-context.sh` reports `dotfiles_source=dev`: this checkout is a
dev/ticket worktree of the dotfiles source. Edits are committed here and reach
the machine through the ticket flow. The deploy clone
(`chezmoi_deploy_root`, normally `~/.local/share/chezmoi`) is `main` only —
never edit or commit there.

## Source naming

`dot_claude/` → `~/.claude/`, `executable_` → mode +x, `private_` → mode 600,
`.tmpl` → Go template, `modify_<name>` → the source is a **script that rewrites**
the target.

A `.tmpl` has conditional branches (`{{ if .is_work }}`). Read enough to put
your text in the right one — a work-specific rule in the shared section leaks
onto the personal machine.

## Existing file

`wf-context.sh srcpath <target>` prints the source path; in `dev` mode that is a
path in this worktree. Edit it there.

`srcpath` exit codes:

- **0** — managed; path on stdout.
- **1** — chezmoi is healthy and the target is not managed in *this* source.
  The stderr names the deploy path when the branch simply does not carry the
  file; otherwise it is the new-file case below. It also covers a path matched
  by `.chezmoiignore`, which `srcpath` can't distinguish.
- **2** — chezmoi is not installed. Ask before touching `~/.claude` by hand.
- **3** — chezmoi cannot read the source state at all: a missing source dir, or
  `.chezmoiignore` / `.chezmoidata.*` / `.chezmoiexternal.*` / `.chezmoiversion`
  won't parse. **Not** the new-file case — do not edit the target, and do not
  treat the deploy clone as broken too (`chezmoi_deploy_healthy` is separate).
  Run `chezmoi doctor`.

rc 3 is narrow: a syntax error in a *content* template (`CLAUDE.md.tmpl`) still
resolves source paths and still breaks `chezmoi apply`. That is why the diff
below is a step, not an assumption.

## New file

Prefer creating `dot_claude/<path>` directly in the worktree — the naming
convention is known, and the file is tracked like any other. Use
`chezmoi -S <worktree> add <target>` only when the source name or mode is
non-obvious; it derives both, and it reads `$HOME`, not the worktree.

**Read `add`'s output — rc 0 does not mean added.** On a path matched by
`.chezmoiignore`, `chezmoi add` prints `warning: ignoring <path>` and exits 0
having done nothing. If you see it, the file stays unmanaged by design — say so
rather than reporting it added.

## `settings.json`

Its source may be a `modify_` script (`chezmoi_settings_source_kind=modify`).
The source is Python with a `MANAGED` dict merging a curated key subset. Edit
that dict — never write JSON into it.

## Try it before the PR

```bash
chezmoi -S <worktree> diff  ~/.claude/<path>    # read-only preview
chezmoi -S <worktree> apply ~/.claude/<path>    # writes to $HOME; diff first
```

**Always name the target.** A bare `apply` writes every managed file, reverting
anything on `main` that the branch lacks. Applying from a branch deploys
unmerged state; the next apply from the deploy clone reverts it.

## Ship it

Commit in the worktree, open the PR, review, merge. Then, in the deploy clone:

```bash
git pull --rebase
chezmoi apply ~/.claude/<path>
```

The deploy clone is the thing that must not be committed to; committing in the
worktree is the normal flow. Check `chezmoi_deploy_behind_origin` — after a
merge it is usually the count that needs pulling. If `chezmoi_deploy_dirty_files`
is non-zero or `chezmoi_deploy_branch` is not `main`, stop and report: someone
left local state there.

`tools/` is chezmoi-ignored and runs in place from the deploy clone, so a pull
updates it and no apply is needed.

## Verify a prompt change

`/governor` and `/start` are loaded by the session that runs them. Verify a
change in a fresh session after the pull and apply; the editing session keeps
its loaded copy (see the authoring note in `SKILL.md` §6).
