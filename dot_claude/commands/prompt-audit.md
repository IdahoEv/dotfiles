---
description: Audit every committed Claude prompt file in a repo for staleness, bloat, scope leakage, and duplication
argument-hint: [repo path, defaults to current] [--fix]
---

# Prompt Audit

Catalog drift across **all committed Claude prompt files** in a repository. Built
to run unattended on a schedule, so it never asks questions and never stops
halfway.

Target repo: `$1` if given, else the current working directory. `--fix` is the
only mode that edits; without it this is strictly read-only.

Use the `prompt-review` skill — it holds the criteria. Do not restate them here.

## Steps

### 1. Collect

Work from **committed** state, not the working tree, so the audit reflects what
other sessions actually load:

- `git -C <repo> status --short` — if dirty, say so in the report header and
  audit `HEAD` anyway. Do not stash, commit, or clean.
- Enumerate prompt files at `HEAD` (`git -C <repo> ls-files`), filtered to the
  scope the skill defines. Empty set → report that and stop.
- Note each file's last-touched date (`git log -1 --format=%ad -- <file>`).
  Old and factual is the highest-risk combination; old and stable is fine.

### 2. Audit

Invoke the `prompt-reviewer` agent in corpus mode with the complete committed
prompt-file inventory and the audited commit. The agent loads `prompt-review`
for the canonical criteria. Keep the inventory explicit so the reviewer cannot
silently drift into the working tree or omit files. Duplication and scope
comparisons must cover the whole corpus; do not split those checks file by file.

Verify factual claims against reality, not against the file: run the commands,
grep the paths, check tracker state via MCP when a ticket is named. An
unverified claim reported as a finding wastes more time than it saves. If a
claim can't be checked (no network, no tracker access, needs Docker), list it
under "unverified" rather than guessing.

### 3. Report

Write the catalog to `<repo>/.scratch/prompt-audit-<YYYY-MM-DD>.md`, following
the repo's own scratch convention instead if its CLAUDE.md names one. Create
the directory when it doesn't exist, and add it to `.gitignore` if that file is
tracked and doesn't already cover it — a scheduled run that emits only to chat
leaves no artifact and no baseline for the week-over-week diff in step 4. Never
write into shared `/tmp`.

Structure:

1. **Header** — repo, commit audited, file count, line count, dirty-tree note.
2. **Verdict line** — total findings per check. "No drift found" is a valid and
   welcome result.
3. **Findings** — the skill's block format, grouped by file.
4. **Unverified** — claims that need something unavailable, each with what it
   needs.
5. **Suggested order** — which findings to act on first, cheapest-with-highest-
   confidence first. Suggestions only; make no changes.

Keep the chat summary to the verdict line plus the top three findings, and
point at the written file for the rest. The catalog is the deliverable; the
chat output is a notification.

### 4. `--fix` only

Apply only findings in these categories, which have a single correct answer:
corrected counts/versions/paths, removed ticket-status claims, relative dates
made absolute. Leave every judgment call — bloat cuts, scope moves, duplication
collapses — in the catalog for a human.

Commit per category with the repo's prefix convention, then report what was
applied and what was left. Never push. If the tree was dirty at step 1, do not
use `--fix`; say why.

## Scheduling note

On a recurring run, open with a diff against the previous catalog if one exists
in `.scratch/`: what is new, what is still open, what was fixed since. A weekly
report that repeats last week's unread list is noise.
