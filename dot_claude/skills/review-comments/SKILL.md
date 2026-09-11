# Review PR Comments Skill

Work through unresolved code review comments on the current branch's pull request.

## Usage

```text
/review-comments
/review-comments automatically
/review-comments quickly
/review-comments slowly
```

### Mode

- **automatically** (default): "Automatic Mode" - automatically resolves comments based on validity and confidence. This is useful for large PRs with many trivial comments. Use this mode by default if no mode is specified.
- **quickly**: "Quick Mode" - runs analysis on all comments up front, then provides recommendations all at once.
- **slowly**: "Slow Mode" - works through the comments one-by-one. This gives the user more opportunity to work through complex comments, go back and forth with Claude, etc. Best for when a PR needs to be thoroughly and carefully reviewed.

## Guardrails

**DO NOT** automatically commit and push without first showing the proposed commit message and waiting for "execute" or "execute <message>".

**Every GitHub comment body this skill posts** (replies, disagree explanations, anything sent via `gh api .../comments`) is posted under the user's own authenticated GitHub identity, with no `[bot]` marker distinguishing it from a comment the user wrote by hand. To keep that distinction visible to anyone reading the thread, append this line to the end of every comment body this skill posts:

```
\n\n_🤖 Claude-generated comment_
```

## Instructions

When this skill is invoked:

### 1. Get the Current Branch and PR

First, determine the current branch and find its associated PR:

```bash
# Get the current branch name
git branch --show-current

# Get PR number for the current branch
gh pr view --json number,url,title --jq '.number'
```

If no PR exists for the current branch, inform the user and exit.

### 2. Fetch Unresolved Review Comments

Use the GitHub CLI (preferred) or MCP tool to get all review comments:

```bash
# Get all review comments with their resolution status
gh api repos/{owner}/{repo}/pulls/{pr_number}/comments --paginate
```

Or use the MCP tool:

- `mcp__github__get_pull_request_review_comments` with owner, repo, and pullNumber

Filter to only unresolved comments. A comment is unresolved if:

- It's part of a review thread that hasn't been resolved
- Check `in_reply_to_id` to identify thread structure

To check if a thread is resolved, use:

```bash
gh api graphql -f query='
  query($owner: String!, $repo: String!, $pr: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pr) {
        reviewThreads(first: 100) {
          nodes {
            isResolved
            comments(first: 10) {
              nodes {
                id
                databaseId
                body
                path
                line
                author { login }
              }
            }
          }
        }
      }
    }
  }
' -f owner="{owner}" -f repo="{repo}" -F pr={pr_number}
```

**IMPORTANT**: Remember to paginate. There may be many pages of review comments.

### 3. Fetch Reviews from `@coderabbitai` with "Outside diff range comments"

`@coderabbitai` sometimes leaves reviews with "Outside diff range comments" **embedded in the review body itself** (not as separate inline comments). These are comments that couldn't be added inline because of GitHub limitations.

**IMPORTANT**: These comments are NOT in the inline review comments API. They are in the **review body** (`body` field of a review object). You must fetch the reviews separately:

```bash
# Fetch all reviews on the PR
gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews --paginate
```

Look for reviews where:

- `user.login` is `coderabbitai[bot]` (note the `[bot]` suffix)
- `body` contains the text "Outside diff range"

**Structure of "Outside diff range comments" in the review body:**

The review body contains nested `<details>` blocks with this structure:

```html
<details>
<summary>⚠️ <strong>Outside diff range</strong> comments (N)</summary>
<blockquote>

<details>
<summary>app/src/main/java/com/example/Foo.kt (1)</summary>
<blockquote>
`185-210`: _🧹 Nitpick_ | _🔵 Trivial_

The actual comment content here...

</blockquote>
</details>

<details>
<summary>app/src/main/java/com/example/Bar.kt (1)</summary>
<blockquote>

`45`: _⚠️ Potential issue_ | _🟠 Major_

Another comment...

</blockquote>
</details>

</blockquote>
</details>
```

**Parsing these comments:**

1. Find all `<details>` blocks inside the outer "Outside diff range" block
2. Each inner `<details>` block contains one or more comments for a single file:
   - The `<summary>` tag contains the filename and number of comments on that file: `{file_path} ({n})`
   - The `<blockquote>` contains the comment(s). For files with more than 1 comment, each comment is separated by `---`.
   - Each comment usually starts with the line number(s) and severity.
3. Extract the line number(s) from patterns "`45`:" or "`199-210`:" for each

**Tracking resolved status:**

These comments can't be formally marked "Resolved" via API, so we use a workaround:

