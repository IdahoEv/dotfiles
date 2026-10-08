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
/open-pr --provider <name>         # --env is an alias; normally resolved from config, don't pass it
/open-pr --no-compact              # skip the context compaction that normally runs after shipping
```

`--review` levels: `none` (no review request), `copilot` (default — request the
Copilot bot via the `requestReviews` mutation; safe), `copilot+claude` (also
dispatch `claude.yml`; opt-in only).

**Providers own every convention — you own none of them.** A provider
encapsulates the branch→ticket parse, the PR title prefix, any tracker-linking
body footer, and the review-bot wiring. `open-pr.sh` resolves one from
an explicit `--provider`/`--env` override if given (highest precedence), else
`openpr_provider=` in the repo's `.start-ticket.conf`, else
`~/.config/start-ticket/config`, else `kardashev`; it searches
`<repo>/.git-tools/open-pr-providers`, `~/.config/git-tools/open-pr-providers`,
then `git-tools/open-pr-providers`. So the shipped `kardashev` is **not** the
only one — per-machine providers are normal and invisible from here. Never
assume a particular convention; if you need to know which provider is active,
read the conf (or the `--provider`/`--env` value, which overrides it) rather than guessing from the repo.

Each provider also declares a **trigger mode**: `manual` providers dispatch
review bots when `open-pr.sh` runs; `auto` providers have bots (Copilot,
CodeRabbit, …) that fire on PR open by themselves, and `open-pr.sh` skips
dispatch entirely. Under an `auto` provider `--review` changes nothing — don't
report "reviews requested" as if you triggered them, and don't pass
`--review none` expecting to suppress them. Step 5's polling is what matters in
both modes.

## Steps

### 1. Preflight

```bash
git branch --show-current
```

Resolve the repository's default branch (`git symbolic-ref --short
refs/remotes/origin/HEAD`, stripping `origin/`; don't assume `main`/`master` —
`development` etc. are common). `origin/HEAD` may be unset locally; if the
command prints nothing, fall back to `git remote show origin` ("HEAD branch:"),
then the host CLI (`gh repo view --json defaultBranchRef -q
.defaultBranchRef.name` on GitHub). If you still can't determine it, ask rather
than proceeding. If the current branch is the default branch: **stop** — there's
nothing to ship.

### 2. Draft

If the tree is dirty, view the diff and draft a commit message:

```bash
git status
git diff HEAD
git ls-files --others --exclude-standard
```

If this branch has no PR yet, also draft the PR title and body.

**Draft the title bare — no ticket prefix.** Write `Add the retry guard`, not
`Is42: Add the retry guard` and not `sc-42: Add the retry guard`. The provider
adds its own prefix (`Is<NNN>: ` / `sc-<id>: ` / none) from the branch name.
Prefixing it yourself in the *wrong* dialect defeats the provider's
idempotency check and produces a double prefix — this is how `sc-73237:
Is73237: …` reached production. If a prefix genuinely belongs in the title and
the provider isn't adding it, fix the provider, not the draft.

**Draft the body as a real summary, and stop there** — no `Closes #<NNN>`, no
Shortcut URL, no tracker-linking footer of any kind. Whether the tracker links
via an auto-close keyword, a branch-name integration, or nothing at all is the
provider's business: `open-pr.sh` appends `provider::pr_body_footer` when the
provider defines one, and skips it when the body already contains it. A
hand-written footer either duplicates the provider's or points into the wrong
namespace (`Closes #74085` in a repo with no GitHub issues silently references
an unrelated *PR* #74085).

Write what a reviewer needs: what changed, why, and anything that needs their
judgment. Match the repo's existing PR bodies for depth.

Show all drafted artifacts in full, then proceed immediately — running
`/open-pr` is itself the approval to commit + push + open the PR. Do not wait
for `execute`.

### 3. Commit (if dirty)

```bash
git add -A
git commit -m "<drafted message>"
```

`open-pr.sh` never commits. Append the Co-Authored-By trailer unless the
approved message already has one.

### 4. Ship

```bash
# first ship — create the PR with the approved metadata:
open-pr.sh --title "<bare short title>" --body-file <tmp-file> --review <level> [--provider <name>]

# re-trigger on an existing PR — reuse existing title/body:
open-pr.sh --review <level> [--provider <name>]

# [--provider <name>]: forward the user's --provider/--env argument verbatim to
# both invocations if they gave one; omit it otherwise.
```

Pass the title **bare**, exactly as drafted in step 2 — the provider prefixes it.

Capture `pr_number` from stdout (also prints `pr_url`, `pr_action`).

Then read the PR title back (`gh pr view <n> --json title`) and confirm it has
the prefix the active provider expects — exactly one for providers that prefix,
none for a `none`-prefix provider (a bare title is valid there, don't "fix" it).
A doubled prefix means the drafted title carried one;
fix it with `gh pr edit <n> --title "<corrected>"` and note it in the report.

Then, directly in this session (not through the script), run:

```bash
git push --no-verify origin "$(git branch --show-current)"
```

`--no-verify` skips `pre-push` for this second push — `open-pr.sh` already ran the
real push and its validation, so there's no need to repeat (or risk re-failing)
expensive hook checks for a metadata-only no-op. It's a no-op ("Everything
up-to-date") because `open-pr.sh` already pushed. In an
agent-view background session this lets Claude Code see a push to the branch and
link the PR on the session's row; the push inside `open-pr.sh` happens in the
script's own process and may not be picked up. Harmless in any other session.

### 5. Poll

```bash
~/.claude/skills/review-comments/poll-pr.sh <pr_number>
```

Run in the background. On completion: exit 0 → re-invoke `/review-comments`;
exit 3 → reviewers signed off (ready to merge); exit 1 → timeout; exit 2 → no
PR found. Default 2 review rounds before treating the PR as converged.

Skip this **only** when `--review none` was passed *and* the provider's trigger
mode is `manual` — that combination is the one case where no bot will ever
comment. Under an `auto` provider the bots fire on PR open regardless of
`--review`, so skipping the poll would strand the PR with unread review
comments. When in doubt, poll.

### 6. Report

```
Shipped <ticket-ref> — <title>
PR #<n>: <url>  (created | reused)
Reviews: <requested: copilot|copilot+claude  |  automatic on PR open (<bots>)  |  none>
```

Use the provider's own ticket dialect in `<ticket-ref>` (`Is42`, `sc-74085`, …)
— take it from the PR title rather than inventing a format (a `none`-prefix provider has no prefix; use the branch's ticket id or just the title). Under an `auto`
provider say reviews fire automatically; don't claim to have requested them.

### 7. Compact

The implementation context that got the branch shipped isn't needed for the
review-poll cycle that follows. Run `/compact` by default after reporting,
unless `--no-compact` was passed or the user said otherwise for this run.
