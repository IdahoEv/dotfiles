# Post-review commit gap, 2026-11-22

#227 asks whether the code Copilot flagged after local review existed when the local cycle last ran. It mostly did: **9 of 141** valid Copilot findings in the review window (**6.4%**) sit on a line introduced or changed after the local-review head. The missed subset is at most **9 of 123 (7.3%)**, so the share is small and no final-HEAD pass is added.

## Method

- Window: PRs created 2026-10-30 through 2026-11-17, the 2026-11-17 telemetry baseline.
- Corpus: 31 PRs with extractable Copilot findings, 141 valid/partial findings. The baseline report had 33 PRs and 145 findings; the difference is PRs whose comments yield no finding (deleted threads, review-body parsing).
- Reviewed head: the newest commit on the PR branch at or before the PR's `created_at`. Local review runs before `/open-pr`, so that is the last full-scope local head. An unattended cycle that reviewed after open makes this conservative: the real head is later, so the share can only fall.
- Classification per finding, at the Copilot comment's `original_commit_id`:
  - `introduced_after` — `git blame` attributes the flagged line to a commit that is a descendant of the reviewed head.
  - `changed_after` — the line is older but the reviewed-head..comment diff modifies that hunk.
  - `present_at_review` — neither.
- The missed subset cannot be rebuilt on this machine (`events.jsonl` has 18 local findings and no 2026-11-17 gap report). Since all misses are a subset of the 141, the number of after-review misses is at most 9.

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

Four of the nine are derived-artifact drift (three manifests, one dashboard key table), not logic written after review.

## Why the report looked worse

`later-commit-touched-file` means a commit after the Copilot comment touched the same file, not that the comment's code was new. #148 is typical: all nine findings carry that reason, and all nine lines blame to the branch's first commit, present long before the local review. Refreshing a manifest after fixing another finding marks every finding in that file, without changing whether the flagged line existed at review time.

## Decision

The share is small, so #227 AC4 applies: no final-HEAD pass, no procedure change, and no new `review.round`/`review.launch` telemetry. `docs/workflow-architecture.md` is unchanged because the cycle is unchanged. The limitation is the missing historical local findings; the bound is conservative and the direction is clear.