- If the `<summary>` tag is prefixed with `[RESOLVED]`, skip that comment
- Example resolved: `<summary>[RESOLVED] app/src/main/Foo.kt (1)</summary>`
- Example unresolved: `<summary>app/src/main/Foo.kt (1)</summary>`

Add all unresolved "Outside diff range" comments to the list of comments to process, treating them like regular inline comments but noting their special handling for resolution. For files with more than 1 comment, only add the `[RESOLVED]` prefix once all of the comments on that file are resolved.

### 3b. Fetch Copilot review-body findings ("Suppressed comments")

GitHub Copilot's PR reviewer (`copilot-pull-request-reviewer[bot]`) frequently posts a review whose findings are **only in the review body**, not as inline threads — under a `<summary>Suppressed comments (N)</summary>` / `Previously missed` block, one bolded `**path:line**` per finding. These create **no review thread**, so anything that only watches `reviewThreads` (including `poll-pr.sh` before it was fixed) will miss them entirely.

Always also fetch reviews (`gh api repos/{owner}/{repo}/pulls/{pr}/reviews --paginate`) and, for any `copilot-pull-request-reviewer[bot]` review, parse `**path:line**` bullets out of the body and add them to the processing list. There is no API to mark these resolved; after handling them, post a short PR comment summarising what changed (and, if the review said so, a new push will trigger another Copilot pass).

### 4. Process Each Unresolved Comment

For each unresolved comment thread, do the following:

#### a. Display the Comment

Show the user:

- **File**: The file path where the comment was made or refers to
- **Line**: The line number(s) the comment refers to
- **Author**: Who made the comment
- **Comment**: The full comment text
- **Thread**: Any replies in the thread (this is only relevant for inline comments)

Format example:

```text
## Comment 1 of N

**File:** file:///{absolute_file_path}:42
**Author:** @reviewer-username
**Comment:**
> This could be simplified using `let` instead of the null check.

**Thread:**
  - @author-username: I wasn't sure if that would work here because...
  - @reviewer-username: Good point, but I think it should still work.
```

Any "suggestion" blocks in the comment should be correctly color-coded as a git diff.

#### b. Give your opinion on this comment

Analyze this comment. Read the comment, the suggested fix (if any), the code context, and do any necessary research. Then form an educated opinion of the validity of this comment. Is it accurate? Is it worth fixing? Does it adhere to our code guidelines and engineering principles? Show your analysis, state your opinion, print two lines of 20 "=" symbols, and then proceed.

#### c. Present Options to User

Use the **AskUserQuestion** tool with options based on the comment author.

**For comments from `@coderabbitai` or Copilot** (author login is `coderabbitai`, `coderabbitai[bot]`, or Copilot):

```text
Question: "How would you like to handle this coderabbit comment?"
Header: "Action"
Options:
  1. **Fix** - "Implement the suggestion (auto 👍 reaction)"
  2. **👎 Disagree** - "React with thumbs down, optionally explain why, and resolve"
  3. **Mark Resolved** - "Mark this comment thread as resolved"
  4. **Reply** - "Reply to this comment on GitHub"
  5. **Skip** - "Skip this comment and continue to the next one"
```

**For comments from human reviewers:**

```text
Question: "How would you like to handle this comment?"
Header: "Action"
Options:
  1. **Fix** - "Work through the comment and implement a fix"
  2. **Mark Resolved** - "Mark this comment thread as resolved"
  3. **Reply** - "Reply to this comment on GitHub"
  4. **Skip** - "Skip this comment and continue to the next one"
```

Based on your informed opinion from the previous step and the actions that have already been taken on this comment (if any), add a `(Recommended)` suffix to the most appropriate option label.

#### d. Handle Each Option

##### Option: Fix

1. Discuss the comment with the user.
2. Read the relevant file and surrounding code for context
3. Propose a fix based on the reviewer's feedback. If the reviewer left a suggestion, first ask the user if they want to accept the suggestion. Otherwise, propose your own fix.
4. Run validation and formatting tools on the changed file(s) (see **Validation & Formatting** below) and resolve anything they surface before continuing.
5. If any changes were applied, use the **AskUserQuestion** tool to ask if they want to commit this change, and include the validation status in the prompt. If the user answers Yes, then use the `/commit` skill to commit the change.
6. **For coderabbit and Copilot comments only:** After successfully implementing the fix, automatically add a 👍 reaction:

   ```bash
   gh api repos/{owner}/{repo}/pulls/comments/{comment_id}/reactions \
     -X POST \
     -f content="+1"
   ```

7. **Return to the same menu** so the user can Reply, Mark Resolved, or Skip

