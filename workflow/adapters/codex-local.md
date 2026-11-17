# Local Codex CLI adapter

Run the existing command and agent procedures from the local dotfiles checkout. This adapter covers interactive CLI sessions with a shared local daemon; cloud sessions continue using `codex.md`.

## Run protocol

1. Resolve `workflow_root` from this file's checkout, `workflow_bin=<workflow_root>/tools`, and `workflow_source_commit` with `git -C <workflow_root> rev-parse HEAD`. Use these tools by absolute path or prepend `workflow_bin` to PATH. Never download the cloud bootstrap locally.
2. Read `<workflow_root>/dot_claude/commands/<command>.md`, then apply the mappings below. Covered commands: governor, groom, pick, start, discuss, local-review-cycle, open-pr, github-review-comments, finalize, merge, land, sync. `$ARGUMENTS` is the user's invocation text. Skills named for each command are discoverable under `~/.codex/skills/`; `$start 12,13 14` invokes the start skill. Slash syntax in canonical procedures refers to these skills, not a promise that Codex registers custom slash commands.
3. Project AGENTS.md, CLAUDE.md, kickoff preambles, overlays, approval gates, and test instructions remain authoritative. Report every check as passed, failed, or not run with its reason. Never imply a check passed unless it ran. PRs include `Workflow source: IdahoEv/dotfiles@<workflow_source_commit>` through `--body-footer`.
4. Before governor, groom, or pick selection, run `codex-workflow.sh status --dir <project>`, `git worktree list`, and inspect open PRs. Treat recorded workstreams as taken even if their sessions are absent. Relay the visibility limitation printed by status. Failure to discover activity stops selection; do not infer an idle worktree.
5. Use the native daemon for independent workstreams; these are persistent root threads, not subagents of the governor. `codex-workflow.sh launch` inherits the user's Codex model and permissions, submits in plan mode, and returns a UUID. Use `codex agents` or `codex resume <UUID>` to address it. Approval must switch out of plan mode: in its TUI use `/plan`, or send the user's explicit approval with `codex-workflow.sh send <UUID> '<approval>' --implement`. Plain `send` preserves the mode. Never switch mode on the governor's own initiative.
6. Memory-guard blocks are blocking: stop remaining groups, report the guard output and any completed setup, and never set `MEM_GUARD_OVERRIDE` or pass `--force` yourself. Only the user may authorize an override. Launch failures are blocking for that group. A returned or recorded UUID may already be running: inspect it before retrying. Re-running a recorded ticket launch returns its UUID without submitting another kickoff. `start 12,13,14 15` runs each space group independently in order; a setup/launch failure stops before the next group. The existing start script owns providers, ordered IDs, worktrees and naming. Chains remain GitHub-only. State repair and tracker enrichment still follow start.md.

## Construct map

