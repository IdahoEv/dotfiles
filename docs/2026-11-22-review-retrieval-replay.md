# Retrieval-contract replay, 2026-11-22

Evidence for #220's AC5: does the `reviewer-contract` retrieval section catch Copilot findings the pre-change prompts missed, and what does it cost?

## Method

- PRs: dotfiles #148, #154, #210, #216. #169 was the ticket's fourth example but `gh` returns zero Copilot comments on it, so #154 (review-procedure telemetry, 9 findings) replaced it.
- State: each PR's first Copilot review head (`0ce21788`, `8711642c`, `b34bd37e`, `b909c8e4`) and the PR base. The final merge head was not used: Copilot's findings were fixed by later commits, so they are absent there.
- Targets: the Copilot findings in that first batch, 6/6/5/7 per PR. Validity is the backfill inference; #216's two adapter-test findings were later dismissed in-thread, so the target set is slightly optimistic.
- Reviewers: `pr-reviewer-{correctness,architecture,robustness}`, the set selection picks for these diffs. Each ran once per side, `claude -p`, sonnet, read-only checkout, prompt = contract + agent brief + `git diff BASE...HEAD` + PR body.
- Before = contract and agent files at the parent commit. After = the retrieval contract and the trimmed agent files in this change.
- A catch is a finding on the same path, at the same line or within 15 lines, describing the same defect as the Copilot comment.

## Which Copilot findings were caught

| PR | First-batch findings | Before | After |
| --- | ---: | ---: | ---: |
| #148 | 6 | 1 (`json.loads` non-list) | 1 (same) |
| #154 | 6 | 0 | 1 (claim truncation vs hash) |
| #210 | 5 | 1 (stale manifest, missing `open-pr-providers/shortcut.sh`) | 2 (statusline record from a subdirectory; `--issue sc-…` passed unnormalized) |
| #216 | 7 | 1 (remote delete not pinned to the PR head) | 1 (`sync_gate` documented read-only but fetches) |
| **Total** | **24** | **3** | **5** |

New-only: #154 claim truncation, #210 subdirectory record, #210 `sc-` normalization, #216 `sync_gate` fetch. Old-only: #210 stale manifest.

## Cost per reviewer, 4 PRs each

| Reviewer | Side | Mean wall time | Total tokens | Cost | Findings |
| --- | --- | ---: | ---: | ---: | ---: |
| correctness | before | 26.9 s | 1,282,522 | $1.00 | 4 |
| correctness | after | 33.7 s | 1,588,382 | $1.12 | 7 |
| architecture | before | 15.2 s | 925,858 | $0.84 | 8 |
| architecture | after | 18.6 s | 868,980 | $0.85 | 11 |
| robustness | before | 18.0 s | 881,487 | $0.78 | 2 |
| robustness | after | 17.0 s | 743,781 | $0.72 | 5 |
| **Total** | before | 20.0 s | 3,089,867 | $2.62 | 14 |
| **Total** | after | 23.1 s | 3,201,143 | $2.69 | 23 |

Tokens include cache reads; cost is the CLI's list-price estimate. Every run stayed under the 20-call budget (3–12 turns).

## Reading

Recall moved from 3/24 to 5/24 on this sample: retrieval helped, not enough to close the gap. Cost rose 3%, wall time 15%, and findings rose 14 → 23, so precision is untested — more volume may mean more false positives.

The regression is the one the seam rule exists for: the after-architecture run on #210 did not run `tools/workflow-manifest.sh --check`, which fails at that head, while the per-agent bullet it replaced pointed at generated files and caught it. The contract states the rule; this sample shows a reviewer can still skip it.

The historical miss set is unavailable on this machine: `~/.local/state/workflow-telemetry/events.jsonl` holds 18 local findings and no 2026-11-17 gap report, so the replay uses the Copilot first batch rather than the "Copilot-only" subset. Both sides scored against the same target.
