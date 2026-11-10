# Open a Pull Request

Push the current branch, open (or reuse) its PR, and trigger reviews — the middle leg of
the `/start` → `/open-pr` → `/finalize` cycle.

`open-pr.sh` handles every mechanical step (commit, push, PR create-or-reuse, title
prefixing and repair, review-bot triggering, the phase stamp, and a detached review watch).
This command's only job is drafting its inputs: commit message, PR title, and body sections.

## Usage

```text
/open-pr
/open-pr --review none|copilot|copilot+claude    # default: copilot; none while ~/.config/local-review-only exists (review locally first with /local-review-cycle)
/open-pr --provider <name>         # --env is an alias; normally resolved from config
/open-pr --draft --issue <a,b>     # chain stopped early: draft PR naming only the completed tickets
/open-pr --no-multi                # ship only this repo; skip the sibling fan-out
/open-pr --no-watch                # skip the detached review watch (and its notification)
/open-pr --repos <dir>[,<dir>...]  # ship these sibling repos instead of auto-detecting
```

**Providers own every convention — you own none of them.** A provider encapsulates the
branch→ticket parse, the PR title prefix, the tracker-linking footer, and the review
wiring. `open-pr.sh` resolves it (explicit `--provider` → `openpr_provider=` in repo/user conf →
`provider=` if an open-pr provider of that name exists → `github`) and reports which one it used. Never assume a convention; read the script's
output rather than guessing from the repo.

## Steps

### 1. Preflight

```bash
git branch --show-current
```

If it's the repo's default branch, **stop** — nothing to ship. (`open-pr.sh` also refuses.)

### 2. Draft

If the tree is dirty, view the diff and draft a commit message:

```bash
git status
git diff HEAD
git ls-files --others --exclude-standard
```

If this branch has no PR yet, also draft the PR title and body.

**Title: bare, no ticket prefix.** Write `Add the retry guard`, not `Is42: …` or `sc-42:
…`. The provider adds its own prefix from the branch name (`Is<N>:` for `github` and
`kardashev`; the head ticket only on a chain); `open-pr.sh` verifies the result and
repairs a double (including a cross-dialect or colon-less one) itself.

On a chained branch (`git rev-parse --absolute-git-dir`'s `chain` file lists several ids),
the summary covers every ticket within the 3-bullet cap. If the chain stopped early, ship a draft
(`--draft`) whose body names the completed tickets and a **Remaining** note listing the
rest; pass only the completed ids as `--issue <a,b>` so unfinished tickets aren't closed. If no ticket completed, open no PR: report the
stall and stop.

**Body: write only two sections.** `open-pr.sh` assembles the rest (Risk, Review, Tests,
tracker footer) from the diff and the review report, so don't restate the ticket, the
commits or the review. Write each to a temp file:

- **Summary** — at most 3 one-line `- ` bullets: what changed and why.
- **Needs your judgment** — at most 3 one-line `- ` items, or the single word `none`.

The script rejects a section over its cap. Chained branches: one Summary bullet per ticket, merging tickets when there are more than 3.

First try the early draft the review cycle saved:

```bash
pr-body.sh draft load --base <default-branch> --summary-file <summary-tmp> --judgment-file <judgment-tmp>
```

Exit 0 means it matches the current commit and touched files: use the files as written. Exit 1
means missing or stale: draft both sections inline from the diff.

Show the drafted artifacts in full, then proceed immediately — running `/open-pr` is
itself the approval to commit, push, and open the PR. Don't wait for `execute`.

### 3. Ship

Write the commit message (if the tree is dirty) to a temp file, with the Co-Authored-By
trailer unless the drafted message already has one. Then one call:

```bash
# first ship — pass the title BARE, exactly as drafted:
open-pr.sh --title "<bare short title>" --summary-file <summary-tmp> --judgment-file <judgment-tmp> --test-result "<one line>" [--commit-message-file <msg-tmp>] --review <level> [--provider <name>] [--draft] [--issue <a,b>] [--no-watch]

# existing PR — reuse its title/body:
open-pr.sh [--commit-message-file <msg-tmp>] --review <level> [--provider <name>] [--no-watch]
```

`--test-result` is the one-line outcome of the project's tests from this session ("42 passed",
or "not run: <why>"). Never claim a pass that didn't run.