| Construct | Local Codex behavior |
| --- | --- |
| `/governor` | Follow governor.md in the primary worktree; use native status, worktrees, and PRs for discovery. |
| `/pick` | Follow pick.md's selection rules using the discovery checks in protocol 4. |
| `/add-dir` | Ask the user to add the required directory to this session and wait; never work around unavailable paths. |
| `/start` | Follow start.md, retaining setup, state verification, enrichment and reporting. |
| `--tab-only` | Replace the launch call with `<workflow_bin>/codex-workflow.sh launch --dir <worktree> --kickoff <kickoff>`. Never switch the governor into that worktree. |
| `--launcher` | For discuss.md's `--session` call only, pass `--launcher none`, then launch the returned dir/kickoff with `--kind talk --name <label>`. Other start calls keep `--no-tab`; no Claude launcher runs. |
| `/discuss` | Follow discuss.md through the preceding mapping. A new independent thread keeps discussion out of governor context; revisit its UUID. |
| `ListAgents` | Use `codex-workflow.sh status` plus git worktrees and open PRs, per protocol 4. |
| `ExitWorktree` | Honor the governor's prohibition. Independent ticket threads use their own worktree; never move the governor out of its primary checkout. |
| `/local-review-cycle` | Follow local-review-cycle.md; launch a fresh manager as specified below and wait for its complete report. Never review or triage inline as a fallback. |
| `local-review-cycle-manager` | Use `collaboration.spawn_agent` with `agent_type=default`, `fork_turns=none`; its task is to read `dot_claude/agents/local-review-cycle-manager.md`, `dot_claude/skills/local-review-cycle-procedure/SKILL.md`, and this adapter under workflow_root. Add only the canonical kickoff fields and resolved workflow paths. It owns cycle edits, tests, local commits and telemetry; never pushes or writes to GitHub. |
| `github-review-repair-agent` | Use a fresh default agent with `fork_turns=none`; point it to `dot_claude/agents/github-review-repair-agent.md`, `dot_claude/skills/github-review-procedure/SKILL.md`, `dot_claude/skills/reviewer-contract/SKILL.md`, and this adapter under workflow_root, plus only canonical repo/PR/branch/cwd fields. It edits and validates; the parent owns approval, commits, push and GitHub actions. |
| `/github-review-comments` | Follow the canonical command: Automatic delegates one fresh repair round; Quick/Slow load the procedure inline. Preserve the opt-in unattended switch and round cap. |
| `AskUserQuestion` | Use the available structured user-input tool with the full proposal in its question. Wait for an explicit answer before dependent actions. If no question tool exists, report the required decision and stop; never assume approval. |
| `/open-pr` | Follow open-pr.md and its provider conventions; invoking it authorizes its commit/push/PR actions. |
| `sibling-worktrees.sh` | Discover as written; launch each sibling with the Codex launch mapping. Report per-sibling failures. Never ship the sibling inline. |
| `--no-multi` | Honor as written. |
| `--no-watch` | Honor as written. The local watcher can notify; it does not automatically run a Codex repair session. |
| `--review` | Honor as written, including provider and local-review-only defaults. Never substitute `none` to hide unsupported review. |
| `--confirm-commits` | Preserve the manager's approval checkpoint and full proposed message. |
| `GT_LABEL_OVERRIDE` | Preserve the head-title label decision during setup; the workstream row renderer supplies the native session name. |
| `GT_LABEL_SLUG_OVERRIDE` | Honor only an explicitly requested deterministic branch override. |
| `session-label.sh` | Claude's script no-ops here. Name the current native thread with `codex-workflow.sh name <UUID> '<label>'`; obtain the UUID from CODEX_THREAD_ID or the launch result. No UUID: report that native naming is unavailable. |
| `agent-phase.sh` | Run canonical bookkeeping when requested; Claude agent-view updates no-op. Native phase labels can be set with the name command; there is no automatic phase synchronization. |
| `github-review-state.sh` | Claude statusline only; use wf-event/pr-body's review records for authoritative cycle totals. |
| `claude agents` | Use `codex agents`; no Claude status/color parity is implied. |
| `github-review-poll.sh` | Run the canonical poll in the background when available; wait for completion, then follow the command. A notification alone does not process comments. |
| `review-unattended.sh` | Honor the existing machine opt-in and cap. |
| `request-review.sh` | Run as written; blocked GraphQL is reported, never silently treated as a re-request. |
| `~/.config/local-review-only` | Honor as written. |
| `mcp__github__` | Use available GitHub tools or gh as the canonical procedure permits. |
| `mcp__shortcut__` | Require the actual Shortcut tools for enrichment/state repair/closure; stop those operations clearly when unavailable. Single-ticket preparation may use the installed provider; chains remain GitHub-only. |
| `~/.claude/` | Resolve canonical command, agent and skill paths under `<workflow_root>/dot_claude/`. Keep project-local .claude/ paths and overlays unchanged. |
| `Co-Authored-By` | Use the project's configured Codex attribution; otherwise omit. Never invent an identity or copy Claude attribution. |
| `/merge` | Follow merge.md and merge-run.sh as written. A blocked gate stops; never commit, push, pull or sync to repair it without the user requesting that action. |
| `/land` | Follow land.md: load merge.md in full, and run finalize.md only after merge-run.sh exits 0. Apply the Codex finalize mapping below, including manual native-thread archival. |
| `/sync` | Follow sync.md and sync-run.sh as written, including conflict resolution, tests for risky resolutions, and --finish recovery. Never force-push after a push failure. |
| `/finalize` | Follow finalize.md and finalize-run.sh's safe verdicts. The script does not dispose native Codex threads: after successful cleanup, report the UUID for manual `codex archive <UUID>`; never call claude rm. Locked/ambiguous cleanup remains a handoff. |
| `/board` | Unsupported; use native agents plus status and report their visibility limits. |

## Independent review

The manager discovers reviewers in all canonical tiers, dedupes by name, and selects by `use_when:`. Spawn each selected reviewer with a fresh context (`fork_turns=none`), pointing it to its actual agent file, every frontmatter skill, this adapter, and the canonical diff/ticket/triage fields. Tier-2 reviewers always load reviewer-contract. Launch independent reviewers in batches within available capacity; never inherit implementer or manager history. Wait for complete outputs before triage. For a fresh PR-draft agent, use the same isolation and the canonical pinned SHA.

Claude model aliases such as sonnet/auto are host hints, not Codex model IDs. Inherit the configured Codex model and record the actual launch model (or `configured`, if unavailable), never claim a Claude model ran. Explicit model requirements with no available mapping stop for a decision. Reviewer read-only scope is enforced by its canonical contract; the manager and repair boundaries are unchanged. If fresh delegation or nested reviewer launches are unavailable, stop with independent review not performed; do not open a PR claiming review passed.

Native daemon runtime status is observable; workflow phase/color and Claude transcript token telemetry are not synchronized. Existing review events and PR review records still work. Cloud/desktop parity and AGY's tmux dashboard are outside this adapter.
