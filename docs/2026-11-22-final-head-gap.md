# Post-review commit gap, 2026-11-22

#227 asks whether the code Copilot flagged after local review existed when the local cycle last ran. It mostly did: **9 of 141** Copilot findings rated valid or partial in the review window (**6.4%**) sit on a line introduced or changed after the local-review head. The baseline report counted 123 misses of 145 valid-or-partial findings (`tools/lib/wf_review_gaps.py:403` counts both); the 141 here are the same population minus four findings this environment cannot extract. Even if all nine after-review findings, plus the four uncaptured ones, were misses, the missed share is at most **13/123 = 10.6%**, and it is likely lower because a fix commit's line can still be caught by the later local round that reviews that commit. The decision rests on the small absolute count: about 0.3 per PR, so no final-HEAD pass is added.

## Method

- Window: PRs created 2026-10-30 through 2026-11-17, the 2026-11-17 telemetry baseline.
- Corpus: 31 PRs with extractable Copilot findings, 141 valid/partial findings. The baseline report had 33 PRs and 145 findings; the difference is PRs whose comments yield no finding (deleted threads, review-body parsing). The excluded 4 findings are unclassified; if all four were after-review, the share is (9+4)/145 = 9.0%.
- Reviewed head: the newest commit on the PR branch at or before the PR's `created_at`. Local review runs before `/open-pr`, so that is the proxy for the last full-scope local head. It is imperfect in both directions. A cycle that reviewed after open means the real head is later, so the share would fall. But `tools/open-pr.sh` commits any dirty tree (`git add -A; git commit`) just before creating the PR, so the newest commit at `created_at` can be an unreviewed one; then the real head is earlier and the share would rise. Per-PR round-start SHAs (`review.round` `start`, `tools/lib/wf_review_gaps.py:344-345`) would remove the ambiguity, but that telemetry is not available for this window (see the missed-subset note below), so the 9/141 figure is not corrected for either bias.
- Classification per finding, at the Copilot comment's `original_commit_id`:
  - `introduced_after` — `git blame` attributes the flagged line to a commit that is a descendant of the reviewed head.
  - `changed_after` — the line is older but the reviewed-head..comment diff modifies that hunk.
  - `present_at_review` — neither.
- The missed subset cannot be rebuilt on this machine (`events.jsonl` has 18 local findings and no 2026-11-17 gap report). The 9 after-review findings are an upper bound on the after-review misses: a line introduced by a fix commit can still be caught by the later local round that reviews that commit, so some of the 9 may have been matched. Add the 4 unclassified findings for the worst case: at most 13 of the report's 123 misses, 10.6%.

## Result

| Class | Findings |
| --- | ---: |
| Present at the reviewed head | 132 |
| Introduced after | 5 |
| Changed after | 4 |
| **Introduced or changed after** | **9 / 141 = 6.4%** |

The nine:

| PR | Finding | Class |
| --- | --- | --- |
| #145 | `tools/cloud-workflow-bootstrap.sh:100` | introduced |
| #154 | `dot_claude/skills/github-review-procedure/SKILL.md:399` | introduced |
| #165 | `workflow/manifest.txt:1` | introduced |
| #165 | `run_onchange_after_register-mcp-servers.sh:8` | changed |
| #186 | `tools/agy-tmux.sh:100` | introduced |
| #196 | `tools/lib/agy_tmux_dashboard.py:27` | changed |
| #196 | `tools/lib/agy_tmux_dashboard.py:402` | changed |
| #196 | `workflow/manifest.txt:63` | introduced |
| #200 | `tools/agent-phase.sh:135` | changed |

Four of the nine are derived-artifact drift (two `workflow/manifest.txt` rows, two dashboard key-table lines), not logic written after review.

## Why the report looked worse

`later-commit-touched-file` means a commit after the Copilot comment touched the same file, not that the comment's code was new. #148 is typical: all nine findings carry that reason, and all nine lines blame to the branch's first commit, present long before the local review. Refreshing a manifest after fixing another finding marks every finding in that file, without changing whether the flagged line existed at review time.

## Decision

Threshold: material means a recurring per-PR loss worth a new pass and telemetry; about 0.3 findings per PR, a worst-case 10.6% of misses, and four of nine being derived-artifact drift do not meet it. #227 AC4 applies: no final-HEAD pass, no procedure change, and no new `review.round`/`review.launch` telemetry. `docs/workflow-architecture.md` is unchanged because the cycle is unchanged. The limitation is the missing historical local findings, which leaves the exact missed-subset share unmeasured; the worst case is still small.
