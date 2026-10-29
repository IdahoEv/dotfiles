# Codex Cloud ticket-to-PR pilot

The canonical host-neutral contract is `workflow/ticket-to-pr.md`. The thin bootstrap at `tools/codex-cloud-bootstrap.sh` resolves the current `main` commit through the GitHub API, fetches that contract by immutable commit SHA, validates required markers, and prints the exact source SHA and local temporary file path. Any retrieval or validation failure exits non-zero; it never falls back to a stale copy.

## Invocation contract

A host adapter should download the bootstrap from this public repository, execute it with Bash, read the returned `workflow_source_path`, and follow the workflow in that file. Preserve `workflow_source_commit` verbatim in the PR description and final task report. The temporary path is session-local; it is not a project artifact and should not be committed.

Requirements: Bash, curl, Python 3, outbound HTTPS access to `api.github.com` and `raw.githubusercontent.com`, and project-appropriate GitHub credentials for issue reads, pushing a branch, and opening a PR. The bootstrap itself uses unauthenticated read access to this public repository. GitHub write permissions are separate and must be tested in the target environment.

## Codex-specific limits

This adapter does not emulate Claude Code commands, skills, hooks, MCP tools, worktrees, or session controls. The project repository must provide minimal Codex-facing guidance and retain its own ticket, branch, build/test, and environment-specific rules. Use only tools actually available in the cloud task.

The bootstrap and workflow can be validated in source control, but they do not prove that a phone-launched Codex Cloud task has network access, credentials, the right repository checkout, or sufficient build dependencies. Record those as pilot observations; do not claim end-to-end completion until a real task opens an unmerged PR with the source SHA recorded.
