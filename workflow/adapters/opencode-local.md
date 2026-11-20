# Local OpenCode adapter

Run the existing command and agent procedures from the local dotfiles checkout under OpenCode. This adapter covers interactive TUI sessions on the shared background server; multi-session access uses OpenCode session tabs, not tmux. Canonical procedures are read as-is from `dot_claude/` — nothing is forked, so improvements to the Claude workflow flow through unchanged.

## Run protocol

1. Resolve `workflow_root` from this file's checkout, `workflow_bin=<workflow_root>/tools`, and `workflow_source_commit` with `git -C <workflow_root> rev-parse HEAD`. Use these tools by absolute path or prepend `workflow_bin` to PATH. Never download the cloud bootstrap locally.
2. Read `<workflow_root>/dot_claude/commands/<command>.md`, then apply the mappings below. Covered commands: governor, groom, pick, start, discuss, local-review-cycle, open-pr, github-review-comments, finalize, merge, land, sync. `$ARGUMENTS` is the user's invocation text. OpenCode natively discovers skills under `~/.claude/skills/` and loads `~/.claude/CLAUDE.md`; commands and agents under `~/.claude/` are not discovery sources — read those canonical files by path. Slash syntax in canonical procedures refers to these files, not a promise that OpenCode registers custom slash commands.
3. Project AGENTS.md, CLAUDE.md, kickoff preambles, overlays, approval gates, and test instructions remain authoritative. Report every check as passed, failed, or not run with its reason. Never imply a check passed unless it ran. PRs include `Workflow source: IdahoEv/dotfiles@<workflow_source_commit>` through `--body-footer`.
4. Before governor, groom, or pick selection, run `opencode session list --format json` in each candidate worktree (the list is project-scoped), `git worktree list`, and inspect open PRs. Treat recorded workstreams as taken even if their sessions are absent. Sessions live on the shared per-user server, but tabs are client-scoped: another device's open tabs are not visible here. Failure to discover activity stops selection; do not infer an idle worktree.
5. Use persistent sessions on the shared server for independent workstreams; these are root sessions, not subagents of the governor. Launch from the worktree with `opencode run --title '<label>' '<kickoff>'`; the session persists after the run and the user opens it in a tab with Ctrl+O. There is no plan-mode switch: approval gates use the question tool, and the user's explicit approval reaches a running session as a follow-up message (`opencode run --session <id> '<approval>'`). Never self-approve.
6. Memory-guard blocks are blocking: stop remaining groups, report the guard output and any completed setup, and never set `MEM_GUARD_OVERRIDE` or pass `--force` yourself. Only the user may authorize an override. Launch failures are blocking for that group. A recorded session may already be running: inspect it before retrying; `opencode run --session <id>` continues it without duplicating the kickoff. `start 12,13,14 15` runs each space group independently in order; a setup/launch failure stops before the next group. The existing start script owns providers, ordered IDs, worktrees and naming. Chains remain GitHub-only. State repair and tracker enrichment still follow start.md.

## Construct map