##### Option: 👎 Disagree (coderabbit/Copilot comments only)

This option is for when coderabbit's suggestion is incorrect, overly pedantic, or not applicable.

1. Add a 👎 reaction to provide feedback to coderabbit:

   ```bash
   gh api repos/{owner}/{repo}/pulls/comments/{comment_id}/reactions \
     -X POST \
     -f content="-1"
   ```

2. Based on your earlier analysis, draft a brief reply explaining why the comment is being dismissed. **Always tag `@coderabbitai` in replies to coderabbit comments** so the bot receives the feedback (e.g., "@coderabbitai This is a false positive - the table name comes from a hardcoded enum switch, not user input."). Append the `🤖 Claude-generated comment` disclosure line (see Guardrails) before posting.

3. Ask the user how to handle the reply using AskUserQuestion:

   ```text
   Question: "How would you like to reply?"
   Header: "Reply"
   Options:
     1. **Use suggested reply** - "[Show the drafted reply text]"
     2. **Custom reply** - "Write your own reply (use Other)"
     3. **No reply** - "Just resolve without replying"
   ```

4. If a reply is chosen, post it (see Reply option below for how)

5. Resolve the comment thread (see Mark Resolved option below for how)

6. **Continue to the next comment**

##### Option: Mark Resolved

1. Depending on the type of comment, do one of the following:

   - For inline review comments, resolve the review thread using the GraphQL API:

      ```bash
      # First get the thread ID
      gh api graphql -f query='
        query($owner: String!, $repo: String!, $pr: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pr) {
              reviewThreads(first: 100) {
                nodes {
                  id
                  isResolved
                  comments(first: 1) {
                    nodes {
                      databaseId
                    }
                  }
                }
              }
            }
          }
        }
      ' -f owner="{owner}" -f repo="{repo}" -F pr={pr_number}

      # Then resolve the thread
      gh api graphql -f query='
        mutation($threadId: ID!) {
          resolveReviewThread(input: {threadId: $threadId}) {
            thread {
              isResolved
            }
          }
        }
      ' -f threadId="{thread_id}"
      ```

   - For "Outside of diff range" comments from `@coderabbitai`, these cannot be resolved via the API because they're embedded in the **review body**, not as separate comments. Instead, edit the review to mark the specific sub-comment as resolved.

     **Important:** Use the reviews API endpoint, not the comments endpoint:

     ```bash
     # Get the current review body (note: reviews endpoint, not comments)
     current_body=$(gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id} --jq '.body')

     # Mark the specific sub-comment as resolved by file path and number
     # Example: file_path="app/src/main/Foo.kt", comment_num="1"
     # Escape regex metacharacters for the search pattern only
     escaped_path=$(echo "{file_path}" | sed 's/[][\/.^$*+?|(){}]/\\&/g')
     updated_body=$(echo "$current_body" | sed "s/<summary>${escaped_path} ({comment_num})<\/summary>/<summary>[RESOLVED] {file_path} ({comment_num})<\/summary>/")

     # Update the review body
     gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id} \
       -X PUT \
       -f body="$updated_body"
     ```

     The `{review_id}` comes from the review object's `id` field when you fetched the reviews in step 3.
2. Confirm the thread was resolved (or comment was updated)
3. **Continue to the next comment**

##### Option: Reply

1. Ask the user what they want to say using AskUserQuestion (free text input via "Other")
2. Post the reply to GitHub using one of these methods:

   **For review comments (in_reply_to supported):** (`{reply_text}` must already end with the `🤖 Claude-generated comment` disclosure line from Guardrails)

   ```bash
   gh api repos/{owner}/{repo}/pulls/{pr_number}/comments \
     -X POST \
     -f body="{reply_text}" \
     -F in_reply_to={parent_comment_id}
   ```

   **For top-level comments (no in_reply_to):**
   Add a new comment quoting the original (again, `{reply_text}` must end with the disclosure line):

   ```bash
   gh api repos/{owner}/{repo}/pulls/{pr_number}/comments \
     -X POST \
     -f body="Replying to @{author}'s comment:\n> {quoted_original}\n\n{reply_text}" \
     -f commit_id="{commit_sha}" \
     -f path="{file_path}" \
     -F line={line_number}
   ```

3. Confirm the reply was posted successfully
4. **Return to the same menu** so the user can Fix, Mark Resolved, or Skip

##### Option: Skip

1. Do nothing
2. **Continue to the next comment**

### 5. Summary Report

After processing all comments, show a summary using the **structured findings table format** (see below), followed by the roll-up counts:

