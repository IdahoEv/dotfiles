---
description: Governor — find upcoming tickets that aren't implementation-ready and walk through completing them
argument-hint: [optional: milestone, feature, ticket refs, or "inline"/"session"]
---

# Groom

Find upcoming tickets that are not yet ready for development, then walk the user through
completing them one at a time. Scanning is read-only; tickets change only in the Walk,
after the user confirms each edit. Intended for a Governor session; follow `/governor`'s
conduct (reply style, stay in the primary worktree).

## Gather

Locate the project's governor file with `project-config.sh find governor.md`; if it
exits non-zero, say so and stop. Then, in parallel:

- Open tickets from the tracker named there, with body, estimate, dependencies,
  milestone, and labels.
- Work already in flight: `git worktree list`, open PRs, and other sessions via
  `ListAgents`. Ticket refs found there are **taken**, not candidates.
- The planning docs named under the governor file's key documents.

## Filter: upcoming

A ticket is upcoming if it falls in the first of these that yields a set:

1. The scope named in `$ARGUMENTS` (milestone, feature, ticket refs).
2. The open milestone with the nearest due date.
3. Features the planning docs mark as next or current.

If none yields a set, say what was checked and stop; don't guess. Drop taken tickets and
any sourced from a draft doc marked "for local review".

## Filter: under-specified

Flag each upcoming ticket with every reason that applies:

- No acceptance criteria.
- No estimate. GitHub has no estimate field; look for an Estimate section in the body.
- Vague scope, or ACs that need "and then also" (a split candidate).
- Unresolved open question or undecided design.
- A dependency mentioned but not named.

## Report

Table of flagged tickets: ref, title, the feature it serves, flags. If nothing is
flagged, report one line — "Nothing upcoming is under-specified." — and stop.

## Where it runs

- **1–2 flagged tickets:** walk them here, in this session.
- **3 or more:** open a sibling session so a long pass doesn't tie this one up. Follow
  `~/.claude/commands/discuss.md`: label `Groom <scope>`, `--about` carrying only the
  flagged ticket refs and "follow the Walk section of `~/.claude/commands/groom.md`".
  The sibling re-reads the tickets itself. Don't hold the walk here.
- A bare `inline` or `session` token in `$ARGUMENTS` overrides the choice. Don't ask.
  Strip it before reading the rest of `$ARGUMENTS` as the scope.

## Walk

One ticket at a time, prerequisites first. Decisions come from the user; surface what is
missing, propose options only where a sensible default exists, and don't invent scope.

1. Two or three sentences on the ticket and the feature it serves.
2. The specific decisions needed, one per flag.
3. Outcome: **update** (ACs, estimate, dependencies), **split**, **park** (with a stated
   reason, recorded as a ticket comment), or **skip**.
4. Show the exact edit, then confirm it with `AskUserQuestion`, putting the full text in
   the question. Apply only on a yes.
5. Apply through the tracker: `gh issue edit` / `create` / `comment` on GitHub, the
   Shortcut MCP tools on Shortcut. A split creates the new ticket and links it from the
   original; confirm each.
6. Move to the next ticket. At the end, list refs as updated, split, parked, skipped.

$ARGUMENTS
