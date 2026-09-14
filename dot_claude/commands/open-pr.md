# Open a Pull Request

Push the current branch, open (or reuse) its PR, and trigger reviews — the
middle leg of the `/start` → `/open-pr` → `/finalize` cycle.

All mechanical steps (push, PR create-or-reuse, review-bot triggering) are
handled by `open-pr.sh` in the `git-tools` repo (alongside `start-ticket.sh`).
That script **never commits** — drafting the commit message + PR title/body,
and getting your approval, is this command's job.

## Usage

```text
/open-pr
/open-pr --review none
/open-pr --review copilot          # default
/open-pr --review copilot+claude
/open-pr --provider kardashev      # --env is an alias; kardashev is default (only provider today)
```

`--review` levels: `none` (no review request), `copilot` (default — request the
Copilot bot via the `requestReviews` mutation; safe), `copilot+claude` (also
dispatch `claude.yml` via `gh workflow run claude.yml -f pr_number=<N>`; opt-in
only). Providers live in `git-tools/open-pr-providers/`; each encapsulates its
review bots + PR title/body/branch conventions. `kardashev` is the only one.

## Steps

### 1. Preflight

```bash
git branch --show-current
```

On `main`/`master`: **stop** — there's nothing to ship.

### 2. Draft and approve

Gather everything that needs approval *before* running `open-pr.sh`. If the
tree is dirty, view the diff and draft a commit message:

```bash
git status
git diff HEAD
git ls-files --others --exclude-standard
```

If this branch has no PR yet, also draft the PR title (`Is<NNN>: <short
title>` — see the repo's `.claude/kickoff-preamble.md`) and body (end with
`Closes #<NNN>`).

Show all drafted artifacts in full and wait for `execute` / `execute <message>`
before continuing. One `execute` covers commit + push + PR together.

### 3. Commit (if dirty)

```bash
git add -A
git commit -m "<approved message>"
```

`open-pr.sh` never commits. Append the Co-Authored-By trailer unless the
approved message already has one.

### 4. Ship

```bash
# first ship — create the PR with the approved metadata:
open-pr.sh --title "Is<NNN>: <short title>" --body-file <tmp-file> --review <level>

# re-trigger on an existing PR — reuse existing title/body:
open-pr.sh --review <level>
```

Capture `pr_number` from stdout (also prints `pr_url`, `pr_action`).

### 5. Poll (skip if `--review none`)

```bash
~/.claude/skills/review-comments/poll-pr.sh <pr_number>
```

Run in the background. On completion: exit 0 → re-invoke `/review-comments`;
exit 3 → reviewers signed off (ready to merge); exit 1 → timeout; exit 2 → no
PR found. Default 2 review rounds before treating the PR as converged.

### 6. Report

```
Shipped Is<NNN> — <title>
PR #<n>: <url>  (created | reused)
Reviews requested: <none | copilot | copilot+claude>
```
