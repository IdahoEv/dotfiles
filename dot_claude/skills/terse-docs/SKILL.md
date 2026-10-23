---
name: terse-docs
description: Write or cut documentation — Notion RFCs/ADRs, design docs, READMEs, PRDs, planning docs, PR bodies, code comments, docstrings. Use when asked to write, draft, revise, shorten, or tighten a document, or when a doc has grown past the length a busy reader will finish. Enforces conclusion-first, high-density prose and deletes the show-your-work reflex.
---

# Terse Docs

A doc nobody finishes documents nothing. Optimize for **the reader who will
spend 90 seconds on this**, not for proof the author was thorough.

Applies to documents, code comments and docstrings. Not to CLAUDE.md or chat.

## The budget

State it before writing. Default ceilings:

| Doc | Ceiling | Must survive a |
| --- | --- | --- |
| ADR / decision | 500 words | 1-sentence summary |
| RFC / design | 1,500 words | 3-bullet summary |
| Reference / inventory | 500 prose words, tables unlimited | — |
| README | 1 screen to first command | — |
| PRD | 1,000 words | table of requirements |
| PR body | 300 words | title alone |

Over budget is a **rewrite signal, not a formatting problem**. Hitting 3× the
ceiling means the doc is carrying material that belongs in a linked appendix, a
ticket, or nowhere.

**Measure prose, not total.** A schema inventory is mostly tables and that is
correct — tables are the deliverable, and their length has a floor set by the
subject. Count the words *outside* tables and code blocks; that is the number
that predicts whether a reader finishes.

## Know which kind of doc this is

Two kinds, two failure modes. Diagnose before cutting.

**Decision doc** (ADR, RFC, proposal) — argues for a conclusion. Fails by
narrating options analysis as prose and re-stating the recommendation ten
headings in. Fix: tables for options, conclusion once.

**Reference doc** (inventory, schema map, API surface) — tells the reader the
shape of something. Fails by **justifying**: "why this matters," "why I included
this," "why this doc doesn't duplicate its sibling." Fix below.

A reference doc that argues is the most common bloat case, because each
justifying clause looks locally reasonable.

## Reference docs: state, don't justify

The reader wants the shape of the data. They did not ask why you chose to
document it.

- **No "why this document exists" section.** One line of provenance (repo,
  branch, commit, date) earns its place; the rest is a link to the ticket.
- **No defending scope.** "This deliberately does not repeat X" → link X.
- **Facts carry themselves.** `member_period_index` — "0-indexed count of prior
  periods; drives taper" is the fact. "A Jigsaw-only field with no Legacy
  analogue" is an argument for a different doc.
- **Analysis is a different document.** "Which fields are useful for ML,"
  "questions for product," "recommended exclusions" are design input for the
  downstream decision. Put them in that doc or the ticket and link.
- **No completeness theater** — "checked explicitly," "every claim traced."
  State findings; the provenance line already covers method.

Confirmed *absences* are facts and stay — "no points system, no wallet, no
redemption catalog" stops the next reader re-investigating.

## Structure

1. **Decision/answer first**, in ≤3 sentences, before any context. Notion: a
   callout block. A reader who stops here must still have the answer.
2. **Why, compressed** — the 2–3 load-bearing reasons. Not every reason.
3. **Consequences** — what changes, who is affected, what breaks.
4. **Everything else**, if it earns its place.

Never make the reader reach heading 10 for the recommendation. If the
conclusion appears twice, cut the second one.

### The opening block is the deliverable

Write it **last**, from the finished doc, and make it the densest thing on the
page. It carries the decision or headline finding plus the load-bearing numbers
— counts, amounts, "N of M exist, 2 are used." A reader who stops here is the
majority case; they must leave with the answer, not a description of the
territory.

Specifically not: a statement of what the document covers, who asked for it, or
how it was produced. "This document inventories X" tells the reader nothing they
didn't get from the title.

Then delete the section that used to serve this purpose. An opening block plus a
surviving "Why this document exists" / "Overview" / "Background" is the same
content twice.

## The ladder

Before adding a section, stop at the first rung that works:

1. **Link it** — the fact lives somewhere already (ticket, schema, code, prior ADR).
2. **Table it** — options, trade-offs, requirements, and comparisons are tables.
   Prose comparing three options is the single biggest source of bloat.
3. **One sentence** — most "sections" are a sentence.
4. **Write the section** — only when a reader genuinely needs the walkthrough.

## Cut on sight

- **Options analysis as narrative.** Rejected options get one table row each:
  option | why not. Not a subsection apiece.
- **Restating the title**, the ticket, or the previous paragraph.
- **Transitional throat-clearing** — "It's worth noting," "As discussed above,"
  "In order to," "It is important to understand that."
- **Background the audience has.** Teammates don't need the project explained.
- **Hedge stacks** — "may potentially," "could possibly." Say it or cut it.
- **Summaries of a doc under 1,000 words.** The doc is the summary.
- **Process narration** — how the analysis was conducted. Nobody is grading it.
- **Deferred/future-work sections** that are really a ticket. File the ticket, link it.
- **Trailing justification clauses.** A fact followed by a comma and a reason the
  fact deserves to be there. Keep the fact, cut the clause.

## Keep, always

Terseness is about volume, never about completeness. Never cut:

- the decision and its real cost
- a constraint that would change a reader's action
- a known failure mode or a rejected option someone will re-propose
- numbers, dates, identifiers, exact names
- the thing that was actually asked for

**Compress by deleting words, not facts.** A doc that is short because it
dropped a constraint is worse than a long one.

## Revising an existing doc

1. Report prose words (excluding tables and code), total words, heading count.
2. Name the top 3 bloat sources with word counts.
3. Propose the cut *before* making it — the author may know why a section
   exists. Approval, then edit.

Never silently delete a section someone wrote.

Start with the opening block and the first two sections. That is where the
repair almost always is: a weak opener plus a meta section, several hundred
words, no facts lost in removing them.

## Code comments and docstrings

Budgets are per comment, not per doc. Default is no comment.

- **Write one only for what the code can't show:** a why, constraint, trap, unit,
  or exact external name.
- **Don't restate the code** or what a good name already says.
- **No narration** of steps, no section banners.
- **No justification clauses** — "this is important because…". Keep the fact.
- **No history or ticket/PR refs** — see Code comments in CLAUDE.md.
- **Ceiling 1–3 lines.** Longer means refactor, or the content belongs in a doc.
- **Docstrings:** one-line summary. Params and returns only where names and types
  leave ambiguity. Examples only when usage is non-obvious.

"Keep, always" applies: never cut a constraint or known failure mode.

## Notion specifics

- Lead with a **callout** carrying the decision.
- **Toggles** for anything an expert reader skips (full schemas, derivations,
  raw benchmark data) — present but collapsed, not in the reading path.
- Tables over bulleted comparisons; Notion renders them well and they force
  parallel structure.
- Properties (Status, ID, owner) are metadata — never restate them in the body.
- Linked docs replace recapped docs. Cite `PERS-ADR-010`, don't re-explain it.

## Report

Word count against budget, and what you cut. One line.
