# Open a Pull Request

Push the current branch, open (or reuse) its PR, and trigger reviews — the middle leg of
the `/start` → `/open-pr` → `/finalize` cycle.

`open-pr.sh` handles every mechanical step (push, PR create-or-reuse, title prefixing and
repair, review-bot triggering). It **never commits** — drafting the commit message and PR
title/body is this command's job.

## Usage

```text
/open-pr
/open-pr --review none|copilot|copilot+claude    # default: copilot
/open-pr --provider <name>         # --env is an alias; normally resolved from config
/open-pr --no-compact              # skip the post-ship context compaction
/open-pr --no-multi                # ship only this repo; skip the sibling fan-out
/open-pr --repos <dir>[,<dir>...]  # ship these sibling repos instead of auto-detecting
```

**Providers own every convention — you own none of them.** A provider encapsulates the
branch→ticket parse, the PR title prefix, the tracker-linking footer, and the review
wiring. `open-pr.sh` resolves it (explicit `--provider` → repo conf → user conf →
`kardashev`) and reports which one it used. Never assume a convention; read the script's
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
…`. The provider adds its own prefix from the branch name; `open-pr.sh` verifies the
result and repairs a double (including a cross-dialect one) itself.

**Body: a real summary, and stop there** — no `Closes #<NNN>`, no Shortcut URL, no
tracker-linking footer. `open-pr.sh` appends `provider::pr_body_footer` when the provider
defines one. A hand-written footer either duplicates it or points into the wrong namespace
(`Closes #74085` in a repo with no GitHub issues silently references an unrelated *PR*).

Write what a reviewer needs: what changed, why, what needs their judgment. Match the
repo's existing PR bodies for depth.

Show the drafted artifacts in full, then proceed immediately — running `/open-pr` is
itself the approval to commit, push, and open the PR. Don't wait for `execute`.

### 3. Commit (if dirty)

```bash
git add -A
git commit -m "<drafted message>"
```

Append the Co-Authored-By trailer unless the approved message already has one.

### 4. Ship

```bash
# first ship — pass the title BARE, exactly as drafted:
open-pr.sh --title "<bare short title>" --body-file <tmp-file> --review <level> [--provider <name>]

# existing PR — reuse its title/body:
open-pr.sh --review <level> [--provider <name>]
```

Forward the user's `--provider`/`--env` verbatim if they gave one; omit otherwise.
Capture from stdout: `pr_number`, `pr_url`, `pr_action`, `provider`, `trigger_mode`,
`pr_title`, and `pr_title_repaired_from` (present only if the script fixed a doubled
prefix — mention it in the report). No need to read the title back yourself.

Then, directly in this session, run:

```bash
git push --no-verify origin "$(git branch --show-current)"
```

A no-op ("Everything up-to-date") that lets an agent-view session see a push and link the
PR on its row; `open-pr.sh`'s own push happens in a subprocess and may not register.
`--no-verify` because the real push already ran the hooks.

### 4a. Fan out to the ticket's other repos

A ticket is often implemented across several repos, each with its own worktree on a branch
carrying the same ticket id. Steps 1–4 shipped **only the repo you're standing in**.

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

Run `/open-pr` here: review the diff, draft the commit message and PR
title/body for THIS repo's changes, ship it, and then run the review cycle
(`/review-comments`) through to sign-off.

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

### 5. Poll

```bash
~/.claude/skills/review-comments/poll-pr.sh <pr_number>
```

Run in the background. Exit 0 → re-invoke `/review-comments`; 3 → signed off, ready to
merge; 1 → timeout; 2 → no PR found.

Skip **only** when `--review none` was passed *and* `trigger_mode=manual` — the one case
where no bot will ever comment. Under `trigger_mode=auto` the bots fire on PR open
regardless of `--review`. When in doubt, poll.

Poll **only this session's PR**. Each sibling runs its own `/open-pr` and polls its own —
one session per PR. Polling a sibling's from here would race it.

### 6. Report

```
Shipped <ticket-ref> — <title>
PR #<n>: <url>  (created | reused)
Reviews: <requested: copilot|copilot+claude  |  automatic on PR open  |  none>
Also on this ticket: <sibling-repo> (<branch>) — session dispatched, will open its own PR
                     <sibling-repo> (<branch>) — dispatch FAILED: <why>; run `cd <wt> && claude`
```

Omit the "Also on this ticket" lines when step 4a found no siblings. Report dispatched
siblings as *sessions started*, not PRs opened — you don't know their PR numbers and must
not guess. Take `<ticket-ref>` from the `pr_title` the script reported rather than
inventing a format. Under `trigger_mode=auto`, say reviews fire automatically; don't claim
to have requested them.

### 7. Compact

The implementation context isn't needed for the review-poll cycle that follows. Run
`/compact` after reporting, unless `--no-compact` was passed.
