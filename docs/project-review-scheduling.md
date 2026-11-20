# Scheduling a Project Review Job

Project review is a periodic task designed to review the project as a whole (as opposed to code review of an individual PR).

Each repository you want to review should have a `.claude/project-review.md`. That file will configures the actions the reviewer will take; without it the review is report-only.

## Setup steps

- Copy `tools/project-config-templates/project-review.md` from dotfiles to your project's `.claude/`.
- Edit that file to set review configuration. Config documentation is below
- Commit that file to your repository so cloud sessions receive it. Many projects have `.claude` in gitignore, in which case you may allowlist the file by adding `!.claude/project-review.md` to `.gitignore`.
- Schedule a job to execute `/project-review-apply` on the schedule you prefer. That job must run where dotfiles is installed: locally after `chezmoi apply`, or in cloud after the workflow bootstrap (`workflow/adapters/claude-cloud.md` § Run protocol).

## Running the Project Review: /project-review-apply

`/project-review-apply` runs the periodic review, then acts on the report per the repo's `project-review.md`. The scheduler's stored prompt is that command alone; every project-specific choice lives in the repo.

```text
/project-review-apply
```

## Config

Resolved from `<repo>/.claude/project-review.md`, then the overlay if one exists. A cloud run needs only the repo file. Missing `## Actions` means report-only.

| Section | Keys | Effect |
| --- | --- | --- |
| `## Actions` | `file-tickets: off \| <P0-P3> <NEW\|ANY>` | File tickets at that severity or higher. `NEW` skips `KNOWN`; `ALREADY TICKETED` is never filed |
| | `ticket-labels` | Labels on filed tickets |
| | `queue-ticket-closures: on\|off` | Queue triage closures/redefinitions in `pending-actions`. Tickets are never closed or edited |
| | `doc-pr: on\|off` | One PR updating the `## Review state` docs |
| `## Delivery` | `email:<address>` \| `file:<path>` \| `inline` | Where the report goes. `- fallback: file:<path>\|inline` applies when email has no mail connector |

A create that fails is retried once without labels (a label missing from the repo is the usual cause). Filing is script code (`tools/project-review-apply.sh`): each finding gets a key (`sha1(normalized title)`, 12 hex) stamped in the ticket body as `<!-- project-review-key: K -->`. A key found in any open or closed ticket is skipped, so reruns never duplicate. If the provider cannot create or list completely (exit 2, or a truncated ticket pull), the finding is queued in `pending-actions` as `new-<key>` instead.

## Provider auth

The procedure runs `gh auth status` first. If `gh` works, the `github` provider is used. If not, tickets go through the GitHub MCP tools (`github-mcp`). Whether a cloud environment's `gh` holds a usable token varies (see `docs/cloud-workflow.md` § Ticket access when `gh` is unauthenticated).

| Provider | Needs | Behavior |
| --- | --- | --- |
| `github` | `gh` authenticated with issues read+write (a local login, or `GH_TOKEN`; add contents/PR write for `doc-pr`). In cloud the `gh` shim answers `issue list`/`issue create` over REST | Scripts list and file tickets directly |
| `github-mcp` | The GitHub MCP tools in the session | The agent stages open and closed issues in `$TRACKER_MCP_DIR` (`issues-open.json`, `issues-closed.json`) before the review. Filing: the apply script records each request in `$TRACKER_MCP_DIR/create/` and the agent creates it with `mcp__github__issue_write`. Dedup works the same: the key is in the body |
| neither | | The ticket pull aborts and nothing is delivered |
| `shortcut` | Not supported: `list`/`create` are stubs (exit 2) | Report-only; findings queued in `pending-actions` |
| other | Define `provider::list_issues` and `provider::create_issue <title> <body-file> <labels-csv>` (print `{"id":N,"url":"..."}`), return 2 for "cannot" | Exit 2 as above |

A failure inside the apply step (listing or filing) is reported under `## Actions taken` and the report is still delivered. With `github-mcp`, each recorded create request also leaves a `new-<key>` row in `pending-actions` (when a path is configured) that is not removed once the ticket is filed.

Email needs a mail connector (Gmail-type MCP server) attached to the routine. Without one the report goes to the fallback channel.

## Cloud routine

Create one routine per repo with `/schedule`. The environment setup runs the workflow bootstrap (`workflow/adapters/claude-cloud.md` run protocol) so the tools and `gh` shim are on `PATH`; the run does not depend on `~/.local/bin` or the overlay.

| Repo | `project-review.md` | Result |
| --- | --- | --- |
| A | `## Delivery` `email:team@example.com`; no `## Actions` | Report emailed, nothing filed |
| B | `## Actions` `file-tickets: P1 NEW`, `ticket-labels: review`, `queue-ticket-closures: on`; `## Delivery` `file:docs/reviews/latest.md` | P1 findings filed, closures queued, report written to the file |

Both routines use the identical stored prompt `/project-review-apply`. Pin `WORKFLOW_REF` to a full SHA. Pilot results for these two runs belong in `docs/cloud-pilot-checklist.md`.
