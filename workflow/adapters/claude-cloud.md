# Claude Code cloud adapter

Translation layer only. The workflow itself is the dotfiles command files, installed into `~/.claude` by `tools/cloud-workflow-bootstrap.sh` with `WORKFLOW_INSTALL=claude`; this file says what differs in a Claude Code cloud session (one fixed checkout, GitHub GraphQL blocked, no iTerm or agent view). It restates no workflow steps. Where a command step has no mapping, stop and report that step; do not improvise a substitute.

Covered: `/start`, `/open-pr`, `/local-review-cycle`, `/github-review-comments`, `/finalize`.

## Run protocol

1. Install the workflow (once per session, or from the environment setup script; it is idempotent): `curl -fsSL "https://raw.githubusercontent.com/IdahoEv/dotfiles/${WORKFLOW_REF:-main}/tools/cloud-workflow-bootstrap.sh" -o "${TMPDIR:-/tmp}/b.sh" && WORKFLOW_INSTALL=claude WORKFLOW_REF="${WORKFLOW_REF:-main}" bash "${TMPDIR:-/tmp}/b.sh"`. Do not use process substitution: it turns a failed download into an empty script that exits 0. Stop and report on a non-zero exit or when `workflow_source_commit=` is missing from the output. Never use a cached or remembered copy of the workflow. Pin `WORKFLOW_REF` to a full SHA for stable runs. The bootstrap needs no access to the repo beyond public files: if the archive download is refused (a session scoped to other repositories gets 403 from `codeload.github.com`), it fetches the files from `raw.githubusercontent.com` and verifies them against `workflow/manifest.txt`. Only if that is also blocked: attach the repo with `add_repo` (`IdahoEv`, `dotfiles`, read access), clone it outside the project checkout as that tool instructs, and rerun with `WORKFLOW_SRC=<clone dir>` added; stop and report if `add_repo` is denied.
2. Put `workflow_shim` and `workflow_bin` first on `PATH` (`export PATH="<workflow_shim>:<workflow_bin>:$PATH"`; a SessionStart hook or `~/.bashrc` already does this when the installer could write them). Keep `workflow_source_commit`. The shim is a `gh` that answers `gh issue|pr|repo ...` over REST, because cloud sessions block GraphQL; use plain `gh` through it and never call `gh api graphql`.
3. To run `/X <args>`, use the installed slash command; if the session started before the install and does not list it, read `<workflow_claude_dir>/commands/X.md` and follow it step by step, applying the table below. `~/.claude/` in command text means `workflow_claude_dir`. Agents and skills are installed alongside; if a named agent is not available as a subagent type, run a `general-purpose` agent with the agent file's body as its brief.
4. The session starts on a harness-assigned branch in the one checkout. `/start` runs `start-ticket.sh <id> --in-place --no-tab`, which checks the deterministic ticket branch out of that checkout instead of creating a worktree; `worktree=` is the current directory. If the environment restricts pushes to its assigned branch and pushing the ticket branch is refused, stop and report; do not push the work to a different branch to get around it.
5. The project repository's own instructions (`AGENTS.md`, `CLAUDE.md`, `.claude/kickoff-preamble.md`) stay authoritative for ticket, branch, build, and test rules.
6. The PR body, final report, and any ticket comment include `Workflow source: IdahoEv/dotfiles@<workflow_source_commit>` (a `manifest-<digest>` value, which the raw fallback reports for a branch ref, is used as is; pin `WORKFLOW_REF` to a full SHA for an exact commit). When `/local-review-cycle` ran, carry its verbatim report summary into the PR body's "Review cycle" note; otherwise include `Independent review: not performed`. Pass each footer line to `open-pr.sh` as `--body-footer "<line>"`. When `open-pr.sh` reports a reused PR, add the lines with `gh pr edit --body` if missing.
7. Report each project check (tests, lint, build) as passed, failed, or not run with the reason, in the PR body and final report. Never imply a check passed unless it ran.
8. Ask the user with `AskUserQuestion` only when the session is attended (`CLAUDE_CODE_SESSION_ATTENDED` is set and not `0`/`false`). Unattended, where a command would ask a question or wait for approval, stop and report the decision needed, unless the command itself says to proceed.
9. After `/open-pr`, stop. Run `/finalize` only when the user says the PR merged. In a cloud session do not run `finalize-run.sh`: it needs a base worktree and a worktree to remove. Run `finalize-check.sh` and stop unless `verdict=ready`; close the ticket (GitHub: for each id in `chain_ids`, if it is still open and the PR body closes it (`Closes #<id>`), `gh issue close <id> --comment "Landed in <pr_merge_commit> (PR #<n>)"`; leave any other open ticket open and report it; Shortcut: the `shortcut` handoff text in `finalize.md`); then `git fetch origin <base>`, check out `<base>`, `git pull --ff-only`, and `git branch -D <branch>`. There is no worktree to remove and no deploy clone.
10. GitHub ticket tracking only. A Shortcut ticket needs `mcp__shortcut__`, which cloud sessions do not have: stop and report.

