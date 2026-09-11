# Start a Ticket

Prepares a worktree + kickoff for a tracker ticket and opens a Claude session for it.
Takes a ticket id (`/start 22`). No id → list the repo's open tickets and ask which one.

Ticket tracking is provider-based: **GitHub issues** or **Shortcut stories**. The
provider is resolved per-repo by `start-ticket.sh` (`.start-ticket.conf` in the repo
root, else autodetect from installed CLIs) — don't assume which one; if you need to
know, check for `.start-ticket.conf` or run `gh repo view` / `command -v short`.
All ticket-state operations go through `start-ticket.sh` and its providers, never
raw CLI calls, except the enrichment queries below.

## Steps

### 1. Setup

```bash
start-ticket.sh <id> --no-tab
```

Creates the worktree (via `worktree-manager.sh`; the Shortcut path also writes a
`.ticket.local.md` with the full story into the worktree), marks the ticket in
progress, and writes a base kickoff from the repo's `.claude/kickoff-preamble.md`
(if present — that file carries the project's working agreement, so this command
doesn't). Prints `worktree=<path>` and `kickoff=<path>` on stdout — capture both.

If it exits non-zero (ticket not open, no provider, CLI not authed), **stop** and
report why. If the worktree already existed it still succeeds and prints the path.

### 2. Enrich the kickoff

Read the kickoff file. Append a `## Context` section with whatever applies:

- **GitHub provider** — parent epic + its still-open sibling sub-issues, one line each:
  ```bash
  gh issue view <parent> --json title,subIssuesSummary,subIssues \
    -q '"\(.title) (\(.subIssuesSummary.completed)/\(.subIssuesSummary.total))",
        (.subIssues.nodes[] | select(.state=="OPEN") | "#\(.number) \(.title)")'
  ```
- **Shortcut provider** — read `<worktree>/.ticket.local.md` for story context; if
  it names an epic or linked/dependent stories, note them (no bulk sub-issue
  progress query exists for Shortcut — skip that line rather than approximating).
- **Dependencies** (either provider): any `Depends on #X` / `Blocked by #X` /
  linked-story references in the ticket body — fetch each one's state via the
  provider CLI; warn if still open, but don't block.
- **Read these first**: source files the ticket body names.

Write the enriched kickoff back to the same path.

### 3. Open the session

```bash
start-ticket.sh --tab-only "<worktree>" "<kickoff>"
```

Opens a new iTerm tab split into two horizontal panes: `claude` on top (with the
kickoff typed into its input but **not submitted** — the user reviews and hits
Enter), a shell in the worktree on the bottom. The kickoff is also on the
clipboard. Not in iTerm → it prints the `cd` + `claude` command instead.

### 4. Report

Worktree path, branch, ticket state, and — if the ticket has a parent epic — the
epic's sub-issue progress and which sibling tickets remain open (GitHub only).
