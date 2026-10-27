---
description: Work through unresolved review comments on the current branch's PR (automatic, quick, or slow)
argument-hint: "[automatically|quickly|slowly]"
---

# Review PR Comments

```text
/github-review-comments                 # Automatic Mode (default)
/github-review-comments automatically
/github-review-comments quickly
/github-review-comments slowly
```

**Quick or Slow:** load the `github-review-procedure` skill and run it in that mode in this session. The interactive discussion is the point, so don't delegate it. Nothing below applies.

**Automatic:** this session is the controller. It never reads the code under review or the comments. A fresh `github-review-repair-agent` does the review and the edits, so implementation reasoning stays out of the review.

## 1. Identify the PR

```bash
gh repo view --json owner,name --jq '"\(.owner.login)/\(.name)"'
gh pr view --json number,url --jq '"\(.number) \(.url)"'
git branch --show-current
pwd
```

No PR → "No pull request found for the current branch." and stop.

## 2. Launch the agent

Launch `github-review-repair-agent`. The kickoff carries only these lines:

```text
Run github-review-procedure in Automatic Mode for one round.
Repo: <owner>/<repo>
PR: #<n> <url>
Branch: <branch>
Working directory: <absolute cwd>
```

Add nothing else: no prior verdicts, no framing of specific comments, no priorities. This session may already hold opinions about the PR, and the agent's value is not inheriting them. The agent reads CLAUDE.md, so standing user preferences reach it anyway.

If the agent runs in the background, wait for its completion notice. Don't act on partial output.

## 3. Report

Print the agent's report **verbatim**. If it says `Files changed: no` and lists no planned actions, run `agent-phase.sh --no-review`, say the round found nothing to do and polling has stopped, and stop.

## 4. Approve the commit

If files changed, ask one `AskUserQuestion`. Write it as if the printed report were never shown, because background sessions often don't show it.

- `question`: the findings table (file:line, finding, verdict), one line per fix, the validation line, a count of the planned GitHub actions by kind, and the full proposed commit message. End with "Commit, push, then post the GitHub actions?"
- Option 1, "Commit and push (Recommended)": `preview` = the full commit message, plus `git diff --stat` if it's short.
- Option 2, "Commit with a different message": the user supplies it via "Other".
- Option 3, "Don't commit yet": leave the changes in the working tree.

A typed `execute` commits with the proposed message; `execute <text>` uses `<text>` as the full message instead. Append this session's commit attribution trailer unless the message already has one.

**On "Don't commit yet"**, post nothing: list the planned actions as not posted, run `agent-phase.sh --no-review`, say polling has stopped, and stop.

## 5. Commit, push, post

1. `git add` exactly the paths the agent listed, commit, and `git push`. If either fails, post nothing, report the error, and stop.
2. **After the push succeeds**, run the planned actions in order using the `gh api` snippets in the `github-review-procedure` skill's §4d (reactions, Reply, Mark Resolved, including the review-body `[RESOLVED]` edit); `pr-comment` rows go through `gh pr comment`. Skip 4d's conversational steps — the bodies are already final. Post each body exactly as planned. Confirm each resolution through the API. Report every action that fails, and keep going.

If no files changed but there are planned actions (for example, rejections only), post them directly. There's no commit to gate them on. Then run `agent-phase.sh --no-review`, say polling has stopped because nothing was pushed to trigger a new review, and stop. Skip steps 6 and 7.

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
~/.claude/skills/github-review-procedure/github-review-poll.sh
```

It polls every 45 s for up to 2 h. Exit codes:

- **0**: new review activity. Re-invoke `/github-review-comments` immediately, without waiting for the user. Each round gets a fresh agent.
- **3**: reviewers signed off and there are no unresolved threads. Announce it, e.g. "✅ Reviewers signed off (Copilot, 14:32) — no unresolved threads. PR looks ready to merge." Run `agent-phase.sh --no-review` and stop.
- **1**: timeout. Say "No new bot activity after 2 hours. Polling stopped." and run `agent-phase.sh --no-review`.
- **2**: no PR found. Say so, run `agent-phase.sh --no-review`, and stop.
- **4**: a reviewer couldn't run (Actions billing or spending limit). Name it, run `agent-phase.sh --no-review`, and don't re-poll.

A review with findings only in its body (Copilot Suppressed comments, CodeRabbit Outside-diff-range) doesn't match a sign-off marker, so it correctly exits 0.
