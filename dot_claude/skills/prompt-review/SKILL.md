---
name: prompt-review
description: Review Claude prompt files — CLAUDE.md, skills, commands, agents, hooks, settings — for staleness, bloat, scope leakage, and duplication. Use when asked to review/audit prompts or Claude config, when asked whether a CLAUDE.md has gone stale, when invoked via /prompt-audit, and when a branch diff under review touches prompt files. Not for product code.
---

# Prompt Review

Review prompt files as prompts. The standards are not the ones that apply to
code: a prompt has no failing input, so "name the caller that reaches the bug"
finds nothing here and the bar has to be different.

**Read-only.** Produce a catalog of findings. Do not edit, commit, or push
unless the caller explicitly asks for fixes.

## Scope

Default is every committed prompt file in the repo — staleness does not appear
in a diff, so a diff-scoped pass cannot find it. Files in scope:

- `CLAUDE.md` at any depth, `.claude/**` (skills, commands, agents, hooks,
  settings, `*.md`, `*.json`)
- chezmoi sources for the above: `dot_claude/**`, `*.tmpl` variants
- `AGENTS.md`, `.cursorrules`, and similar if present

`--diff [BASE]` narrows to `git diff BASE...HEAD` for the branch-review case.
Say which scope you ran.

## The four checks

### 1. Staleness — the one that matters most

A prompt goes stale with **zero edits to it**, because the world it describes
moved. Nothing triggers a re-read when that happens. Every factual claim is a
liability; check it rather than trusting it.

Highest-yield claims, in order:

- **Ticket/issue/PR state.** "In progress", "not yet merged", "blocked by",
  ordering tables. Verify against the tracker, not against the file. These are
  wrong by default — the tracker moves and the file does not.
- **Status words with no expiry:** "currently", "for now", "soon", "upcoming",
  "not built yet", "the only X so far", "in flight". Each needs a current fact
  or an absolute date behind it.
- **Counts, versions, pins, paths, commands.** "94 tests", "pins 0.3.0",
  `src/foo.ts`. Run or grep; don't eyeball.
- **Relative dates.** "last month", "recently" — convert to absolute or cut.

Report the claim, the evidence that contradicts it, and the correction.

### 2. Scope leakage

Each rule belongs in the narrowest scope that holds it, stated **once**.

- **Global** (`~/.claude`, chezmoi): true in every repo — tone, git hygiene,
  review gates, who the user is, tools on `PATH` everywhere.
- **Project** (repo `CLAUDE.md`, `.claude/`): this repo's commands, paths,
  services, schemas, test tiers, CI, conventions only it follows.
- **Work vs. personal:** a Shortcut/employer-specific rule in a shared or
  personal-machine section leaks work conventions where they don't apply. In
  `.tmpl` files, check which conditional branch the text sits in.

Flag a global rule that names one repo, a project rule that would hold
everywhere (promote on the *second* sighting, not the first), and anything in
the wrong template branch.

### 3. Duplication

The same rule in two files drifts into contradiction — that is how the two
copies stop agreeing and nobody notices. Report any rule stated in more than
one place, say which location is narrowest, and recommend the others become a
pointer. Direct contradictions are findings regardless of scope.

### 4. Bloat

Two distinct cuts, and the second needs care:

**Cut what the model already does by default.** Generic competence, obvious
process, encouragement, restatements of the request. Carry what is
*surprising* about this setup.

**For prose that explains reasoning, apply the load-bearing test:** delete it
mentally and name the wrong move that returns. If you can name one, the prose
is load-bearing — keep it, even if it is long. If you cannot, cut it.

This test exists because rationale that looks like decoration is often the
record of a specific past failure, and a reviewer who doesn't know the incident
will cut it every time. When in doubt, flag it as a question rather than a
deletion.

Also flag: a rule firing every session that sits in a skill (belongs in
`CLAUDE.md`), and a rule firing once per task that sits in `CLAUDE.md` (belongs
in a skill, where it costs nothing until invoked). And a `description` that
doesn't name the firing situations in the user's own words — it is matched
before the body is ever read.

## Output

Group by file, severity first within each. One block per finding:

    file:line | check | the claim or text | evidence | recommended change

Lead the report with a one-line count per check, then the blocks. Close with
anything you could not verify and why.

Say "no findings" rather than padding. A clean file is a real result; do not
manufacture nits to look thorough.