## Construct map

Maintained against the covered commands by `tools/cloud-workflow-adapter.test.sh`: every Claude-only construct they use must have a row, and every row must still occur.

| Construct | Claude cloud behavior |
| --- | --- |
| `/start` | Read and follow `start.md` with `--in-place` (protocol 4). Skip step 3 (open the session): the current session is the session. Read `kickoff=` as the task brief. |
| `/open-pr` | Read and follow `open-pr.md`. |
| `/finalize` | Read and follow `finalize.md`, with protocol 9 for steps 3–5. |
| `/local-review-cycle` | Read and follow `local-review-cycle.md`. |
| `/github-review-comments` | Read and follow `github-review-comments.md`, with the review-state mappings below. |
| `/discuss` | Not available. Skip any mention. |
| `/pick` | Not available. Skip any mention. |
| `/board` | Not available. Skip any mention. |
| `--tab-only` | Skip the step that opens a session. |
| `--launcher` | Never pass it. No launcher exists here (equivalent to `none`). |
| `--no-watch` | Always pass it: the watcher polls GraphQL, which is blocked here, and there is no desktop to notify. See the `github-review-poll.sh` row for review waits. |
| `--no-multi` | Always in effect. Skip the fan-out step to sibling repos. |
| `sibling-worktrees.sh` | Do not run (fan-out is skipped). |
| `GT_LABEL_OVERRIDE` | Do not set. Session labels do not exist here. |
| `GT_LABEL_SLUG_OVERRIDE` | Do not set. The deterministic branch name stands. |
| `agent-phase.sh` | Skip direct calls; scripts that call it already no-op. |
| `session-label.sh` | Skip. |
| `claude agents` | Ignore; there is no agent view. |
| `--review` | Always `--review none`: the Copilot request goes through GraphQL, which is blocked. To get a Copilot review, call `mcp__github__request_copilot_review` after the PR exists. |
| `review-unattended.sh` | Treat as exit 1 (interactive); cloud sessions never run unattended. |
| `~/.config/local-review-only` | Treat as absent. |
| `--confirm-commits` | Honor it; the question follows protocol 8. |
| `AskUserQuestion` | Native when attended; otherwise protocol 8. |
| `local-review-cycle-manager` | Run as a subagent (protocol 3). |
| `github-review-repair-agent` | Run as a subagent (protocol 3). |
| `github-review-poll.sh` | Do not run: it queries GraphQL. If a review wait is wanted, subscribe with `subscribe_pr_activity` and end the turn; otherwise report that no review wait was done. |
| `github-review-state.sh` | Do not run: it queries GraphQL. Read review state from `mcp__github__pull_request_read` (`get_reviews`, `get_review_comments`, `get_status`). |
| `request-review.sh` | Do not run: it requests the review through GraphQL. For a Copilot re-review call `mcp__github__request_copilot_review`; for the `claude.yml` smoke test, `gh workflow run claude.yml -f pr_number=<N>` is REST and works. |
| `mcp__github__` | Available. Use `pull_request_read` for reviews and threads, `resolve_review_thread` / `add_reply_to_pull_request_comment` for threads; REST `gh api` calls for reactions and replies work as written. Where the skill names `get_pull_request_review_comments`, use `pull_request_read` with method `get_review_comments`. |
| `mcp__shortcut__` | Not available. Stop and report (protocol 10). |
| `Co-Authored-By` | Use the attribution lines the session's own system reminder gives for commits and PRs in place of the global trailer. |
| `~/.claude/` | Means `workflow_claude_dir`. |
