---
name: workflow
description: Improve how we work — Claude config (CLAUDE.md, skills, commands, hooks, settings, agents), dotfiles, git/ticket workflow, and the scripts behind them. Use when the user asks to improve, tune, speed up, or fix the workflow, prompts, or Claude setup; when a recurring friction or repeated correction suggests a config change; or when they invoke /workflow. Routes each change to the right scope — this project vs. global dotfiles.
---

# Workflow

Work on *how we work*, not on the product. You are an expert in workflow
optimization and in writing effective, token-efficient Claude prompts.

## Non-negotiables

**Never leave this worktree** — no `cd` out to edit, no branch switch, no
`ExitWorktree` — unless asked. Editing the chezmoi source dir and `git-tools` is
expected and does not violate this; they're separate working directories.

**If you need an unavailable directory, stop and ask.** Don't work around it.
Name the path and wait.

**Err toward asking on anything touching global config; err toward acting on
anything local and reversible.**

## 1. Orient (one command)

```bash
~/.claude/skills/workflow/wf-context.sh
```

Prints `key=value` facts: repo root, branch, default branch, worktree status,
`.claude/` layout, standing ticket, chezmoi state, tool availability. **Run this
instead of probing with a dozen separate calls.**

Keys that change what you do:

| Key | Meaning |
| --- | --- |
| `project_claude_dir=symlink` | **Stop.** `.claude/` points at the main checkout; edits escape the branch into the user's working copy. Report and ask. |
| `project_claude_settings_local=symlink` | Same trap, quieter: only `settings.local.json` is shared. Don't edit it here. |
| `chezmoi_settings_source_kind=modify` | `settings.json`'s source is a *script*, not JSON — see §3. |
| `standing_ticket_source=none` | No ticket found by marker or branch — see §4. |
| `tool_*=git_tools_only` | Not on this session's PATH; invoke as `$git_tools_dir/<name>.sh`. |
| `tool_*=missing` | Stop and ask. |
| `chezmoi_source_dirty_files` > 0 | Dotfiles work already in flight. Say so before adding to it. |
| `chezmoi_source_behind_origin` > 0 | The other machine pushed. `git -C <chezmoi_source_root> pull --rebase` **before** editing, or the push later becomes a merge. |
| `chezmoi_source_ahead_origin` > 0 | Unpushed dotfiles commits here — the other machine can't see them. Mention it. |
| `chezmoi_source_pull_rebase` ≠ `true` | Plain `pull` will make merge commits. Offer `git -C <chezmoi_source_root> config pull.rebase true`; it is per-clone, so each machine needs it. |
| `chezmoi_healthy=no` | chezmoi can't read its source state — every other `chezmoi_*` key is a false negative. Stop; `chezmoi doctor`. |
| `default_branch_source=probe` | `origin/HEAD` gave no usable answer (unset, or pointing at a pruned ref), so `default_branch` is a guess from a fixed `development→main→master` order and may name the wrong branch. Don't branch off it without checking. |
| `default_branch_source=none` | No default branch at all. |
| `commits_*_default` absent | Not zero — unknown. The keys are omitted whenever the comparison couldn't be made (no default branch, unborn HEAD). Never report "0 behind" from a missing key. |
| `chezmoi_available=no` | chezmoi isn't installed; §3 doesn't apply and every other `chezmoi_*` key is absent or `unknown`. Ask before touching `~/.claude` by hand. |

`wf-context.sh srcpath <target>` resolves the chezmoi source for one file.

## 2. Classify — local or global?

The judgment this skill exists for. Decide per improvement, before writing, and
say which you chose.

**Project-local** (this repo's `.claude/` or `CLAUDE.md`): names this repo's
commands, paths, services, schemas, test tiers, or CI; encodes a convention only
this codebase follows; allowlists a command meaningful only here.

**Global** (chezmoi source for `~/.claude`): holds for every repo — git hygiene,
review gates, tone, subagent handoffs, how to ask questions; describes the user
rather than the project; a tool on `PATH` everywhere (`git-tools`).

**Tiebreakers.** A rule observed in one repo stays local until it bites in a
second — promote on the second sighting, don't predict it. When genuinely both,
write the global statement plus a thin project-local pointer, never two copies
that can drift.

## 3. Global config lives in chezmoi

`~/.claude` is chezmoi-managed: editing those files directly is reverted by the
next `chezmoi apply` and conflicts when dotfiles sync to another machine.
**Edit the source, never the target.**

Source naming: `dot_claude/` → `~/.claude/`, `executable_` → mode +x,
`private_` → mode 600, `.tmpl` → Go template, `modify_<name>` → the source is a
**script that rewrites** the target.

**Existing file** — `wf-context.sh srcpath <target>` gives the source. Then:

1. Edit the source.
2. `chezmoi diff <target>` — show the user. **Always name the target**; bare
   `diff`/`apply` hits every managed entry, including unrelated in-flight work.
3. `chezmoi apply <target>` — make it live.
4. **Stop. Never commit the dotfiles repo** — it syncs across machines, so the
   commit is the user's. Say what's waiting for them.

**New file** (`srcpath` exits **1**, and only 1): write the real file at its
target path, then `chezmoi add <target>` (`--template` if it needs `{{ }}`).
chezmoi derives the source name and preserves mode, so an executable lands as
`executable_*`. Never hand-name a source file.

**Read `add`'s output — rc 0 doesn't mean added.** On a path matched by
`.chezmoiignore`, `chezmoi add` prints `warning: ignoring <path>` and exits 0
having done nothing. `srcpath` can't pre-detect this (`chezmoi ignored` only
sees entries already in the source state), so the warning is the only signal.
If you see it, the file stays unmanaged by design — say so rather than
reporting it added.

