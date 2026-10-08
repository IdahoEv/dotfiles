# Remind

Re-orient me after time away. Read-only: make no changes to code, branches, or worktrees.

Gather state for the current project (run independent commands in parallel):

- **Git:** latest commits on the default branch (after `git fetch`), `git worktree list`, and uncommitted/unpushed work in each non-default worktree.
- **PRs/MRs:** open ones with status and review state (`gh` for GitHub; the project's own tooling otherwise, e.g. Shortcut/GitLab).
- **Tickets:** open issues/stories, grouped by milestone/epic. Use whatever tracker the project's CLAUDE.md names; also skim TODO.md or docs/plans if present.
- **Sessions:** other Claude sessions via `ListAgents`.

Then report, concisely, under these headings:

1. **Current state** — what landed recently, what's open, anything dirty or stale.
2. **Open sessions** — each with name, status, and (if known) what it was doing.
3. **Planned next steps** — what the tracker/docs say is queued, grouped by theme.
4. **Recommended next steps** — a short ordered list with a one-line reason each. Flag blockers, stale worktrees/branches, and tickets that look closeable.

State what you couldn't determine rather than guessing. Skip praise and recap of obvious outcomes.
