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
   - Subagents (`invoke_subagent`, `define_subagent`) are used to run isolated orchestrator, leaf reviewer, and PR repair agents (`local-review-cycle-manager`, `*-reviewer`, and `github-review-repair-agent`).
4. To run `/X <args>`, read `<workflow_root>/dot_claude/commands/X.md` (or deployed `~/.claude/commands/X.md`) and follow it step by step, applying the table below. Slash commands may only be run from the covered list: `start`, `local-review-cycle`, `open-pr`, `github-review-comments`, `governor`, `pick`, `discuss`, `remind`.
5. The project repository's own instructions (`AGENTS.md`, `CLAUDE.md`, `.claude/kickoff-preamble.md`) stay authoritative for ticket, branch, build, and test rules.
6. The PR body, final report, and any ticket comment include `Workflow source: IdahoEv/dotfiles@<workflow_source_commit>`. When `/local-review-cycle` ran, carry its verbatim report summary into the PR body's "Review cycle" note; when it was skipped or not performed (e.g., remote unreviewed runs), include `Independent review: not performed`. Pass each footer line to `open-pr.sh` as `--body-footer "<line>"`. When `open-pr.sh` reports a reused PR, add the lines with `gh pr edit --body` if missing.
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
| `/local-review-cycle` | Read and follow `local-review-cycle.md` using `run_command` and subagent tools. |
| `/github-review-comments` | Read and follow `github-review-comments.md` using `run_command`, file tools, and subagent tools (in Quick or Slow mode, load `skills/github-review-procedure/SKILL.md` inline in the current session; in Automatic mode, launch `github-review-repair-agent` and retain parent ownership of commits, push, and GitHub thread writes). |
| `/discuss` | Read and follow `discuss.md` using `run_command` (`start-ticket.sh --session ... --launcher none`); report `dir=`, `kickoff=`, and `label=` instead of opening a Claude tab or session. |
| `/governor` | Read and follow `governor.md` using `run_command` and file tools; stay in the primary worktree and end the first turn with a plain-text readiness line. |
| `/pick` | Read and follow `pick.md` using `run_command` (`git worktree list`, `gh`) and file tools. |
| `/board` | Not available. |
| `ExitWorktree` | Not available; stay in the primary worktree without switching branches or directories. |
| `/add-dir` | Not available; ask the user to add the workspace/directory to the AGY session and wait. |
| `ListAgents` | Not available; rely on `git worktree list` and `gh pr list` to discover in-flight work. |
| `--tab-only` | Skip the step that opens a session. The AGY task is already the session. |
| `--no-watch` | Always pass it. The detached watcher and its macOS notification are local-Claude machinery; follow the `github-review-poll.sh` row for review waits. |
| `--no-multi` | Always in effect. Skip the fan-out step to sibling repos. |
| `--confirm-commits` | Honour as written; pass through in the `local-review-cycle-manager` kickoff. |
| `sibling-worktrees.sh` | Do not run (fan-out is skipped). |
| `GT_LABEL_OVERRIDE` | Do not set. Session labels do not exist here. |
| `GT_LABEL_SLUG_OVERRIDE` | Do not set. The deterministic branch name stands. |
| `agent-phase.sh` | Skip direct calls; scripts that call it already no-op. |
| `github-review-state.sh` | Skip direct `--set-local` statusline calls; `wf-event.sh review.result` records the final round count. |
| `session-label.sh` | Skip. |
| `AskUserQuestion` | Follow protocol 9: in interactive sessions use `ask_question` with self-contained context; in headless/Telegram sessions print the self-contained question and options at the end of the turn and wait. |
| `claude agents` | Ignore; there is no Claude agent view. |
| `github-review-poll.sh` | In interactive CLI sessions, run in the background via `run_command` and re-invoke `/github-review-comments` on exit 0; in single-turn headless/Telegram or remote runs, skip the poll step and report that review polling is manual. |
| `mcp__shortcut__` | Not available. Shortcut tickets: stop and report. GitHub tickets need no MCP. |
| `mcp__github__` | Not required; use the `gh` CLI (`gh api ...`) via `run_command` as preferred by `github-review-procedure`. |
| `--review` | Honour as written (`open-pr.sh` defaults to `none` when `~/.config/local-review-only` exists). |
| `--launcher` | Pass `--launcher none` for `/discuss` (`start-ticket.sh --session`); for `/start` (`--tab-only` is skipped), no session is launched. |
| `review-unattended.sh` | When the script is absent, treat as exit 1 (interactive). Otherwise honour as written; unattended mode is opt-in per machine via `~/.config/github-review-unattended`. |
| `~/.config/local-review-only` | Honour as written (`open-pr.sh` checks it automatically). |
| `local-review-cycle-manager` | Define via `define_subagent` (`EnableWriteTools: true`, `EnableSubagentTools: true`, system prompt from `agents/local-review-cycle-manager.md` + `skills/local-review-cycle-procedure/SKILL.md` + `workflow/adapters/agy.md`, passing resolved `workflow_root` and `workflow_bin`) and launch via `invoke_subagent`. Inside the manager, define each reviewer selected under `local-review-cycle-procedure` §2 (all three discovery tiers: `.claude/agents/`, `docs/local/reviewers/` or project-overlay `claude/agents/`, and `dot_claude/agents/`) via `define_subagent` with `EnableWriteTools: false` and system prompt from the reviewer file body plus every skill in its `skills:` frontmatter (`skills/<skill>/SKILL.md`, e.g. `reviewer-contract`, `prompt-review`, `security-review-rubric`; always include `skills/reviewer-contract/SKILL.md` for tier-2 reviewers), then invoke in parallel via `invoke_subagent`. |
| `github-review-repair-agent` | Define via `define_subagent` (`EnableWriteTools: true`, `EnableSubagentTools: false`, system prompt from `agents/github-review-repair-agent.md` + `skills/github-review-procedure/SKILL.md` + `skills/reviewer-contract/SKILL.md` + `workflow/adapters/agy.md`, passing resolved `workflow_root` and `workflow_bin`) and launch via `invoke_subagent` for one Automatic Mode round. The subagent edits files and runs validation only — never commits, pushes, or writes to GitHub; the parent session owns commit approval (`AskUserQuestion`), `git commit`, `git push`, and posting/resolving planned GitHub actions. |
| `Co-Authored-By` | Use the attribution line the host/project instructs; if none, omit the trailer. |
| `~/.claude/` | Paths under `~/.claude/` may exist in local environments; for repository or remote runs, use `<workflow_root>/dot_claude/` (names carry chezmoi prefixes such as `executable_`). |
| `request-review.sh` | Run as written (needs `gh` with GraphQL access); if GraphQL is blocked, stop and report that the re-request is manual. |
