---
name: project-review-procedure
description: Procedure for running a read-only periodic project review — activity gate, shared default-branch snapshot, tracker pull with truncation abort, lens discovery and fan-out, central synthesis, inline report, and snapshot cleanup. Preloaded by project-review-manager; not invoked directly.
user-invocable: false
---

# Project Review Procedure

Run a read-only periodic review of `origin/<default_branch>` using fresh lens agents, then synthesize findings centrally into a grouped inline report. Never edit repository files or mutate tracker state.

## 1. Preflight & config

- Fetch `origin` (`git fetch origin`). Verify `origin/<default_branch>` resolves (`git rev-parse --verify "origin/<default_branch>"`); stop if not.
- Locate `project-review.md` via `project-config.sh find project-review.md 2>/dev/null | cut -f1 || true`.
  - If found, read it. Any value still in `<...>` placeholder form counts as unset.
  - If absent, proceed in report-only mode with defaults: `Window: 7`, no `Activity globs:`, no `Skip:`, `inline` delivery.
- Resolve `Window` (positive integer days from § Cadence `Window:`, default `7`; overridden by `--window N` if passed in kickoff) and `Activity globs:` (non-placeholder globs from § Cadence).

## 2. Activity gate

Unless `--force` is in kickoff `Flags:`, check for commits in the window:

```bash
git log -n 1 --since="<Window> days ago" "origin/<default_branch>" [-- <globs...>]
```

Omit `-- <globs...>` when `Activity globs:` is unset. If the output is empty, stop without creating a snapshot and report:

`Skipped: no activity on origin/<default_branch> in the last <Window> days.`

## 3. Shared read-only snapshot

Create one detached checkout of `origin/<default_branch>` shared by all lenses:

1. Pick a gitignored scratch parent:
   - If `git check-ignore -q .scratch 2>/dev/null`, use `<cwd>/.scratch/project-review-<timestamp>-<pid>`.
   - Else if `git check-ignore -q .claude/scratch 2>/dev/null`, use `<cwd>/.claude/scratch/project-review-<timestamp>-<pid>`.
   - Else create a temp dir with `mktemp -d "${TMPDIR:-/tmp}/project-review.XXXXXX"` (outside the repo so nothing can be committed).
2. Create the snapshot worktree and record its literal path:
   ```bash
   git worktree add --detach "<snapshot_dir>" "origin/<default_branch>"
   ```
3. **Cleanup invariant:** On **every** exit path (normal completion, tracker abort, lens error, or unexpected failure), remove the snapshot and prune:
   ```bash
   git worktree remove --force "<snapshot_dir>" 2>/dev/null || true
   rm -rf "<snapshot_dir>"
   git worktree prune
   ```
   Verify `[ ! -e "<snapshot_dir>" ]` before returning.

## 4. Tracker pull (truncation abort)

Pull open and closed issues through the provider seam:

```bash
tracker.sh list --state open
tracker.sh list --state closed
```

- **Exit 2** (provider cannot list): set `tracker_mode=unavailable` and continue in report-only mode (triage will report skipped; no live tracker `ALREADY TICKETED` matching).
- **Any other non-zero exit, malformed JSON, or `"truncated": true`** on either call: **run snapshot cleanup (§3) immediately** and abort with an error naming which pull failed or truncated. Never synthesize from a partial issue set.
- Otherwise retain the open and closed issue sets for synthesis and pass a concise summary of open/already-ticketed items to lenses.

## 5. Lens discovery & fan-out

Discover lenses following `review-lens-contract` § Discovery:

1. Scan all three tiers at once (use `grep -rnE` if `rg` is absent):
   ```bash
   rg -H --no-messages '^(name|use_when):|^Lens:\s*(collect|triage)' .claude/agents dot_claude/agents docs/local/reviewers ~/.claude/agents $(project-config.sh list agents 2>/dev/null)
   ```
2. Deduplicate by `name` in tier order, filter to `Lens: collect` or `Lens: triage`, and drop any lens in `project-review.md` § Lenses `Skip:` (ignoring `<...>` placeholders), per `review-lens-contract` § Discovery.

Launch all remaining lenses in parallel against the same `<snapshot_dir>` (registered lenses by name; tier-2 lenses via `general-purpose` per `review-lens-contract` § Discovery):

- **Inputs for every lens:**
  - Snapshot path: `<snapshot_dir>` (literal path)
  - `project-review.md` path: `<path>` or `none`
  - Word cap: `400 words`
  - Known/ticketed findings: summary of open tracker issues (and prior review-state entries if configured), or `none`

## 6. Central synthesis

Wait for all launched lenses, then synthesize centrally:

1. **Evidence check:** Keep only findings with `file:line` in the snapshot or probe command output. Drop unsubstantiated claims.
2. **Cross-lens dedup:** Merge findings describing the same defect/location across lenses; retain the strongest evidence and list all contributing lenses.
3. **Tag status:** Tag each finding `NEW`, `KNOWN`, or `ALREADY TICKETED` against the open tracker issues and any non-placeholder review-state doc (`backlog` / `pending-actions` in `project-review.md` § Review state).
4. **Recurrence:** When prior review-state/history is available, count prior unticketed sweeps. A finding unticketed across **3+ sweeps** escalates one severity level (e.g. `P2` → `P1`) and is marked `recurring (N sweeps)`.
5. **Order:** Sort by severity (`P0` → `P1` → `P2` → `P3`), `NEW` before `KNOWN` / `ALREADY TICKETED`.

## 7. Inline report & cleanup

1. Run snapshot cleanup (§3) and verify `<snapshot_dir>` is removed before emitting the report.
2. Emit the grouped inline report (read-only):
   - **Header:** Repo, `origin/<default_branch>` short SHA, window (`<Window>d`), lenses run and skipped, tracker status (`ok` / `unavailable — report-only`).
   - **Findings by lens:** One section per lens that produced findings (respecting per-lens word caps), ordered by severity:
     `SEVERITY | STATUS | file:line | defect | evidence | minimal fix` (append `| recurring (N sweeps)` when applicable).
   - **Triage summary:** Separate section when a `Lens: triage` agent ran — duplicates, state consistency, debt ranking, work clusters, and any `Proposed actions:` listed as read-only recommendations (never executed).
   - **Verified clean & skipped:** Per-lens `Verified clean:` items, plus any sections/roles skipped because `project-review.md` was absent or unset.
