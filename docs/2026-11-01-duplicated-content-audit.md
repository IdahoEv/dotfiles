# Duplicated LLM-generated content across the ticket lifecycle

Audit of #109 against `main` at 31c081f. Only the PR body (ticket AC and what/why restated) and the plan (ticket restated) regenerate content that already exists. The kickoff is already mechanical and stays as is. I recommend five follow-ups (8 points total, one of them a usage check on the Shortcut-era commands); the PR body assembly is the one that saves real output. Recent PR bodies run 665–1,952 characters, so the saving is modest per ticket and mostly shows up as less review reading and less drift.

## Artifacts

| Artifact | Producer | Inputs | LLM regenerates existing content? | Size |
| --- | --- | --- | --- | --- |
| Ticket | Human, `/discuss`, or governor | Intent | No (origin) | 0.3–1 KB |
| Kickoff | `start-ticket.sh`, copy only; `/start` appends `## Context` | Ticket title and body verbatim, preamble, personal-assets block | No. `/start` adds parent, sibling and blocker state, which the ticket can't hold. The session label is the only LLM-written string | ticket + ~0.6 KB; Context ~0.3 KB |
| Plan | Implementer, in plan mode | Kickoff (already holds the ticket), code | Yes: restates what/why/AC. `literal_create_plan.md` goes further and requires description and AC "complete and unmodified" | 1–5 KB in chat; 5–20 KB with the file template |
| Commit message | Implementer (`/open-pr` step 2); manager and repair agent per round | Diff | Partly: re-describes the plan's phase summary | 0.2–0.5 KB each |
| Review report | `local-review-cycle-manager` | Reviewer findings | New content. Reprinted by `/local-review-cycle` step 3, then rewritten into the PR | 0.5–1.5 KB |
| PR body | Implementer (`/open-pr` step 2) | Diff, ticket, review report | Yes: ticket what/why/AC, commit subjects, review note. The `Closes #N` footer is already mechanical (`provider::pr_body_footer`) | 0.7–2 KB measured (#100–#108) |
| Sibling kickoff | Implementer (`/open-pr` step 4a) | Ticket ref, PR URL | Yes: the same heredoc boilerplate each fan-out | ~0.8 KB each |
| `/create_plan`, `/implement` outputs | Shortcut/PRD-era commands | PRD → plan → tracker comments | Yes: AC copied PRD → plan → progress comments → summary, 4–5 copies | Largest |

## Classification

| # | Duplication | Class |
| --- | --- | --- |
| D1 | Plan restates ticket what/why/AC | Redundant |
| D2 | PR body restates ticket what/why/AC | Redundant; AC copy is also drift-prone if the ticket is edited later |
| D3 | PR body re-summarizes commits that `git log` lists | Redundant |
| D4 | PR "Review cycle" note rewritten from the manager report, which is already specified as its source | Redundant |
| D5 | Review report printed by the manager, then again by `/local-review-cycle` | Redundant but necessary: the user must see it once at top level |
| D6 | `create_plan` template and `/implement` re-quote AC at several steps | Redundant and drift-prone (Shortcut flow; confirm it is still used) |
| D7 | Sibling kickoff boilerplate rewritten per fan-out | Redundant |
| D8 | `Closes` footer, commit trailer | Already mechanical; leave |
| D9 | Plan approach and deviations; PR "what needs your judgment" | Necessary: new synthesis |
| D10 | Kickoff = ticket verbatim + tracker-state Context | Necessary; already the right shape |
| D11 | Working-agreement preamble in every kickoff | Necessary: the session has no other channel |

## Recommendations

Each is a follow-up ticket.

| # | Change | Fixes | Size |
| --- | --- | --- | --- |
| R1 | Assemble the PR body mechanically: ticket AC fetched (not retyped) + `git log BASE..HEAD` + a 3–6 line LLM-written "Deviations / needs your judgment" + the review note verbatim. `open-pr.sh --body-file` stays; add an assemble helper | D2, D3, D4 | 3 |
| R2 | Plans reference the ticket instead of restating it: link, approach, files, test strategy, deviations only. Put the rule in the kickoff or global guidance, not the legacy template | D1 | 1 |
| R3 | Manager emits a ready-to-paste "Review cycle" block (counts, dismissed findings with reasons); `/open-pr` embeds it unedited | D4 | 1 |
| R4 | Move the sibling kickoff heredoc into `start-ticket.sh`; `/open-pr` passes ticket ref, PR URL and repo name | D7 | 1 |
| R5 | Check whether `/create_plan`, `/implement` and `/generate_prd` are still used; then retire them or cut them to references | D6 | 2 |
| — | Leave kickoff, preamble, footer, trailer | D8, D10, D11 | 0 |

R1 trade-off: AC is fetched when the PR opens, so a later ticket edit leaves the PR stale until refreshed. That is still better than a retyped copy, which can be wrong on day one.

## `docs/workflow-architecture.md`

No update needed for this audit, which changes no workflow behavior. Its only touchpoint is the sequence diagram's "report → PR body's Review cycle note" line, which matches D4. R1, R3 and R4 touch `/open-pr`, the manager report and `start-ticket.sh`, so each must re-check it, and R4 must also update the adapter map in `workflow/adapters/` (`cloud-workflow-adapter.test.sh` enforces this for `open-pr.md`).
