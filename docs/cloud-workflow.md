# Cloud workflow for non-Claude hosts

Non-Claude agents (Codex Cloud first) run the dotfiles' own command files (`dot_claude/commands/*.md`) through a per-host adapter. No workflow steps are restated here or in the adapter, so editing a command changes what cloud agents do on the next run.

| Piece | Path | Role |
| --- | --- | --- |
| Bootstrap | `tools/cloud-workflow-bootstrap.sh` | Resolves `WORKFLOW_REF` (default `main`) to a commit SHA, fetches the repo as one tarball at that SHA, checks required files, exposes `tools/*.sh` on `workflow_bin`, prints `key=value`. Any failure exits non-zero; no cached copy is used. |
| Adapter | `workflow/adapters/<host>.md` | Run protocol plus a Claude-construct → host-behavior map. Mappings only. |
| Drift test | `tools/cloud-workflow-adapter.test.sh` | Fails when a covered command uses a Claude-only construct on the test's known list that the adapter doesn't map, or the adapter maps one no covered command uses. |

## Invocation

Give the cloud task: the adapter's run protocol (`workflow/adapters/codex.md`), one explicit ticket number, and the command to run (`/start`, then implement, then `/open-pr`). Output includes `workflow_source_commit`; the adapter requires it in the PR body and final report.

Requirements: Bash, curl, tar, Python 3 (only when `WORKFLOW_REF` is not a full SHA), outbound HTTPS to `api.github.com` and `codeload.github.com`, plus project-appropriate GitHub credentials for issue reads, push, and PR creation. `GITHUB_TOKEN` is optional and raises the API rate limit (60 requests/hour/IP unauthenticated; cloud egress IPs may be shared). It is sent to the API call only.

## Trust and pinning

`main` is a moving target: with the default ref, any push to `main` changes what the next cloud task does, and the bootstrap script itself is fetched from `main`. For a stable pilot, pass `WORKFLOW_REF=<full sha>` ; the adapter's download URL uses the same ref. The reported `workflow_source_commit` is the resolved commit, not a promise that the ref was fixed in advance.

## Coverage and limits

v1 covers `/start` and `/open-pr`. Not covered: `/finalize`, review cycles (so PRs from this path state `Independent review: not performed`), governor, discussion, planning. Constructs without a mapping stop the task with a report, never an improvisation. The Codex task is already an isolated checkout, so worktree and session-launch steps are skipped.

The tests prove the bootstrap and adapter in source control, not that a phone-launched cloud task has network access, credentials, the right checkout, or build dependencies. Record those in `docs/cloud-pilot-checklist.md`.

## Adding a host

Copy `workflow/adapters/codex.md`, change the construct behaviors, and add a `check` call for it in the drift test. The bootstrap and commands do not change.
