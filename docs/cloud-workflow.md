# Cloud workflow

Cloud agents (Claude Code cloud sessions, Codex Cloud, and Google Antigravity / AGY) run the dotfiles' own command files (`dot_claude/commands/*.md`) through a per-host adapter. No workflow steps are restated here or in the adapter, so editing a command changes what cloud agents do on the next run.

| Piece | Path | Role |
| --- | --- | --- |
| Bootstrap | `tools/cloud-workflow-bootstrap.sh` | Resolves `WORKFLOW_REF` (default `main`) to a commit SHA, fetches the repo as one tarball at that SHA, checks required files, exposes `tools/*.sh` on `workflow_bin`, prints `key=value`. Any failure exits non-zero; no cached copy is used. |
| Adapter | `workflow/adapters/<host>.md` | Run protocol plus a Claude-construct → host-behavior map (`claude-cloud.md`, `codex.md`, `agy.md`). Mappings only. |
| `gh` shim | `tools/cloud-gh-shim.py` | Installed as `gh` for Claude cloud sessions. Answers the GraphQL-backed `gh issue/pr/repo/auth` calls the workflow scripts make over REST; everything else (including `gh api`) reaches the real gh. Tested by `tools/cloud-gh-shim.test.sh`. |
| Drift test | `tools/cloud-workflow-adapter.test.sh` | Fails when a covered command uses a Claude-only construct on the test's known list that an adapter doesn't map, or an adapter maps one no covered command uses. |

## Invocation

Give the cloud task: the adapter's run protocol (`workflow/adapters/codex.md` for Codex Cloud, `workflow/adapters/agy.md` for Antigravity), one explicit ticket number, and the command to run (`/start`, then implement, then `/open-pr`). Output includes `workflow_source_commit`; the adapter requires it in the PR body and final report.

For local Antigravity sessions on the host machine where the dotfiles repo is already cloned, the adapter locates `workflow_root` and `workflow_bin` directly without downloading a remote tarball, and resolves `workflow_source_commit` from git.

Requirements: Bash, curl, tar, Python 3 (when `WORKFLOW_REF` is not a full SHA, and always for `WORKFLOW_INSTALL=claude`, whose `gh` shim is Python), outbound HTTPS to `api.github.com` and `codeload.github.com`, plus project-appropriate GitHub credentials for issue reads, push, and PR creation. `GITHUB_TOKEN` is optional and raises the API rate limit (60 requests/hour/IP unauthenticated; cloud egress IPs may be shared). It is sent to the API call only.

## Claude Code cloud sessions

`WORKFLOW_INSTALL=claude` makes the bootstrap a real install: it keeps the snapshot under `~/.cache/dotfiles-workflow/<sha>`, copies `dot_claude/{commands,agents,skills}` into `~/.claude` (chezmoi `executable_` prefixes stripped; the global `CLAUDE.md` and settings templates are not installed), links `tools/*.sh` into `/usr/local/bin` (or `~/.local/bin`), and installs the `gh` shim ahead of the real gh. PATH is exported through `$CLAUDE_ENV_FILE` when a SessionStart hook runs it, otherwise appended to `~/.bashrc`.

Use it either way:

- **Environment setup script** (runs before Claude starts, so the slash commands are listed from the first turn): `curl -fsSL https://raw.githubusercontent.com/IdahoEv/dotfiles/main/tools/cloud-workflow-bootstrap.sh -o /tmp/b.sh && WORKFLOW_INSTALL=claude bash /tmp/b.sh`
- **Per-repo SessionStart hook** in `.claude/settings.json`, running the same command with `WORKFLOW_INSTALL=claude`. Commands installed mid-session may need `/reload-skills`.
- **Ad hoc**: give the session `workflow/adapters/claude-cloud.md` and run protocol step 1.

Differences from a local session, all in `claude-cloud.md`: `/start` uses `start-ticket.sh --in-place` (ticket branch cut from the default branch in the existing checkout, or continuing the remote one; refuses a dirty tree; no worktree); `/open-pr` runs `--review none` (Copilot's request is GraphQL; use `mcp__github__request_copilot_review`); `/github-review-comments` reads review state through the GitHub MCP tools instead of `github-review-poll.sh` / `-state.sh`; `/finalize` stops at verify, close, and sync (no worktree, no deploy clone). GitHub tickets only: Shortcut needs `mcp__shortcut__`.

Unverified from this repo: whether the cloud git proxy accepts a push of the ticket branch when the environment names a different assigned branch. The adapter stops and reports if it does not.

## Trust and pinning

`main` is a moving target: with the default ref, any push to `main` changes what the next cloud task does, and the bootstrap script itself is fetched from `main`. For a stable pilot, pass `WORKFLOW_REF=<full sha>` ; the adapter's download URL uses the same ref. The reported `workflow_source_commit` is the resolved commit, not a promise that the ref was fixed in advance.

## Coverage and limits

- **Claude Code cloud (`workflow/adapters/claude-cloud.md`):** Covers `/start`, `/open-pr`, `/local-review-cycle`, `/github-review-comments`, and `/finalize`. Not covered: Shortcut tickets, Copilot review requests via `/open-pr`, `/discuss`, `/board`, sibling-repo fan-out.
- **Codex Cloud (`workflow/adapters/codex.md`):** Covers `/start` and `/open-pr`. Not covered: `/finalize`, review cycles (PRs from this path state `Independent review: not performed`), governor, discussion, planning. The Codex task is already an isolated checkout, so worktree and session-launch steps are skipped.
- **Antigravity (`workflow/adapters/agy.md`):** Covers `/start`, `/local-review-cycle`, `/open-pr`, and `/github-review-comments`. Maps `local-review-cycle-manager`, leaf reviewer specialists (`*-reviewer`), and `github-review-repair-agent` onto AGY's `define_subagent`/`invoke_subagent` tools, and deploys user rules and skill wrappers under `dot_gemini/config/` (`~/.gemini/config/`). Local AGY sessions create and switch into the ticket worktree; remote unreviewed runs skip the review cycle and state `Independent review: not performed`.

Constructs without a mapping stop the task with a report, never an improvisation.

The tests prove the bootstrap and adapter in source control, not that a phone-launched cloud task has network access, credentials, the right checkout, or build dependencies. Record those in `docs/cloud-pilot-checklist.md`.

## Adding a host

Copy an existing adapter (`workflow/adapters/codex.md` or `agy.md`), change the construct behaviors, and add a `check` call for it in the drift test. The bootstrap and commands do not change.