```text
Total unresolved comments: N
- Fixed: X (👍 reactions added for coderabbit)
- Disagreed: Y (👎 reactions added for coderabbit)
- Replied: Z
- Resolved: W
- Skipped: V

Remaining unresolved: N - W (comments marked resolved are no longer unresolved)
```

#### Structured findings table format

Every findings summary — the per-round Automatic Mode summary, the Quick Mode up-front summary, and the final report at the end of a run — uses this format:

- Open with a horizontal rule (`---`) immediately before the heading, and close with another horizontal rule (`---`) immediately after the table, so the block is visually separated from surrounding narration.
- A one-line heading naming the round/batch and a source breakdown, e.g. `### Round 12 — 4 findings, all CodeRabbit` or `### Findings — 6 total (4 CodeRabbit, 2 Copilot)`.
- A single Markdown table with these columns, in this order:

| # | File : Line | Finding | Verdict |
|---|---|---|---|
| 1 | `path/to/file.ts:42` | One-sentence statement of what the comment claims | ✅ **Valid** — fixed |
| 2 | `path/to/file.ts:88` | One-sentence statement of what the comment claims | ❌ **Rejected** — one-clause reason |
| 3 | `path/to/other.ts:12` | One-sentence statement of what the comment claims | ⚠️ **Partially valid** — one-clause nuance |

Verdict column rules:

