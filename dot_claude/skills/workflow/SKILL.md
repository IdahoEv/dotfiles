---
name: workflow
description: Improve how we work — Claude config (CLAUDE.md, skills, commands, hooks, settings, agents), prompts, dotfiles, git/ticket workflow, and the scripts behind them. Use when the user asks to improve, tune, speed up, or fix the workflow or prompts; when a recurring friction or repeated correction suggests a config change; or when they invoke /workflow. Routes each change to the right scope and shapes it as a ticket; outside the dotfiles repo, a global change becomes an intake issue there. Delivery mechanics are in delivery.md for the dotfiles repo.
---

# Workflow

Work on *how we work*, not on the product. You are an expert in workflow
optimization and in writing effective, token-efficient Claude prompts.

**Governor session only** (title ends " Governor"): run `workflow-session.sh` and stop — it
opens the project's `workflow` worktree and session. Relay its `worktree=` and `kickoff=`
paths (with `launcher=none` nothing opens; the user starts it from those), and on
`launched=no` the `--relaunch` option. Any other session: skip this and follow the skill
below as ordinary guidance.

**First action:** run `session-label.sh --title Workflow --color green` (`--color project`
on the `workflow` branch, so the project's session is identifiable). The title must be
exactly "Workflow": the statusline keys on it. Skip this if `session-label.sh` isn't found;
it is silent outside a background session.

## Non-negotiables

**Never leave this worktree** — no `cd` out to edit, no branch switch, no
`ExitWorktree` — unless asked. Editing the dotfiles source in your own
worktree, and `tools/`, is expected and does not violate this; the deploy
clone is never a working copy.

**If you need an unavailable directory, stop and ask.** Don't work around it.
Name the path and wait.

**Err toward asking on anything touching global config; err toward acting on
anything local and reversible.**

## 1. Orient (one command)

```bash
~/.claude/skills/workflow/wf-context.sh
```

Prints `key=value` facts: repo root, branch, default branch, worktree status,
`.claude/` layout, standing ticket, dotfiles source, tool availability. **Run
this instead of probing with a dozen separate calls.**

Keys that change what you do:

| Key | Meaning |
| --- | --- |
| `dotfiles_source=dev` | This checkout is a dev/ticket worktree of the dotfiles source. Read `delivery.md` before editing. |
| `dotfiles_source=deploy` | You are in the deploy clone. It is never a working copy — don't edit it; read `delivery.md` for the pull/apply step. |
| `dotfiles_source=none` | Not the dotfiles repo. Project-local edits stay here; a global change goes through intake (§3). |
| `project_claude_dir=symlink` | **Stop.** `.claude/` points at the main checkout; edits escape the branch into the user's working copy. Report and ask. |
| `project_claude_settings_local=symlink` | Same trap, quieter: only `settings.local.json` is shared. Don't edit it here. |
| `standing_ticket_source=none` | No ticket found by marker or branch — see §4. |
| `tool_*=git_tools_only` | Not on this session's PATH; invoke as `$git_tools_dir/<name>.sh`. |
| `tool_*=missing` | Stop and ask. |
| `default_branch_source=probe` | `origin/HEAD` gave no usable answer, so `default_branch` is a guess from a fixed `development→main→master` order and may name the wrong branch. Don't branch off it without checking. |
| `default_branch_source=none` | No default branch at all. |
| `commits_*_default` absent | Not zero — unknown. The keys are omitted whenever the comparison couldn't be made. Never report "0 behind" from a missing key. |

Source-path and deploy facts are delivery concerns — see `delivery.md` when
`dotfiles_source` is `dev` or `deploy`.

## 2. Classify — local or global?

The judgment this skill exists for. Decide per improvement, before writing, and
say which you chose.

**Project-local** (this repo's `.claude/` or `CLAUDE.md`): names this repo's
commands, paths, services, schemas, test tiers, or CI; encodes a convention only
this codebase follows; allowlists a command meaningful only here.

**Global** (the dotfiles repo, which deploys to `~/.claude`): holds for every
repo — git hygiene, review gates, tone, subagent handoffs, how to ask questions;
describes the user rather than the project; a tool on `PATH` everywhere.

**Tiebreakers.** A rule observed in one repo stays local until it bites in a
second — promote on the second sighting, don't predict it. When genuinely both,
write the global statement plus a thin project-local pointer, never two copies
that can drift. **State the rule once, in the narrowest scope that holds it.**

## 3. Where the edit lands

- `dotfiles_source=dev` — the delivery checkout. Author the change for the
  current ticket (§4): read `delivery.md`, then edit in this worktree. Do not
  file an intake issue here.
- `dotfiles_source=deploy` — no edits here; it is not a working copy.
- `dotfiles_source=none` — project-local changes (this repo's `.claude/`,
  `CLAUDE.md`) are made here as usual (§4). A change that §2 classifies global
  goes through intake below: never edit `~/.claude`, the deploy clone, or a
  chezmoi source, and never `chezmoi add` against them.

### Intake: a global change from another repo

1. Everything sent to GitHub — search keywords, title, body, comment — is on
   a public service: strip work-repo names, hosts, credentials, internal
   URLs, customer names, and ticket ids before step 2. If the evidence can't
   be sanitized, describe the shape of the problem and keep the evidence local.
2. Check for an existing issue with generic terms:
   `gh issue list -R github.com/IdahoEv/dotfiles --state all --search "<generic terms>"`.
   If one covers it, check its state with
   `gh issue view <n> -R github.com/IdahoEv/dotfiles --json state`. Reopen a
   closed one (`gh issue reopen <n> -R github.com/IdahoEv/dotfiles`) or link
   it from a new issue; a comment on a closed issue is not intake. If the
   search fails, skip it and draft anyway.
3. Draft the title and body for either path: `## Friction`, `## Evidence`
   (command and output, `file:line`, what you were attempting),
   `## Proposed change`, and a one-line scope note.
4. Show the draft and wait for approval; create nothing before it.
5. File it with the body on stdin:
   `gh issue create -R github.com/IdahoEv/dotfiles --title "<title>" --body-file -`,
   or `gh issue comment <n> -R github.com/IdahoEv/dotfiles --body-file -`
   after reopening a closed issue. If that call fails, hand the user the
   failure and the draft — title and body to create, or issue number and body
   to comment — rather than improvising another path. On success, report the
   URL; intake is done. Continue with any local work and the §8 report.

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

- **A project's own `tools/`** — useful outside Claude or shared by several of
  its commands; it ships in that project's PR.
- **The dotfiles repo's `tools/`** — shared read-only facts belong in
  `tools/lib/repo-facts.sh`, which exists for this.
- **This skill's directory** — specific to this skill, like `wf-context.sh`.
- Scripts print `key=value` on stdout, exit non-zero with a reason on stderr,
  and stay read-only unless the task is explicitly a mutation.

The dotfiles repo's `tools/` is chezmoi-ignored (it runs in place from the
deploy clone), so a script change there rides the same ticket and PR as the
prompt that calls it. Never split them across two reviews.

## 6. Writing the prompt itself

- **Lead with the trigger.** A skill `description` is matched before the body is
  read; it must name the firing situations in the user's own words.
- **Give the reason only when it prevents a plausible wrong move.**
- **Cut anything the model already does by default.** Carry what's *surprising*
  about this setup, not general competence.
- A rule firing every session belongs in `CLAUDE.md`; one firing per task
  belongs in a skill, where it costs nothing until invoked.
- **Know which session reads it.** `/governor` and `/start` are instructions a
  session loads at launch. Editing one changes the next session that runs the
  command; the editing session keeps the copy it already loaded. Name the
  affected role in the report — an edit that takes effect next session is not
  observable in this one.

For judging prompts that already exist — staleness, bloat, scope leakage,
duplication — use the `prompt-review` skill; it holds the criteria, the evidence
bar, and which agent or command runs it. Don't restate the checks here.

## 7. Cloud counterparts

Cloud sessions see only committed files, so projects that use them carry `cloud-start`,
`cloud-open-pr`, `cloud-finalize`, `cloud-code-review-cycle` and `cloud-governor` in
`.claude/commands/`, `git` and `gh` only, each naming its global counterpart.

- **Editing a global `start`, `open-pr`, `finalize`, `local-review-cycle` or
  `governor`:** check the repo's matching `cloud-*` file and report whether it needs the
  same change.
- **Personal project with none:** suggest creating them once, modelled on Kardashev's.
- **Skip** when `ticket_provider=shortcut` or the repo is a work repo.

## 8. Report

State what changed by scope (project / global source / tools), what is authored
versus shipped (PR open or merged — delivery details are in `delivery.md`), and
anything you deliberately skipped. An intake issue is authored, not shipped:
give its URL.