**`srcpath` exits 3 — chezmoi is broken, not the file unmanaged.** It can't read
its source state at all: the source dir is missing, or a scaffolding file
(`.chezmoiignore`, `.chezmoidata.*`, `.chezmoiexternal.*`, `.chezmoiversion`)
won't parse, which aborts source-path resolution for *every* file. This is
*not* the new-file case: treating
it as one means writing directly to `~/.claude/...`, which is the one thing §3
forbids, and the next working `chezmoi apply` silently reverts it. **Stop and
tell the user to run `chezmoi doctor`.** Same for `chezmoi_healthy=no` in the
facts block: every `chezmoi_*` answer there is then a false negative.

rc 3 is still narrow, and rc 1 is **not** a clean bill of health — a syntax
error in a *content* template (`CLAUDE.md.tmpl`) leaves source-path resolution
working and still breaks `chezmoi apply`. That's what step 3 below is for: read
the `apply` output, don't assume it succeeded.

**A `.tmpl` has conditional branches** (`{{ if .is_work }}`). Read enough to put
your text in the right one — a Shortcut-specific rule in the shared section
leaks work conventions onto personal machines.

**`settings.json`** (`chezmoi_settings_source_kind=modify`): the source is Python
with a `MANAGED` dict merging a curated key subset. Edit that dict — do not write
JSON into it.

## 4. Project-local config and the standing ticket

Project `.claude/` changes go through ticket → branch → PR; repo rules disallow
committing to the default branch.

Take the ticket by precedence — `standing_ticket` from §1 (marker or branch
name), then the project's CLAUDE.md if it names one. Only if all are silent,
ask whether to use a standing ticket or a plain descriptive branch.

With a ticket: use the matching worktree if one exists, else create it with
`start-ticket.sh <id>` — never raw `git worktree add`. If no marker file exists,
write one on the branch so the question never recurs:

```json
{ "standing_ticket": "sc-74085", "provider": "shortcut", "branch_prefix": "sc-74085" }
```

at `.claude/workflow-config.json`. Show the diff and get approval before
committing, unless the user said "commit this."

## 5. Prefer shell over prose

A deterministic step — same inputs, same output, no judgment — goes in a script,
not a prompt. Move it when it's a fixed command sequence parsed the same way
each time, a fact about the repo (default branch, worktree layout, ticket id),
or a convention restated in more than one prompt. Keep it in the prompt when it
needs judgment: trade-offs, prose, scope calls.

Where it goes:

- **`git-tools/main/`** — useful outside Claude or shared by several commands.
  Shared read-only facts belong in `lib/repo-facts.sh`, which exists for this.
- **This skill's directory** — specific to this skill, like `wf-context.sh`.
- Scripts print `key=value` on stdout, exit non-zero with a reason on stderr,
  and stay read-only unless the task is explicitly a mutation.

`git-tools` is a separate repo: branch, commit, PR. Not this worktree — so its
changes are a separate reviewable unit, not folded into the project PR.

## 6. Writing the prompt itself

- **State the rule once, in the narrowest scope that holds it.** Duplication
  across global and project files is how instructions drift into contradiction.
- **Lead with the trigger.** A skill `description` is matched before the body is
  read; it must name the firing situations in the user's own words.
- **Give the reason only when it prevents a plausible wrong move.**
- **Cut anything the model already does by default.** Carry what's *surprising*
  about this setup, not general competence.
- A rule firing every session belongs in `CLAUDE.md`; one firing per task
  belongs in a skill, where it costs nothing until invoked.

Those are the rules for *writing* one. For judging prompts that already exist —
staleness, bloat, scope leakage, duplication — use the `prompt-review` skill,
which holds the criteria and the evidence bar. `/prompt-audit [repo]` runs it
over a whole repo; `branch-reviewer` picks it up when a diff touches prompt
files. Don't restate its checks here.

## 7. Cloud counterparts

Cloud sessions see only committed files, so projects that use them carry `cloud-start`,
`cloud-open-pr`, `cloud-finalize`, `cloud-code-review-cycle` and `cloud-governor` in
`.claude/commands/`, `git` and `gh` only, each naming its global counterpart.

- **Editing a global `start`, `open-pr`, `finalize`, `local-code-review-cycle` or
  `governor`:** check the repo's matching `cloud-*` file and report whether it needs the
  same change.
- **Personal project with none:** suggest creating them once, modelled on Kardashev's.
- **Skip** when `ticket_provider=shortcut` or the repo is a work repo.

## 8. Report

State what changed by scope (project / global-source / git-tools), what's
applied vs. awaiting the user (dotfiles commit, approval, PR), and anything you
deliberately skipped.
