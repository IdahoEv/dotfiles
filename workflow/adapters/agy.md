# Antigravity (AGY) adapter

Translation layer only. The workflow itself is the dotfiles command files; this file maps the Claude Code conventions those files use onto Google Antigravity (`agy` / Gemini CLI) sessions. It restates no workflow steps. Where a command step has no mapping, stop and report that step; do not improvise a substitute.

## Run protocol

1. Locate the workflow:
   - **Local AGY session** (running on a host where the dotfiles repository is cloned, e.g. `~/Documents/Development/dotfiles/main` or `~/.local/share/chezmoi`):
     - Set `workflow_root` to that local checkout directory.
     - Set `workflow_bin` to `<workflow_root>/tools` (or `~/.local/bin`).
     - Resolve `workflow_source_commit=$(git -C "$workflow_root" rev-parse HEAD)`.
     Do not download the tarball or invoke the remote bootstrap script when running on the host.
   - **Remote / Cloud AGY session** (isolated container or sandbox without local dotfiles):
     - Download the bootstrap to a file, then run it, using the same ref for both (`WORKFLOW_REF` defaults to `main`; pin a full SHA for stable runs): `curl -fsSL "https://raw.githubusercontent.com/IdahoEv/dotfiles/${WORKFLOW_REF:-main}/tools/cloud-workflow-bootstrap.sh" -o "${TMPDIR:-/tmp}/b.sh" && WORKFLOW_REF="${WORKFLOW_REF:-main}" bash "${TMPDIR:-/tmp}/b.sh"`. Do not use process substitution: it turns a failed download into an empty script that exits 0. Stop and report on a non-zero exit or when `workflow_source_commit=` is missing from the output. Never use a cached or remembered copy of the workflow.
2. Add `workflow_bin` to `PATH` so command text such as `start-ticket.sh` and `open-pr.sh` runs unmodified. Keep `workflow_source_commit`.
3. Tool execution in AGY:
   - Run shell commands using `run_command`. Attempt sandboxed execution first; retry with `BypassSandbox: true` if blocked by network or authentication requirements (e.g., `gh`).
   - Use `read_file`, `write_file`, and `edit_file` for file operations.
   - Subagents (`invoke_subagent`, `define_subagent`) are available in AGY, but independent review subagents are not mapped in this v1 protocol.
4. To run `/X <args>`, read `<workflow_root>/dot_claude/commands/X.md` (or deployed `~/.claude/commands/X.md`) and follow it step by step, applying the table below. Slash commands may only be run from the covered list: `start`, `open-pr`.
5. The project repository's own instructions (`AGENTS.md`, `CLAUDE.md`, `.claude/kickoff-preamble.md`) stay authoritative for ticket, branch, build, and test rules.
6. The PR body, final report, and any ticket comment include `Workflow source: IdahoEv/dotfiles@<workflow_source_commit>`, and the line `Independent review: not performed`. This overrides any command text that limits the PR body; when `open-pr.sh` reports a reused PR, add the lines with `gh pr edit --body` if missing.
7. The `/start` output names `worktree=` and `kickoff=`. Because the session launch step is skipped, switch into `worktree=` (set working directory) and read `kickoff=` as the task brief.
8. Report each project check (tests, lint, build) as passed, failed, or not run with the reason, in the PR body and final report. Never imply a check passed unless it ran.
9. Interactive prompts: In an interactive AGY session, use `ask_question` or user chat when human input is requested. In automated/headless execution, where a command would ask a question or wait for approval, stop and report the decision needed, unless the command itself says to proceed.
10. Stop with the PR open. Never merge or run `/finalize`.

## Construct map

Maintained against the covered commands by `tools/cloud-workflow-adapter.test.sh`: every Claude-only construct they use must have a row, and every row must still occur.

| Construct | AGY behavior |
| --- | --- |
| `/start` | Read and follow `start.md` using `run_command` and file tools. |
| `/open-pr` | Read and follow `open-pr.md` using `run_command` and file tools. |
| `/finalize` | Not available. Stop and report. |
| `/local-review-cycle` | Not available; independent review is not performed (see protocol 6). Skip any mention. |
| `/github-review-comments` | Not available. Skip; report that review follow-up is manual. |
| `/discuss` | Not available. |
| `/board` | Not available. |
| `--tab-only` | Skip the step that opens a session. The AGY task is already the session. |
| `--no-multi` | Always in effect. Skip the fan-out step to sibling repos. |
| `sibling-worktrees.sh` | Do not run (fan-out is skipped). |
| `GT_LABEL_OVERRIDE` | Do not set. Session labels do not exist here. |
| `GT_LABEL_SLUG_OVERRIDE` | Do not set. The deterministic branch name stands. |
| `agent-phase.sh` | Skip direct calls; scripts that call it already no-op. |
| `session-label.sh` | Skip. |
| `claude agents` | Ignore; there is no Claude agent view. |
| `git push --no-verify` | Skip the no-op push; it only registers a push in the Claude agent view. |
| `github-review-poll.sh` | Skip the poll step; report that no review wait was done. |
| `mcp__shortcut__` | Not available. Shortcut tickets: stop and report. GitHub tickets need no MCP. |
| `--review` | Always `--review none`; independent review is not performed. |
| `--launcher` | Never pass it. No session is launched. |
| `~/.config/local-review-only` | Ignore; `--review none` already applies. |
| `github-review-repair-agent` | Not available. Skip; report that review follow-up is manual. |
| `Co-Authored-By` | Use the attribution line the host/project instructs; if none, omit the trailer. |
| `~/.claude/` | Paths under `~/.claude/` may exist in local environments; for repository or remote runs, use `<workflow_root>/dot_claude/` (names carry chezmoi prefixes such as `executable_`). |