Forward the user's `--provider`/`--env` and `--no-watch` verbatim if they gave them; omit otherwise.
The script commits, pushes, opens or reuses the PR, triggers reviews, stamps the agent-view
row (`[REVIEW][PR]` / `[REVIEWED][PR]` / `[PR]`), and starts the detached review watch. Don't
repeat any of that by hand. It prints `pr_number`, `pr_url`, `pr_action`, `provider`,
`trigger_mode`, `pr_title`, `pr_title_repaired_from` (only if it fixed a doubled prefix —
mention it), `watch=started|skipped`, then a `Shipped … / PR … / Reviews …` block.

The watch polls for review comments in the background; when it ends it sends a macOS
notification and a `pr.watch` event. On "comments arrived", run `/github-review-comments`.
The session can be left once this step returns.

### 4. Fan out to the ticket's other repos

A ticket is often implemented across several repos, each with its own worktree on a branch
carrying the same ticket id. Steps 1–3 shipped **only the repo you're standing in**.

Skip entirely if `--no-multi`. Otherwise:

```bash
sibling-worktrees.sh                       # auto-detect
sibling-worktrees.sh --repos <dir>,<dir>   # forward the user's --repos verbatim
```

Prints `<repo>\t<worktree>\t<branch>\t<state>` per sibling with unshipped work. **No
output means nothing to fan out to** — the common case, not an error: say nothing and go
to step 5. It's local-only, so running it every ship is free.

If there *are* matches, list them and proceed — invoking `/open-pr` already approved
shipping this ticket. **Do** stop and ask if a record looks wrong: an unexpected repo, or
`dirty` where you expected `ahead`.

For **each** sibling, write a kickoff and dispatch a session into its existing worktree:

```bash
kf="$(mktemp "${TMPDIR:-/tmp}/open-pr-sibling-<repo>.XXXXXX.md")"
cat > "$kf" <<'EOF'
Working on <ticket-ref> in this worktree. Branch `<branch>` is checked out.

This ticket is being implemented across several repos. The PR for
<this-repo> is already open (<pr_url>); this session owns the
<sibling-repo> side of the same ticket, end to end.

Run `/open-pr --no-multi` here: review the diff, draft the commit message
and PR title/body for THIS repo's changes, ship it, and then run the review
cycle (`/github-review-comments`) through to sign-off. `--no-multi` is required —
the session that dispatched you already fanned out to every sibling on this
ticket, so fanning out again would race it for the same PRs.

Draft from what's actually in this worktree — do not assume this repo's
changes mirror the other repo's. Keep the PR body scoped to these changes,
and mention the companion PR <pr_url> so a reviewer can find the other half.
EOF

start-ticket.sh --tab-only "<sibling-worktree>" "$kf"
```

Don't pass `--launcher`. If the resolved launcher is `none`, no session starts: say so and
list the `cd <worktree> && claude` commands instead of silently doing nothing. Dispatch
failures are per-sibling and **non-fatal** — report with the manual fallback and keep
going. Never `cd` into a sibling worktree to ship it yourself: that pulls two codebases
into one context.

### 5. Relay

Print the script's `Shipped … / PR … / Reviews …` block as the report. Add, when step 4
found siblings:

```
Also on this ticket: <sibling-repo> (<branch>) — session dispatched, will open its own PR
                     <sibling-repo> (<branch>) — dispatch FAILED: <why>; run `cd <wt> && claude`
```

Report dispatched siblings as *sessions started*, not PRs opened — you don't know their PR
numbers and must not guess. Under `trigger_mode=auto`, the script's Reviews line says reviews
fire automatically; don't claim to have requested them.
