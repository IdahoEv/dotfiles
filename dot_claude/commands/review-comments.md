---
description: Work through unresolved review comments on the current branch's PR (automatic, quick, or slow)
argument-hint: "[automatically|quickly|slowly]"
---

# Review PR Comments

```text
/review-comments                 # Automatic Mode (default)
/review-comments automatically
/review-comments quickly
/review-comments slowly
```

**Quick or Slow:** load the `review-comments-procedure` skill and run it in that mode in this session. The interactive discussion is the point, so don't delegate it. Nothing below applies.

**Automatic:** this session is the controller. It never reads the code under review or the comments. A fresh `review-repair-agent` does the review and the edits, so implementation reasoning stays out of the review.

## 1. Identify the PR

```bash
gh repo view --json owner,name --jq '"\(.owner.login)/\(.name)"'
gh pr view --json number,url --jq '"\(.number) \(.url)"'
git branch --show-current
pwd
```

No PR → "No pull request found for the current branch." and stop.

## 2. Launch the agent

Launch `review-repair-agent` in the foreground. The kickoff carries only these lines:

```text
Run review-comments-procedure in Automatic Mode for one round.
Repo: <owner>/<repo>
PR: #<n> <url>
Branch: <branch>
Working directory: <absolute cwd>
```

## 3. Report

Print the agent's report **verbatim**. If it says `Files changed: no` and lists no planned actions, stop there.

## 4. Approve the commit

If files changed, ask one `AskUserQuestion`. Write it as if the printed report were never shown, because background sessions often don't show it.

- `question`: the findings table (file:line, finding, verdict), one line per fix, the validation line, a count of the planned GitHub actions by kind, and the full proposed commit message. End with "Commit, push, then post the GitHub actions?"
- Option 1, "Commit and push (Recommended)": `preview` = the full commit message, plus `git diff --stat` if it's short.
- Option 2, "Commit with a different message": the user supplies it via "Other".
- Option 3, "Don't commit yet": leave the changes in the working tree.

Never ask this question without the table and the commit message in it. A typed `execute` commits with the proposed message; `execute <text>` uses `<text>` as the full message instead. Append `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` unless the message already has one.

**On "Don't commit yet"**, post nothing: list the planned actions as not posted, and stop.

## 5. Commit, push, post

1. `git add` the files the agent changed, commit, and `git push`.
2. **After the push succeeds**, run the planned actions in order. The mechanics are in the `review-comments-procedure` skill under §4d (reactions, Reply, Mark Resolved, including the review-body `[RESOLVED]` edit), and §3b covers the Copilot summary comment. Post each body exactly as planned. Confirm each resolution through the API. Report every action that fails, and keep going.

If no files changed but there are planned actions (for example, rejections only), post them directly. There's no commit to gate them on.

## 6. Re-request review

GitHub auto-requests Copilot only when the PR opens. A later push gets no new pass unless one is requested. Skip this step while `~/.config/local-review-only` exists. Otherwise ask:

```text
Question: "Request another Copilot review round for this push?"
Header: "Re-review"
Options:
  1. **Request Copilot review** - "Fire another Copilot pass on the new commit(s)" (recommended on round 1; later rounds only if the fixes were substantial)
  2. **Skip this round** - "One pass was enough, or you're handling the rest manually" (recommended on round 2+)
```

On request, run `request-review.sh`. Pass `--pr <N>` if needed, or `--level copilot+claude` to add the `claude.yml` smoke-test review.

## 7. Poll

Run `agent-phase.sh REVIEW`, then run this in the background:

```bash
~/.claude/skills/review-comments-procedure/poll-pr.sh
```

It polls every 45 s for up to 2 h. Exit codes:

- **0**: new review activity. Re-invoke `/review-comments` immediately, without waiting for the user. Each round gets a fresh agent.
- **3**: reviewers signed off and there are no unresolved threads. Announce it, e.g. "✅ Reviewers signed off (Copilot, 14:32) — no unresolved threads. PR looks ready to merge." Run `agent-phase.sh --no-review` and stop.
- **1**: timeout. Say "No new bot activity after 2 hours. Polling stopped." and run `agent-phase.sh --no-review`.
- **4**: a reviewer couldn't run (Actions billing or spending limit). Name it, run `agent-phase.sh --no-review`, and don't re-poll.

A review with findings only in its body (Copilot Suppressed comments, CodeRabbit Outside-diff-range) doesn't match a sign-off marker, so it correctly exits 0.
