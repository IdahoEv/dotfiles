---
description: Open a non-ticket session to discuss, research, or brainstorm a topic in this project
argument-hint: <topic> [short description]
---

# Discuss

Opens a `[TALK]` session for this project in its main checkout, with no ticket, branch, or
worktree. If the discussion leads to code, that session files a ticket and moves itself
onto the ticket's worktree; its kickoff carries the rules.

1. From `$ARGUMENTS`, write a **3–4-word title-cased label** naming the topic (same rule
   as `/start`'s Naming section). Any further description goes to `--about` verbatim.
   No arguments → no label; the script names it `<project> Discussion`.
2. Run:
   ```bash
   start-ticket.sh --session "<label>" [--about "<description>"]
   ```
   Never pass `--launcher`. Output is `dir= kickoff= label=`.
3. Report the label and launcher as `/start` step 3 describes: under `bg` the session is in
   `claude agents` as `[TALK] <label>`; under `iterm` a tab holds the unsubmitted kickoff;
   under `none` give the `dir` and `kickoff` paths.

Don't hold the discussion here.

$ARGUMENTS