- Always lead with one of these exact glyphs, bolded: `✅ **Valid**`, `❌ **Rejected**`, `⚠️ **Partially valid**`, or `⏭️ **Skipped**` (low confidence / deferred to the user).
- Follow the glyph with an em-dash and a terse clause — `— fixed`, `— disagreed, replied`, `— already handled elsewhere`, `— verified against the model, claim doesn't hold`. Keep it to a few words; the full reasoning belongs in prose above or below the table, not crammed into the cell.
- The **File : Line** column always cites the file the finding is anchored to, even when the actual fix landed in a different file (note that in the Finding cell or in surrounding prose).
- For a comment that "Affects N files" (CodeRabbit's own cross-file annotation) or where you additionally fixed a parallel/duplicate issue you noticed elsewhere, give it its own row rather than folding it into one cell — one row per file:line touched, not one row per source comment.
- Keep rows in the order the comments were processed (typically file, then line), matching the rest of this skill's ordering convention.

## Modes

### Default: "Automatic Mode"

If invoked with no arguments or with "automatically", perform this skill in "Automatic Mode":

1. Go through every comment up front to perform your analysis.
2. Automatically perform your recommended action for each comment based on your analysis and confidence level:
  - If you have high confidence in your recommendation (fix, mark resolved, dismiss, disagree, etc) and that the user will agree with your recommendation, automatically apply it without asking the user.
  - If you are not confident in your recommendation or there's a strong reason the user might disagree, skip the comment with no action.
3. Once all fixes are applied, run validation and formatting (see **Validation & Formatting** below) once across all changed files and resolve anything it surfaces before showing the summary. If a fix can't be made to pass validation, flag it in the summary rather than leaving it broken.

At the end, show a summary using the **structured findings table format** above — one row per file:line touched, verdict glyph plus terse reason in the Verdict column. Put the fuller rationale for any non-obvious verdict (why something was rejected or only partially valid) in a sentence or two above or below the table, not squeezed into a cell. Note validation status (lint/typecheck/tests) as a line beneath the table rather than as a table column.

**After showing the summary**, if any file changes were made, draft a commit message and display it to the user before taking any further action. Then wait — see **Commit, Push & Poll** below for how to proceed.

### "Quick Mode"

If invoked with "quickly", perform this skill in "Quick Mode": instead of working through the comments one-by-one, go through every comment up front and then summarize each one with the comment, your analysis, and your recommendation. Present the summary to the user, and then stop and wait for the user will tell you what to do with each one.

- **DO NOT** use the `AskUserQuestion` tool to ask the user what to do - they will tell you.

### "Slow Mode"

If invoked with "slowly", perform this skill in "Slow Mode": work through the comments one-by-one, giving the user the opportunity to fully process each comment and take action before moving to the next one.

## Commit, Push & Poll

This section governs the commit/push/poll cycle that follows a completed Automatic Mode run.

### After showing the summary (Automatic Mode only)

If any file changes were made, output the proposed commit message in full — do not commit yet. Example:

```
Proposed commit message:

  Fix A-6 externalId requirement: extend page query to include Pulse external ID

  SegmentMemberRow currently only carries internal member id; A-6 bulk fetch
  requires externalId. Members with null externalId fall through to per-member
  collection rather than being included in the bulk request.

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

Say "execute" to commit and push with this message, or "execute <your message>" to override.
```

Then wait for the user.

### "execute" shorthand

| User input | Meaning |
|---|---|
| `execute` | Commit and push using the proposed message shown above, then start the polling loop |
| `execute <text>` | Commit and push using `<text>` as the full commit message instead, then start the polling loop |

Co-author trailer (`Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`) is always appended unless the user's override message already contains it.

### Polling loop (automatic, after every commit + push)

After a successful `git push`, run the polling script in the background:

```bash
~/.claude/skills/review-comments/poll-pr.sh
```

The script polls every 45 seconds for up to 2 hours. Exit codes:

- **0** — new review activity detected (possible complaints). **Immediately re-invoke the review-comments skill in Automatic Mode** without waiting for the user to say anything.
- **3** — AI reviewers have signed off (latest non-author activity is a review that is APPROVED or whose body matches a known all-clear marker — Copilot "Merge recommended"/"No issues found", CodeRabbit "Merge approved"/"Verified successful" — and there are zero unresolved threads). Do **not** re-process comments; instead announce to the user, e.g.: **"✅ Reviewers signed off (Copilot, 14:32) — no unresolved threads. PR looks ready to merge."** Then stop and wait for the user.
- **1** (timeout) — notify the user: "No new bot activity after 2 hours. Polling stopped."

Note the distinction: exit 0 means "something happened, go look"; exit 3 means "checked, and it's an all-clear." A findings-in-body review (Copilot Suppressed comments, CodeRabbit Outside-diff-range) does not match the sign-off markers, so it correctly exits 0.

## Error Handling

- **No PR found**: "No pull request found for the current branch."
- **No unresolved comments**: "No unresolved review comments found on this PR."
- **GitHub API errors**: Show the error message and suggest the user check their GitHub authentication (`gh auth status`)
- **IDE command not found**: "Could not open file in IDE. Please open manually: {file_path}:{line}"

## Tips

- The skill processes comments in the order they appear on the PR (typically by file, then by line)
- When fixing code, always read the full context around the commented line
- Validation and formatting run automatically after each fix (see **Validation & Formatting**) — you shouldn't need to run them manually
- If you've made multiple fixes, consider committing them with `/commit` before continuing

## Repository Detection

To determine the owner and repo:

```bash
gh repo view --json owner,name --jq '"\(.owner.login)/\(.name)"'
```

Or parse from the remote URL:

```bash
git remote get-url origin
# Parse: git@github.com:owner/repo.git or https://github.com/owner/repo.git
```

## Validation & Formatting

Before presenting any applied fix for feedback — the commit-confirmation prompt in Quick/Slow mode, or the final summary in Automatic Mode — run the repo's validation and formatting tools and resolve anything they surface. This skill runs across many repositories, so detect the tooling per-repo; never assume a specific language or package manager.

### Detection

Check in this order and use the first match:

1. **Documented commands** — a `CLAUDE.md`, `AGENTS.md`, or `README` section describing lint/format/typecheck/test commands. Prefer these over guessing.
2. **Node/JS/TS** — `package.json` present:
   - Package manager from the lockfile: `yarn.lock` → `yarn`, `pnpm-lock.yaml` → `pnpm`, `package-lock.json`/none → `npm`
   - Run whichever of `lint`, `format`/`format:check`, `typecheck`, `test` scripts are defined in `package.json`
3. **Python** — `pyproject.toml`/`setup.cfg`/`requirements.txt` present:
   - Format: `ruff format` or `black .`, whichever is configured
   - Lint: `ruff check` or `flake8`
   - Types: `mypy` if configured
   - Tests: `pytest`
4. **Rust** — `Cargo.toml` present: `cargo fmt`, `cargo clippy`, `cargo test`
5. **Go** — `go.mod` present: `gofmt -l -w` / `goimports -w`, `go vet ./...`, `go test ./...`
6. **Nothing detected** — ask the user once per session (not once per comment) which commands to run, then reuse the answer for the rest of the run.

### Running

- Scope to the changed file(s) where the tool supports it (e.g. `eslint path/to/file.ts`, `ruff check path/to/file.py`) rather than the whole repo, to stay fast on large PRs.
- Run formatters first and let them auto-fix, then lint/typecheck/test.
- If a check fails because of your fix, resolve it before moving on — don't hand the user a broken build.
- If a check fails for a reason unrelated to your change (a pre-existing failure), note that rather than trying to fix it.
- Surface a one-line status alongside the diff, e.g. `✅ lint/typecheck/tests pass` or `⚠️ 2 lint errors fixed, tests pass`.
