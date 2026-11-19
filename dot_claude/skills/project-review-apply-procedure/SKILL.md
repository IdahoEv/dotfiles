---
name: project-review-apply-procedure
description: Procedure for /project-review-apply — run the project review, then act on its report per project-review.md § Actions and § Delivery (file tickets, queue closures, doc PR, deliver the report). Loaded by the /project-review-apply command; not invoked directly.
user-invocable: false
---

# Project Review Apply Procedure

Review, then act. Filing and queueing are done by scripts; this procedure only wires them together. Never close or edit an existing ticket.

## 1. Resolve context and tools

- Repo (`gh repo view --json nameWithOwner -q .nameWithOwner`), default branch (`repo-facts.sh default-branch`), working directory (`git rev-parse --show-toplevel`). Stop if any fails.
- Tools: `project-review-config.sh`, `project-review-apply.sh`, `tracker.sh`, `pending-actions.sh` must be on `PATH`. Do not look in `~/.local/bin` specifically; if `command -v project-review-apply.sh` is empty, stop and report that the workflow install (cloud adapter run protocol) did not run.
- Config file: `<working directory>/.claude/project-review.md` if present, else the overlay via `project-config.sh find project-review.md` (optional; skip silently when the tool or overlay is absent). None found: report-only.
- Parse it: `project-review-config.sh <file> > "$TMPDIR/pr-config.json"`. A non-zero exit is a config error: stop and report its message, run nothing else.

## 2. Review

Launch `project-review-manager` with the `/project-review` kickoff plus one extra line, `Findings block: yes`:

```text
Run project-review-procedure on the default branch.
Repo: <owner>/<repo>
Default branch: <branch>
Working directory: <absolute cwd>
Flags: <--force and/or --window N | (none)>
Findings block: yes
```

If the manager reports the activity gate skipped the run or aborted, deliver nothing and act on nothing: print its message and stop.

## 3. Act

Split the report: the findings block (the fenced `project-review-findings` JSON) goes to `$TMPDIR/pr-findings.json`; everything before it is the report body.

- `.actions` is `null` (no § Actions): report-only. Skip to §5.
- Otherwise run `project-review-apply.sh "$TMPDIR/pr-findings.json" "$TMPDIR/pr-config.json"` and append its tab-separated output to the report under `## Actions taken`. A non-zero exit is reported, not retried; delivery still happens.
- `doc_pr` true and § Review state has paths: one PR from a new branch editing only those paths (backlog/archive/pending-actions) using this run's results; never edit anything else. `open-pr.sh`; never push the default branch.

## 4. Deliver

The report body plus `## Actions taken` is the delivery body. Use `delivery.kind` from the config (`inline` when no config):

| Kind | Action |
| --- | --- |
| `email` | Send to `target` with the available mail connector (a `send_message`/`create_draft` tool of a Gmail-type MCP server). Subject `Project review: <owner>/<repo> <YYYY-MM-DD>`. No connector, or the send fails: use `delivery.fallback` and say why in the first line of the output |
| `file` | Write the body to `target` (create parent dirs; the path is relative to the working directory). Do not commit it |
| `inline` | Print the body at top level, no fence or quote |

A `file` fallback that cannot be written falls through to `inline`. Always end by printing which channel actually delivered.

## 5. Finish

Report in the final message: review result, actions taken (counts of filed / duplicate / queued), delivery channel used. Failures and skipped steps are stated plainly.
