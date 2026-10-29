# Codex Cloud adapter

Translation layer only. The workflow itself is the dotfiles command files, fetched at one commit by `tools/cloud-workflow-bootstrap.sh`; this file maps the Claude Code conventions those files use onto a Codex Cloud task. It restates no workflow steps. Where a command step has no mapping, stop and report that step; do not improvise a substitute.

## Run protocol

1. Run `bash <(curl -fsSL https://raw.githubusercontent.com/IdahoEv/dotfiles/main/tools/cloud-workflow-bootstrap.sh)` (add `WORKFLOW_REF=<sha-or-tag>` to pin). Non-zero exit → stop and report the error. Never use a cached or remembered copy of the workflow.
2. Add `workflow_bin` to `PATH` so command text such as `start-ticket.sh` and `open-pr.sh` runs unmodified. Keep `workflow_source_commit`.
3. To run `/X <args>`, read `<workflow_root>/dot_claude/commands/X.md` and follow it step by step, applying the table below. Slash commands may only be run from the covered list: `start`, `open-pr`.
4. The project repository's own instructions (`AGENTS.md`, `CLAUDE.md`, `.claude/kickoff-preamble.md`) stay authoritative for ticket, branch, build, and test rules.
5. The PR body, final report, and any ticket comment include `Workflow source: IdahoEv/dotfiles@<workflow_source_commit>`, and the line `Independent review: not performed`.
6. There is no interactive user mid-task. Where a command would ask a question or wait for approval, stop and report the decision needed, unless the command itself says to proceed.
7. Stop with the PR open. Never merge or run `/finalize`.

## Construct map

Maintained against the covered commands by `tools/cloud-workflow-adapter.test.sh`: every Claude-only construct they use must have a row, and every row must still occur.

| Construct | Codex behavior |
| --- | --- |
| `/start` | Read and follow `start.md`; run only its steps 1, 1a, 2, and 4. |
| `/open-pr` | Read and follow `open-pr.md` with `--no-multi` implied. |
| `/finalize` | Not available. Stop and report. |
| `/local-review-cycle` | Not available; independent review is not performed (see protocol 5). Skip any mention. |
| `/github-review-comments` | Not available. Skip; report that review follow-up is manual. |
| `/discuss` | Not available. |
| `/board` | Not available. |
| `--tab-only` | Skip `start.md` step 3 (opening a session). The task is already the session. |
| `--no-multi` | Always in effect. Skip `open-pr.md` step 4a. |
| `sibling-worktrees.sh` | Do not run (fan-out is skipped). |
| `GT_LABEL_OVERRIDE` | Do not set. Session labels do not exist here. |
| `GT_LABEL_SLUG_OVERRIDE` | Do not set. The deterministic branch name stands. |
| `agent-phase.sh` | Skip direct calls; scripts that call it already no-op. |
| `session-label.sh` | Skip. |
| `claude agents` | Ignore; there is no agent view. |
| `git push --no-verify` | Skip the no-op push; it only registers a push in the agent view. |
| `github-review-poll.sh` | Skip the poll in `open-pr.md` step 5; report that no review wait was done. |
| `mcp__shortcut__` | Not available. Shortcut tickets: stop and report. GitHub tickets need no MCP. |
| `Co-Authored-By` | Use the attribution line the host/project instructs; if none, omit the trailer. |
| `~/.claude/` | Paths under the home `.claude` do not exist here. Use the same file under `<workflow_root>/dot_claude/` (names carry chezmoi prefixes such as `executable_`). |
