# Codex Cloud adapter

Translation layer only. The workflow itself is the dotfiles command files, fetched at one commit by `tools/cloud-workflow-bootstrap.sh`; this file maps the Claude Code conventions those files use onto a Codex Cloud task. It restates no workflow steps. Where a command step has no mapping, stop and report that step; do not improvise a substitute.

## Run protocol

1. Download the bootstrap to a file, then run it, using the same ref for both (`WORKFLOW_REF` defaults to `main`; pin a full SHA for stable runs): `curl -fsSL "https://raw.githubusercontent.com/IdahoEv/dotfiles/${WORKFLOW_REF:-main}/tools/cloud-workflow-bootstrap.sh" -o "$TMPDIR/b.sh" && WORKFLOW_REF="${WORKFLOW_REF:-main}" bash "$TMPDIR/b.sh"`. Do not use process substitution: it turns a failed download into an empty script that exits 0. Stop and report on a non-zero exit or when `workflow_source_commit=` is missing from the output. Never use a cached or remembered copy of the workflow.
2. Add `workflow_bin` to `PATH` so command text such as `start-ticket.sh` and `open-pr.sh` runs unmodified. Keep `workflow_source_commit`.
3. To run `/X <args>`, read `<workflow_root>/dot_claude/commands/X.md` and follow it step by step, applying the table below. Slash commands may only be run from the covered list: `start`, `open-pr`.
4. The project repository's own instructions (`AGENTS.md`, `CLAUDE.md`, `.claude/kickoff-preamble.md`) stay authoritative for ticket, branch, build, and test rules.
5. The PR body, final report, and any ticket comment include `Workflow source: IdahoEv/dotfiles@<workflow_source_commit>`, and the line `Independent review: not performed`. This overrides any command text that limits the PR body; when `open-pr.sh` reports a reused PR, add the lines with `gh pr edit --body` if missing.
6. The `/start` output names `worktree=` and `kickoff=`. Because the launch step is skipped, switch into `worktree=` and read `kickoff=` as the task brief.
7. Report each project check (tests, lint, build) as passed, failed, or not run with the reason, in the PR body and final report. Never imply a check passed unless it ran.
8. There is no interactive user mid-task. Where a command would ask a question or wait for approval, stop and report the decision needed, unless the command itself says to proceed.
9. Stop with the PR open. Never merge or run `/finalize`.

## Construct map

Maintained against the covered commands by `tools/cloud-workflow-adapter.test.sh`: every Claude-only construct they use must have a row, and every row must still occur.

| Construct | Codex behavior |
| --- | --- |
| `/start` | Read and follow `start.md`. |
| `/open-pr` | Read and follow `open-pr.md`. |
| `/finalize` | Not available. Stop and report. |
| `/local-review-cycle` | Not available; independent review is not performed (see protocol 5). Skip any mention. |
| `/github-review-comments` | Not available. Skip; report that review follow-up is manual. |
| `/discuss` | Not available. |
| `/board` | Not available. |
| `--tab-only` | Skip the step that opens a session. The task is already the session. |
| `--no-multi` | Always in effect. Skip the fan-out step to sibling repos. |
| `sibling-worktrees.sh` | Do not run (fan-out is skipped). |
| `GT_LABEL_OVERRIDE` | Do not set. Session labels do not exist here. |
| `GT_LABEL_SLUG_OVERRIDE` | Do not set. The deterministic branch name stands. |
| `agent-phase.sh` | Skip direct calls; scripts that call it already no-op. |
| `session-label.sh` | Skip. |
| `claude agents` | Ignore; there is no agent view. |
| `git push --no-verify` | Skip the no-op push; it only registers a push in the agent view. |
| `github-review-poll.sh` | Skip the poll step; report that no review wait was done. |
| `mcp__shortcut__` | Not available. Shortcut tickets: stop and report. GitHub tickets need no MCP. |
| `--review` | Always `--review none`; independent review is not performed. |
| `--launcher` | Never pass it. No session is launched. |
| `~/.config/local-review-only` | Ignore; `--review none` already applies. |
| `github-review-repair-agent` | Not available. Skip; report that review follow-up is manual. |
| `Co-Authored-By` | Use the attribution line the host/project instructs; if none, omit the trailer. |
| `~/.claude/` | Paths under the home `.claude` do not exist here. Use the same file under `<workflow_root>/dot_claude/` (names carry chezmoi prefixes such as `executable_`). |
