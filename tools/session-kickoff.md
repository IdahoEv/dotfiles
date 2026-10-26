## Discussion session

This session is for discussion, research, and brainstorming, with no ticket and no branch. Don't edit files in this checkout. Acknowledge the topic and wait for the user rather than starting research on your own.

**"Make a ticket" / "file this"** — do step 1 below, report the ticket id, and stop. The user starts the work with `/start <id>` in a new session.

**"Let's code this" / "make a ticket and start coding"** — move this session onto a ticket:

1. Draft the ticket (concrete acceptance criteria and an estimate) and get approval through `AskUserQuestion`, with the full draft in the question. File it with the repo's tracker (`gh issue create` on GitHub, the Shortcut MCP tools on Shortcut).
2. `start-ticket.sh <id> --print-title`, choose a 3–4-word label, then `GT_LABEL_OVERRIDE="<label>" start-ticket.sh <id> --no-tab`. This creates the worktree and branch and marks the ticket in progress; it opens no second session.
3. `EnterWorktree` with `path=<worktree>` from step 2.
4. `session-label.sh --title "[PLAN] <Is|Sc><id> <label>"` (`Is` for GitHub, `Sc` for Shortcut).
5. Present an implementation plan. From here the normal ticket rules apply.

Never create a worktree with raw `git worktree add`, and never edit before step 3.
