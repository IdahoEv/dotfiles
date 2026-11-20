# Local Codex CLI workflow

Use the existing dotfiles workflow from independent local Codex sessions. Ticket chains share one worktree, thread and PR; space-separated groups launch separate threads. The native daemon provides session discovery and resume; tmux is optional.

## Use

After merging, pull the dotfiles deploy clone and apply the named `~/.codex/skills/<command>/SKILL.md` targets with chezmoi. The existing link-tools apply script exposes `codex-workflow.sh` on PATH. Restart Codex to discover new skills. Before deployment, invoke the helper by absolute path from this worktree.

```text
$governor
$groom
$pick
$start 12,13,14 15
$discuss Cache Invalidation
$local-review-cycle
$open-pr
$github-review-comments
$sync
$merge
$land
$finalize
```

`$merge` runs the local sync gate before merging; a blocked gate stops for the user. `$land` merges, then finalizes only on success. `$sync` brings in the base and pushes, handing conflicts to the session under the canonical test and recovery rules. Land uses the same manual native-thread archive handoff as finalize.

These skills load [canonical procedures](../dot_claude/commands/) through the [local adapter](../workflow/adapters/codex-local.md). They do not register custom native slash commands. `codex-workflow.sh instructions <command>` prints the corresponding file pointers.

```sh
codex-workflow.sh start 12,13,14 15
codex-workflow.sh status --dir /absolute/project
codex agents
codex resume <UUID>
codex-workflow.sh send <UUID> 'Approved; implement the plan' --implement
codex-workflow.sh discuss 'Cache Invalidation' --about 'Compare the proposed strategies'
```

The shell start shortcut prepares and launches groups; use the start skill when tracker enrichment or state repair is needed. Start uses the existing provider and worktree manager. Ordered IDs, naming and metadata stay in `.workstream.json`; `codex_sessions` records the persistent UUID. Repeating a recorded launch returns that UUID without resubmitting. On failure, inspect the printed UUID before retrying. A failed group stops subsequent launches.

Launches use the shared [memory guard](memory-guard.md): each group is checked before setup and every new thread before creation. A block stops subsequent groups; completed setup is reported for recovery. Missing or crashing guards warn and continue. Only the user may explicitly override with `MEM_GUARD_OVERRIDE=1`; child processes do not inherit it.

Threads start in plan mode and inherit the user's model and permissions. Approve within the resumed TUI and switch to default mode, or use `send --implement` with explicit approval. Plain `send` preserves the mode. Discussion threads have their own UUIDs and do not consume governor context.

## Differences

| Area | Local Codex behavior |
| --- | --- |
| Requirements | Python 3.11+, Git, configured Codex CLI with native app-server daemon/version and Unix WebSocket support; provider credentials as before |
| Tested installation | CLI 0.166.0; running daemon 0.169.0 |
| Review | Fresh manager/reviewer contexts; unsupported delegation stops review explicitly |
| Models | Configured Codex model; Claude aliases do not select Codex models |
| Visibility | Non-archived interactive threads on this daemon; worktrees/PRs supplement it; no Claude/AGY/remote-daemon activity inference |
| Lifecycle | Native runtime status; no automatic phase/color synchronization or Claude token telemetry |
| Approvals | Native permission controls plus the canonical human checkpoints; pending requests are handled in the TUI |
| Providers | Existing provider setup; Shortcut repair/closure requires its actual MCP tools; chains are GitHub-only |
| Finalize | Existing safe cleanup checks; native transcript remains for manual `codex archive <UUID>` after successful cleanup |
| Other hosts | Existing [Codex cloud adapter](../workflow/adapters/codex.md) unchanged; AGY dashboard work stays separate |

## Validation

The [smoke record](codex-cli-smoke.md) distinguishes real daemon/CLI observations from fixtures. Automated launch, failure, protocol and regression checks run with:

```sh
python3 -m unittest discover -s tools/lib -p '*_test.py'
bash tools/start-ticket.test.sh
bash tools/cloud-workflow-adapter.test.sh
bash tools/cloud-workflow-bootstrap.test.sh
```
