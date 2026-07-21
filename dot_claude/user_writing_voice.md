---
name: Evan's writing voice and style
description: Voice, tone, diction, and structural patterns to match when writing prose on Evan's behalf — ADRs, RFCs, design docs, glossaries, or any document intended to sound like him
type: user
---

When writing documents on Evan's behalf, match the following patterns. These were derived by comparing his hand-written PERS design documents against generated text.

## First-person ownership — direct and unhesitant

Evan claims recommendations as his own and shows his reasoning process, not just the conclusion.

- ✅ "For now I am recommending a weekly cadence."
- ✅ "I've considered the possibility of a double cadence… but have rejected that for now as too complex."
- ✅ "My intent is that the most recent plan…"
- ❌ "The weekly cadence is selected." (committee passive voice)
- ❌ "This design avoids requiring a…" (impersonal third person)

Use "I" for personal recommendations and rejected options. Use "we" for shared team goals and decisions.

## Inline causal reasoning — not sub-headers

The "why" is attached directly to the "what" as a subordinate clause or the next sentence. Do not create bold **Why X?** sub-headers for explanations.

- ✅ "No document is ever mutated after creation. This is required for point-in-time correctness: the ability to reconstruct…"
- ✅ "Provenance is per-field (not per-document) because demographics often arrive from multiple source systems at different times."
- ❌ **Why not a single ID?** [followed by paragraph]

## Pivot words and connective tissue

- "However" is the primary pivot when switching to a counterargument
- "As a result" for conclusions from prior reasoning
- "For now" as a temporal hedge: "rejected that for now as too complex"
- "As such" to connect cause to consequence

## Parenthetical asides — frequent and casual

Used for caveats, examples, and alternatives without breaking flow.

- "(or whatever)"
- "(a.k.a. Jigsaw)"
- "(e.g. what rule was run, what ML model, if any, contributed, etc.)"
- "(which will probably be either weekly or daily)"

## Honest hedges

Express uncertainty directly rather than hiding it.

- "most likely", "probably", "I think", "in my mind"
- "For now I am recommending…" rather than stating it as decided fact

## Plain vocabulary — no academic register

- "get us off on the wrong foot" (idiomatic is fine)
- "too complex", "too heavyweight" are valid, complete reasons
- "the deciding factor, for me" not "the decisive factor"
- "affects" not "determines"; "frozen" not "immutable"; "need for" not "necessity of"

## Short blunt conclusions after longer reasoning

Evan uses short declarative sentences or brief ADR-style conclusions after building up the reasoning:

- "Decision: six documents"
- "Decision: Option A"
- "Decision: Provenance per field"
- "This is not a close call."

## Structure

- Numbered lists with sub-bullets (Purpose / Trigger / Output) for process descriptions
- Tables for structured comparisons of options
- Parenthetical references to other docs: "(see ADR-006)" or "(when available)"
- Inline code backticks for field names, system names, code references
- No padding sentences — every sentence should carry information

## What to avoid

- Academic passive voice: "is accepted as a reasonable tradeoff" → "I think this is an acceptable tradeoff"
- Formal committee language: "The X is selected." → "I'm recommending X."
- Over-structured explanations with bold sub-headers for every "why"
- Elaborate multi-clause openers — Evan's paragraphs start simply and build
- Unnecessary hedging qualifiers that add words without adding meaning
