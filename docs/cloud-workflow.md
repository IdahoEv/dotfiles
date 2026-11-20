# Cloud workflow

Cloud agents (Claude Code cloud sessions, Codex Cloud, and Google Antigravity / AGY) run the dotfiles' own command files (`dot_claude/commands/*.md`) through a per-host adapter. No workflow steps are restated here or in the adapter, so editing a command changes what cloud agents do on the next run.

| Piece | Path | Role |
| --- | --- | --- |
| Bootstrap | `tools/cloud-workflow-bootstrap.sh` | Fetches the repo as one tarball for `WORKFLOW_REF` (default `main`) from `codeload.github.com` and reads the commit SHA from the archive's own header (no GitHub API call; a pinned SHA is verified against it), checks required files, exposes `tools/*.sh` on `workflow_bin`, prints `key=value`. Any failure exits non-zero; no cached copy is used. |
| Adapter | `workflow/adapters/<host>.md` | Run protocol plus a Claude-construct → host-behavior map (`claude-cloud.md`, `codex.md`, `agy.md`). Mappings only. |
| `gh` shim | `tools/cloud-gh-shim.py` | Installed as `gh` for Claude cloud sessions. Answers the GraphQL-backed `gh issue/pr/repo/auth` calls the workflow scripts make over REST; everything else (including `gh api`) reaches the real gh. Tested by `tools/cloud-gh-shim.test.sh`. |
| Drift test | `tools/cloud-workflow-adapter.test.sh` | Fails when a covered command uses a Claude-only construct on the test's known list that an adapter doesn't map, or an adapter maps one no covered command uses. |

## Invocation

Give the cloud task: the adapter's run protocol (`workflow/adapters/codex.md` for Codex Cloud, `workflow/adapters/agy.md` for Antigravity), one explicit ticket number, and the command to run (`/start`, then implement, then `/open-pr`). Output includes `workflow_source_commit`; the adapter requires it in the PR body and final report.

For local Antigravity sessions on the host machine where the dotfiles repo is already cloned, the adapter locates `workflow_root` and `workflow_bin` directly without downloading a remote tarball, and resolves `workflow_source_commit` from git.

Requirements: Bash, curl, tar, Python 3, and outbound HTTPS to `raw.githubusercontent.com` (the bootstrap script, and the file-by-file fallback) and preferably `codeload.github.com`. The bootstrap makes no GitHub API call and sends no credentials; `WORKFLOW_SRC=<clone>` skips the download entirely, and `WORKFLOW_FETCH=raw|archive` forces one path. The workflow's own commands additionally need `api.github.com` and project-appropriate GitHub credentials for issue reads, push, and PR creation.

## Claude Code cloud sessions

`WORKFLOW_INSTALL=claude` makes the bootstrap a real install: it keeps the snapshot under `~/.cache/dotfiles-workflow/<sha>`, copies `dot_claude/{commands,agents,skills}` into `~/.claude` (chezmoi `executable_` prefixes stripped; the global `CLAUDE.md` and settings templates are not installed), links `tools/*.sh` into `/usr/local/bin` (or `~/.local/bin`), and installs the `gh` shim ahead of the real gh. PATH is exported through `$CLAUDE_ENV_FILE` when a SessionStart hook runs it, otherwise appended to `~/.bashrc`.

**Repository scope.** A cloud session's GitHub access is scoped to the repositories attached to it. In a session on another project, `api.github.com` and `codeload.github.com` return 403 for `IdahoEv/dotfiles` and only `raw.githubusercontent.com` is reachable. So the bootstrap tries the archive first and falls back to fetching each file from `raw.githubusercontent.com`, checking it against `workflow/manifest.txt` (sha256 and mode per file). The manifest comes from the same ref over TLS as the files, so the check proves a consistent snapshot, not authenticity: trust rests on the ref. A pinned full SHA fixes the bytes but not their provenance (raw serves any commit in the repo's fork network; only the archive path verifies a pin against the commit). Nothing needs attaching, which also means anyone can use the public repo this way. The fallback has no commit id for a branch ref, so it stamps `manifest-<digest>`; pin `WORKFLOW_REF` to a full SHA for an exact one. A push landing mid-download, or a stale CDN copy, fails the hash check instead of installing a mixed snapshot: retry, or pin. Regenerate the manifest with `tools/workflow-manifest.sh --write` whenever a covered file changes; `tools/workflow-manifest.test.sh` fails when it is stale, and nothing else gates it (the repo has no CI), so run that test before merging a change to a covered file. The generator hashes staged blobs, so `git add` first. If raw is blocked too, attach the repo, clone it, and use `WORKFLOW_SRC=<clone>`.