| Construct | Local OpenCode behavior |
| --- | --- |
| `/governor` | Follow governor.md in the primary worktree; use session lists, worktrees, and PRs for discovery per protocol 4. |
| `/pick` | Follow pick.md's selection rules using the discovery checks in protocol 4. |
| `/add-dir` | Ask the user to make the required directory available (open or move a session there) and wait; never work around unavailable paths. |
| `/start` | Follow start.md, retaining setup, state verification, enrichment and reporting. |
| `--tab-only` | Replace the launch call with the protocol 5 `opencode run` launch from the worktree. Never move the governor into that worktree. |
| `--launcher` | For discuss.md's `--session` call only, pass `--launcher none`, then launch the returned dir/kickoff per protocol 5 with a talk label. Other start calls keep `--no-tab`; no Claude launcher runs. |
| `/discuss` | Follow discuss.md through the preceding mapping. A new independent session keeps discussion out of governor context; revisit it by session ID. |
| `ListAgents` | Use `opencode session list --format json` per worktree plus git worktrees and open PRs, per protocol 4. |
| `ExitWorktree` | Use `session_move` for deliberate relocation; honor the governor's prohibition — never move the governor out of its primary checkout. |
| `/local-review-cycle` | Follow local-review-cycle.md; launch a fresh manager subagent as specified below and wait for its complete report. Never review or triage inline as a fallback. |
| `local-review-cycle-manager` | Launch with the subagent tool as a delegation-capable agent, fresh context (the built-in `general` cannot launch subagents; use a custom agent with `subagent` permission allowed, e.g. `workflow-manager`). Its task is to read `dot_claude/agents/local-review-cycle-manager.md`, `dot_claude/skills/local-review-cycle-procedure/SKILL.md`, and this adapter under workflow_root. Add only the canonical kickoff fields and resolved workflow paths. Its reviewer fan-out requires `experimental.subagent_depth` of at least 2. It owns cycle edits, tests, local commits and telemetry; never pushes or writes to GitHub. |
| `github-review-repair-agent` | Use a fresh general subagent; point it to `dot_claude/agents/github-review-repair-agent.md`, `dot_claude/skills/github-review-procedure/SKILL.md`, `dot_claude/skills/reviewer-contract/SKILL.md`, and this adapter under workflow_root, plus only canonical repo/PR/branch/cwd fields. It edits and validates; the parent owns approval, commits, push and GitHub actions. |
| `/github-review-comments` | Follow the canonical command: Automatic delegates one fresh repair round; Quick/Slow load the procedure inline. Preserve the opt-in unattended switch and round cap. |
| `AskUserQuestion` | Use the `question` tool with the full proposal in its question text. Wait for an explicit answer before dependent actions; never assume approval. Child sessions have no question tool: a subagent needing a decision reports it to the parent, which asks. |
| `/open-pr` | Follow open-pr.md and its provider conventions; invoking it authorizes its commit/push/PR actions. |
| `sibling-worktrees.sh` | Discover as written; launch each sibling with the protocol 5 session launch. Report per-sibling failures. Never ship the sibling inline. |
| `--no-multi` | Honor as written. |
| `--no-watch` | Honor as written. The local watcher can notify; it does not automatically run an OpenCode repair session. |
| `--review` | Honor as written, including provider and local-review-only defaults. Never substitute `none` to hide unsupported review. |
| `--confirm-commits` | Preserve the manager's approval checkpoint and full proposed message. |
| `GT_LABEL_OVERRIDE` | Preserve the head-title label decision during setup; the session title carries the label. |
| `GT_LABEL_SLUG_OVERRIDE` | Honor only an explicitly requested deterministic branch override. |
| `session-label.sh` | Claude's script no-ops here. Name the session with `session_rename` (or Ctrl+R in the TUI). |
| `agent-phase.sh` | Run canonical bookkeeping when requested; Claude agent-view updates no-op. Set the phase prefix on the session title with `session_rename`; there is no automatic phase synchronization. |
| `github-review-state.sh` | Claude statusline only; use wf-event/pr-body's review records for authoritative cycle totals. |
| `claude agents` | Use session tabs plus `opencode session list`; tabs are client-scoped and there is no server-wide phase dashboard. State the visibility limits. |
| `github-review-poll.sh` | Run the canonical poll in the background when available; wait for completion, then follow the command. A notification alone does not process comments. |
| `review-unattended.sh` | Honor the existing machine opt-in and cap. |
| `request-review.sh` | Run as written; blocked GraphQL is reported, never silently treated as a re-request. |
| `~/.config/local-review-only` | Honor as written. |
| `mcp__github__` | Use available GitHub tools or gh as the canonical procedure permits. |
| `mcp__shortcut__` | Require the actual Shortcut tools for enrichment/state repair/closure; stop those operations clearly when unavailable. Single-ticket preparation may use the installed provider; chains remain GitHub-only. |
| `~/.claude/` | Resolve canonical command and agent paths under `<workflow_root>/dot_claude/`. Skills and the global CLAUDE.md are discovered natively from `~/.claude/`; commands and agents are not. Keep project-local .claude/ paths and overlays unchanged. |
| `Co-Authored-By` | Use the project's configured OpenCode attribution; otherwise omit. Never invent an identity or copy Claude attribution. |
| `/merge` | Follow merge.md and merge-run.sh as written. A blocked gate stops; never commit, push, pull or sync to repair it without the user requesting that action. |
| `/land` | Follow land.md: load merge.md in full, and run finalize.md only after merge-run.sh exits 0. Apply the OpenCode finalize mapping below, including the manual session handoff. |
| `/sync` | Follow sync.md and sync-run.sh as written, including conflict resolution, tests for risky resolutions, and --finish recovery. Never force-push after a push failure. |
| `/finalize` | Follow finalize.md and finalize-run.sh's safe verdicts. The script does not dispose OpenCode sessions: after successful cleanup, report session IDs for manual close or `opencode session delete`; never call claude rm. Locked/ambiguous cleanup remains a handoff. |
| `/board` | Unsupported; use session tabs plus session lists and report their visibility limits. |

## Independent review

The manager discovers reviewers in all canonical tiers, dedupes by name, and selects by `use_when:`. Spawn each selected reviewer as a fresh subagent (subagents always start with fresh context), pointing it to its actual agent file, every frontmatter skill, this adapter, and the canonical diff/ticket/triage fields. Tier-2 reviewers always load reviewer-contract. Launch independent reviewers in batches within available capacity; never inherit implementer or manager history. Subagents run in the background: wait for each completion notification and its complete output before triage. For a fresh PR-draft agent, use the same isolation and the canonical pinned SHA.

Claude model aliases such as sonnet/auto are host hints, not OpenCode model IDs. Inherit the configured OpenCode model and record the actual launch model (or `configured`, if unavailable), never claim a Claude model ran. Explicit model requirements with no available mapping stop for a decision. Reviewer read-only scope is enforced by its canonical contract; the manager and repair boundaries are unchanged. Reviewer fan-out requires `experimental.subagent_depth` of at least 2 and a delegation-capable manager agent: the built-in `general` subagent cannot launch subagents at any depth, so the manager runs as a custom agent with `subagent` permission allowed (e.g. `workflow-manager`); leaf reviewers may be `general`. If fresh delegation or nested reviewer launches are unavailable, stop with independent review not performed; do not open a PR claiming review passed.

## Visibility and guards

OpenCode has no statusline, agent view, or Claude hooks. Workflow phase lives only in session titles set through the mappings above; Claude transcript token telemetry is not synchronized. The no-cd-write PreToolUse guard is not enforced under OpenCode until a plugin ports it; the rule in the global CLAUDE.md remains authoritative — never mix `cd` with a redirect or write in one command. Existing review events and PR review records still work.

Friction goes in `docs/friction/<environment>.md` (e.g. `opencode-local`); from another repo, file an intake issue titled `[<environment>] <friction>`.
