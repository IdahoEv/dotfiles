---
name: tighten
description: Audit and cut verbose comments, docstrings, and markdown docs across an existing repo. Use when asked to tighten comment bloat, trim documentation, sweep narration/history/ticket references out of comments, audit a repo's docs for verbosity, or when invoked as /tighten.
---

# Tighten

Sweep a repo's comments, docstrings, and markdown prose for bloat, propose the
cuts as a batch, and apply only what is approved. Edits land in a worktree, one
commit per batch, with build and tests run before and after.

The rubric is `~/.claude/skills/terse-docs/SKILL.md`: **Revising an existing
doc**, **Cut on sight**, **Keep, always**, **Code comments and docstrings**.
Read it before proposing anything; do not restate it here.

## Contract

- Report first. No edit before the approval gate.
- Never touch code — only comment, docstring, and prose text. The validator
  enforces this by requiring every `old` text to sit inside a comment block.
- Never delete without approval: every deletion appears in the batch preview.
- Never push, open a PR, or remove the worktree.
- The global "don't sweep unrelated files" rule covers incidental edits. This
  invocation is the explicit sweep it excepts.

## Arguments

`/tighten [paths…]` — default the repo root.

| Flag | Effect |
| --- | --- |
| `--comments-only` / `--docs-only` | One corpus |
| `--report-only` | Scan and report, never propose or edit; no worktree |
| `--no-fanout` | Inline proposals even on large repos |
| `--max-batches N` | Default 3, cap 4 |
| `--base REF` | Worktree base; defaults to `HEAD` of the repo at creation. Always pass the scanned commit. |
| `--include-untracked` | Report untracked files (they cannot be edited in a worktree) |

Scripts live in this skill's directory (`~/.claude/skills/tighten/`):
`tighten-scan.py` (read-only), `tighten-proposals.py` (validate/apply),
`tighten-worktree.sh` (create/reuse). `test_tighten.py` is the suite:
`python3 ~/.claude/skills/tighten/test_tighten.py`.

## 1. Preflight

```bash
git -C <repo> rev-parse --show-toplevel
git -C <repo> rev-parse HEAD            # save as scan_sha
git -C <repo> status --porcelain
python3 ~/.claude/skills/tighten/tighten-scan.py --root <repo> --commands
```

- Not a git repo → `--report-only`.
- Dirty tree → report only, unless the user accepts that uncommitted work is not
  carried into the worktree. Never stash.
- No `build=`/`test=` → `AskUserQuestion`: supply a command, or accept
  `unverified`. Never claim a pass that did not run.

## 2. Worktree

Skip this section under `--report-only`; scan the repo in place instead.

```bash
~/.claude/skills/tighten/tighten-worktree.sh <repo> tighten/<YYYY-MM-DD-HHMM> --base <scan_sha>
```

Parse `worktree=`, `branch=`, `mode=`, `reused=`, `head=`. Refuse to continue
when `head` differs from `scan_sha` — the proposals were made against that tree.
Never put the worktree inside the repo.

## 3. Scan and report

Scan the worktree (same commit as `scan_sha`), not the original checkout:

```bash
python3 ~/.claude/skills/tighten/tighten-scan.py --root <worktree> [paths] --json --top 5 \
  [--comments-only|--docs-only]
```

Write the JSON to `<scan-root>/.scratch/tighten-<YYYY-MM-DD-HHMM>/scan.json`.
Chat gets the totals line, the per-directory table, and the top 5 comment and
doc offenders. Stop here when `--report-only`.

Bloat is a ranking signal, not a verdict: a long block that carries a
constraint stays. Files with `parse_error: true` are reported, never edited.

## 4. Baseline

Run the detected build and test in the worktree **before any edit**. Red → stop
unless the user explicitly accepts a red baseline. No command and no user
command → record `unverified` and continue only if the user accepts it.

## 5. Propose

Take files with `signal: true`, highest word counts first. Fewer than 30 files →
read them yourself. Otherwise fan out to `general-purpose` subagents, one per
directory group, at most 6 concurrent and 15 files each; run further rounds until
every signal file has been offered, and carry the count into the report.
`--no-fanout` disables this. Lean prompts: file list and the rubric path, no
pre-reading by the caller.

Contract for each proposer:

> Read-only: do not edit. Read `~/.claude/skills/terse-docs/SKILL.md` and apply
> "Revising an existing doc", "Cut on sight", "Keep, always", and "Code comments
> and docstrings" to the listed files. Return a JSON array of
> `{file, start_line, end_line, old, new, reason, kind}`. `old` is byte-exact,
> including markers and indentation, and must occur once; use `start_line` to
> disambiguate. `new` may be empty only for a deletion. Whole comment or
> docstring blocks only; never code. Everything under "Keep, always" survives.
> Never touch a directive (`type: ignore`, `noqa`, `eslint-disable`, `go:build`,
> `@ts-`, SPDX/license headers) or a doctest, and never propose more words than
> you remove. Skip anything you cannot improve. No prose outside the JSON.

Merge the arrays, dedup identical `(file, old)`, and save `proposals.json` in the
scan directory. Then:

```bash
python3 ~/.claude/skills/tighten/tighten-proposals.py check <proposals.json> \
  --root <worktree> --json --write-accepted <proposals-accepted.json>
```

Report every rejection with its reason; never apply one. The accepted file is
what the gate approves.

## 6. Approve — one gate

Group accepted proposals by directory into at most `--max-batches` batches
(merge the smallest groups when over). Call `AskUserQuestion` once, one question
per batch, at most four. Each question text carries: directory, file count,
hunk count, word delta, the three largest cuts (`file:line — reason`), and the
full commit message. Options:

- **Apply and commit** — `preview` holds that batch's exact hunks.
- **Skip**

No selection → stop with no edits. Rejected hunks are stated as not applied.

## 7. Apply, verify, commit

Per approved batch:

```bash
python3 ~/.claude/skills/tighten/tighten-proposals.py apply <proposals-accepted.json> \
  --root <worktree> --dir <batch-dir> --stage
( cd <worktree> && <build> && <test> )      # detected, or the user's command
git -C <worktree> commit -m "Tighten comments and doc prose in <dir>" \
  -m "Cut restatement, narration, and history; no behavior change."
```

- `apply` is all-or-nothing and refuses when any proposal in the batch is
  invalid. `--stage` stages exactly the files it changed, nothing else.
- Tests red → `git -C <worktree> reset --hard HEAD` (the worktree is disposable;
  `checkout -- .` restores from the index, which `--stage` already filled), stop,
  report the batch and the failing output. Never commit red.
- Word growth, code (in `old` or `new`), protected directives, structural doc
  edits, and missing matches are rejected by the validator; do not work around a
  rejection by hand-editing.
- Several directories in one batch → repeat `--dir`.

## 8. Final report

Per-batch word delta, total before/after, commits, tests run (or `unverified`),
worktree path and branch, rejected counts, and how many signal files were
offered (N of M) so a capped run never reads as a complete sweep. Say how to
review or discard the worktree. Never push.

## Guardrails

- `.claude/**`, chezmoi `dot_claude/**`, `SKILL.md`, `CLAUDE.md`, `AGENTS.md`,
  and `.cursorrules` are agent prompt files, governed by a different rubric. The
  scanner skips them unless a path is passed explicitly.
- `CHANGELOG`, `HISTORY`, `NEWS`, `LICENSE`, `COPYING` are history or legal
  text and are not targets.
- Vendored and generated files are skipped by path, name, and content markers.