Use it either way:

- **Environment setup script** (runs before Claude starts, so the slash commands are listed from the first turn): `curl -fsSL https://raw.githubusercontent.com/IdahoEv/dotfiles/main/tools/cloud-workflow-bootstrap.sh -o /tmp/b.sh && WORKFLOW_INSTALL=claude bash /tmp/b.sh`
- **Per-repo SessionStart hook** in `.claude/settings.json`, running the same command with `WORKFLOW_INSTALL=claude`. Commands installed mid-session may need `/reload-skills`.
- **Ad hoc**: give the session `workflow/adapters/claude-cloud.md` and run protocol step 1.

Differences from a local session, all in `claude-cloud.md`: `/start` uses `start-ticket.sh --in-place` (ticket branch cut from the default branch in the existing checkout, or continuing the remote one; refuses a dirty tree; no worktree); `/open-pr` runs `--review none` (Copilot's request is GraphQL; use `mcp__github__request_copilot_review`); `/github-review-comments` reads review state through the GitHub MCP tools instead of `github-review-poll.sh` / `-state.sh`; `/finalize` stops at verify, close, and sync (no worktree, no deploy clone). GitHub tickets only: Shortcut needs `mcp__shortcut__`.

Push permission: a cloud session may push any branch it creates. Branch names follow the ticket branch from `start-ticket.sh --in-place`, or `<N>-slug`. Never force-push, push to the default branch, or rewrite history on a shared branch; stop and report if a push is refused. Protect the default branch on the remote, since the `git push -u origin` allow rule matches any branch.

`gh` is installed as the system `gh` (the real binary kept as `gh.real`) when the setup script runs as root, so a plain Bash call finds the REST shim without any `PATH` setup. The bootstrap also installs a small `~/.claude/settings.json` with allow rules only (`git add`, `git commit`, `git push -u origin`, the Copilot review request) so multi-repo sessions can run the sequence unprompted; it merges into existing settings and adds no hooks.

## Trust and pinning

`main` is a moving target: with the default ref, any push to `main` changes what the next cloud task does, and the bootstrap script itself is fetched from `main`. For a stable pilot, pass `WORKFLOW_REF=<full sha>` ; the adapter's download URL uses the same ref. The reported `workflow_source_commit` is the resolved commit, not a promise that the ref was fixed in advance.

**Testing a ref.** Setting `WORKFLOW_REF` in a session does nothing to an install that already ran: cloud environments cache the setup script's result, so a session can boot with the `main` of the last cache build. To test a branch or SHA, rerun the bootstrap with the ref (adapter protocol 1), then confirm `workflow_source_commit=` or `readlink -f "$(command -v start-ticket.sh)"` names it. Merged changes reach cached environments only after their cache is rebuilt.

## Per-project toolchains

A project whose toolchain is missing from the cloud image cannot run its tests there; that is an environment concern, not a workflow one. Two options: install it in the **environment setup script**, or in a **per-repo SessionStart hook**. Either way the environment's network allowlist must include the toolchain's download hosts. `/pick` checks the toolchain is present before offering a ticket that needs a build or test run, and reports it as "unverifiable here" otherwise.

## Default sequence and Stop hook

Every kickoff carries the default sequence (`start-ticket.sh` `sequence_block`): plan then pause; after approval implement, commit, `/local-review-cycle`, push and `/open-pr`, remote review, with no further approvals; stop before merge; any failure pauses and asks. A project's `design_gate=` key in `.start-ticket.conf` adds a pause for aesthetic changes before the review cycle. The "uncommitted changes, please commit and push" Stop hook seen in one cloud session is not in this repo (`dot_claude/modify_private_settings.json.tmpl` Stop hooks only set colour and status), `dot_claude/plugins`, or a fresh cloud container. It must be in the cloud environment settings, the account/organisation settings, or the project repo's `.claude/settings.json`: still to be located by the owner, and it must not fire before plan approval.

Board fields (GitHub Projects v2) cannot be set from cloud; `/open-pr` sets milestones over REST and reports the board fields to set by hand.

## Coverage and limits

- **Claude Code cloud (`workflow/adapters/claude-cloud.md`):** Covers `/start`, `/open-pr`, `/local-review-cycle`, `/github-review-comments`, `/finalize`, `/merge`, `/land`, `/sync` and `/pick`. Not covered: Shortcut tickets, Copilot review requests via `/open-pr`, `/discuss`, `/board`, sibling-repo fan-out.
- **Codex Cloud (`workflow/adapters/codex.md`):** Covers `/start` and `/open-pr`. Not covered: `/finalize`, review cycles (PRs from this path state `Independent review: not performed`), governor, discussion, planning. The Codex task is already an isolated checkout, so worktree and session-launch steps are skipped.
- **Antigravity (`workflow/adapters/agy.md`):** Covers `/start`, `/local-review-cycle`, `/open-pr`, `/github-review-comments`, `/governor`, `/pick`, `/discuss`, `/remind`, and `/finalize` (local interactive sessions only; remote and headless runs stop with the PR open). Maps `local-review-cycle-manager`, leaf reviewer specialists (`*-reviewer`), and `github-review-repair-agent` onto AGY's `define_subagent`/`invoke_subagent` tools, and deploys user rules and skill wrappers under `dot_gemini/config/` (`~/.gemini/config/`). Local AGY sessions create the ticket worktree; a multi-group `/start 100,101,102 143 156` opens one `agy-tmux` window per group inside a dashboard session, and outside one takes the first group inline and prints the start command for each other group; remote unreviewed runs skip the review cycle and state `Independent review: not performed`.

Constructs without a mapping stop the task with a report, never an improvisation.

The tests prove the bootstrap and adapter in source control, not that a phone-launched cloud task has network access, credentials, the right checkout, or build dependencies. Record those in `docs/cloud-pilot-checklist.md`.

## Adding a host

Copy an existing adapter (`workflow/adapters/codex.md` or `agy.md`), change the construct behaviors, and add a `check` call for it in the drift test. The bootstrap and commands do not change.

## Ticket access when `gh` is unauthenticated

**Decision: MCP handoff, not `gh` auth.** Cloud environments refuse the saved credential for `api.github.com`, so there is no supported way to give `gh` a working token; GitHub is reachable only through `mcp__github__*`, which a script can't call. So the agent does the tracker calls and the script consumes the result.

| Step | Who | How |
| --- | --- | --- |
| Detect | `start-ticket.sh` | `gh` unauthenticated → one error, `github unavailable … rerun with --provider github-mcp` |
| Read tickets | agent | `mcp__github__issue_read` per id → `$TMPDIR/start-ticket-mcp/<id>.json` |
| Branch, kickoff | `start-ticket.sh` | `START_TICKET_MCP_DIR=<dir> start-ticket.sh <ids> --in-place --no-tab` (`tools/start-ticket-providers/github-mcp.sh`); reports `ticket_in_progress=unknown` |
| Mark in progress | agent | `/start` step 1a: assign + comment through `issue_write` / `add_issue_comment`, then read back |

Chains (`12,13 14`) work: one handoff file per id. Setting `START_TICKET_MCP_DIR` selects the provider without a `.start-ticket.conf`. Tested in `tools/start-ticket.test.sh`; a live cloud run is not covered.

`/project-review-apply` uses the same handoff for tracker listing and filing (`tracker.sh --provider github-mcp`, staged in `$TRACKER_MCP_DIR`); see `docs/project-review-scheduling.md` § Provider auth.
