# Scheduling /project-review-apply

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

| Provider | Needs | Without it |
| --- | --- | --- |
| `github` | `GH_TOKEN` in the routine's environment with issues read+write (add contents/PR write for `doc-pr`). In a cloud session the `gh` shim answers `issue list`/`issue create` over REST | The review's ticket pull aborts and nothing is delivered. If only filing fails, the report is still delivered with the failure under `## Actions taken` |
| `github-mcp` | Not supported by `tracker.sh` (scripts cannot call MCP) | Same as above; use `github` |
| `shortcut` | Not supported: `list`/`create` are stubs (exit 2) | Report-only; findings queued in `pending-actions` |
| other | Define `provider::list_issues` and `provider::create_issue <title> <body-file> <labels-csv>` (print `{"id":N,"url":"..."}`), return 2 for "cannot" | Exit 2 as above |

Email needs a mail connector (Gmail-type MCP server) attached to the routine. Without one the report goes to the fallback channel.

## Cloud routine

Create one routine per repo with `/schedule`. The environment setup runs the workflow bootstrap (`workflow/adapters/claude-cloud.md` run protocol) so the tools and `gh` shim are on `PATH`; the run does not depend on `~/.local/bin` or the overlay.

| Repo | `project-review.md` | Result |
| --- | --- | --- |
| A | `## Delivery` `email:team@example.com`; no `## Actions` | Report emailed, nothing filed |
| B | `## Actions` `file-tickets: P1 NEW`, `ticket-labels: review`, `queue-ticket-closures: on`; `## Delivery` `file:docs/reviews/latest.md` | P1 findings filed, closures queued, report written to the file |

Both routines use the identical stored prompt `/project-review-apply`. Pin `WORKFLOW_REF` to a full SHA. Pilot results for these two runs belong in `docs/cloud-pilot-checklist.md`.
