# Ticket naming across surfaces

Spike for #156. Today a ticket is spelled four ways (`sc-7`, `Sc7`, `Is7`, `#7`) by seven independent code paths, and nothing guarantees the branch, worktree, agent row and PR title read alike. Proposal: derive every surface from one **name** `(key, description)`, rendered by per-surface templates that the user can override per user, machine or project.

## Current state

"Det" = script-derived; "Model" = written by the model from prose instructions.

| Surface | Format today | Defined in | Det/Model |
| --- | --- | --- | --- |
| Branch, GitHub | `<N>-<first 6 title words>` | `start-ticket-providers/github.sh` | Det |
| Branch, Shortcut | `sc-<id>/<last 5 title words>` (user segment stripped) | `worktree-manager.sh` (419-500) | Det |
| Branch, cloud sessions | `Is<N>-<slug>` | project prose | Model |
| Worktree dir | branch with `/` → `-` | `worktree-manager.sh` (672) | Det |
| Agent row | `[PHASE][PR] Is<N>\|Sc<id> <3-4 words>`; chain `Is7+8` | `start-ticket.sh` `make_label`, `agent-phase.sh` | Det prefix, Model words |
| Agent row, session-kickoff path | same, hand-composed | `tools/session-kickoff.md` | Model |
| PR title | `Is<N>: <bare title>`; none for Shortcut | `open-pr-providers/*.sh` `pr_title`, repair in `open-pr.sh` (310-340) | Det prefix, Model title |
| Commit subject | unspecified; `Closes` footer only | `commands/open-pr.md` | Model |
| Kickoff first line | `Working on GitHub issue #N …` / `Shortcut story N …` | `start-ticket.sh` (~605) | Det |
| Statusline | `project \| branch(40) \| [PHASE] \| PR`; no id or label | `executable_statusline.sh` (66-77) | Det |
| Telemetry / finalize ref | `owner/repo#N`, `sc-<id>`, `#42` | `lib/telemetry.sh`, `commands/finalize.md` | Det |
| Id parsers | `^[1-9][0-9]*-`, `.*sc-([0-9]+)` | `lib/repo-facts.sh`, `lib/repo_facts.py` | Det |

## Inconsistencies

1. **Four spellings of one id**: `sc-<id>` (branch, telemetry), `Sc<id>` (row), `Is<N>` (row, PR title), `#N` (footer, finalize).
2. **Colon**: PR titles use `Is<N>:`, rows use `Is<N> `. The repair regex accepts every variant, which hides the drift.
3. **Cloud `Is<N>-slug` branches are invisible to the parsers** (`^[1-9][0-9]*-`): a local `open-pr` opens a ticketless PR with no `Closes`, and finalize loses the id.
4. **Shortcut has no PR-title story**: the GitHub provider returns no issue for `sc-<id>/…`, so the PR is ticketless. `--issue` is integer-only and would emit the wrong `Is<N>:` dialect. Comments and `open-pr.md` imply an `sc-<N>:` form nothing emits.
5. **Slug rules differ by provider**: GitHub keeps the first 6 raw words, Shortcut the last 5 distilled. `--print-title` shows the Shortcut-style `proposed_slug` for both, and `start.md` says `GT_LABEL_SLUG_OVERRIDE` renames the branch, which GitHub ignores.
6. **Two label composers**: `make_label` and the hand-composed string in `session-kickoff.md`. The latter skips chain tags and truncation.
7. **Model label may never reach the row** (unverified): `start.md` says the label is applied during `--no-tab`, but the session opens in a later `--tab-only` call that recomputes from the branch.
8. **Model wording diverges from the slug** on the same ticket (by design today), so only the number ties the surfaces together.
9. **Chain tag only on the row** (`Is7+8`); branch and title carry the head ticket.
10. **`[TALK]`** is outside `PHASES` and the statusline regex.
11. **Project prose duplicates provider logic** (PR-title prefix, `Closes` footer), once per cloud and local path.
12. **Commit subjects and the statusline** carry no ticket key.

## Proposal

### Model

One **name** per unit of work: `key` + `description`.

- **key**: deterministic, from the ticket(s). Identity lives here; parsers read only the key.
- **description**: 2-4 words, mostly nouns, no filler verbs (*implement*, *build*, *add*). Model-written once at start, then **persisted** (`<git-dir>/name`). Every surface reads the persisted value, so reruns, `find_ticket_branch`, and the row can never drift.

### Default (ticket-driven)

key = `<provider><numbers>`: provider `Is` (GitHub issue) or `sc-` (Shortcut); numbers = all chain tickets, hyphen-joined.

Every surface derives from one **base** template, `{key} {desc}` (key `{provider}{chain}`: `Is312-313-315`, `sc-7435`). A surface differs from the base only by a **form** (case and word separator) and a **wrapper** (prefix, suffix, phase tag). Both are overridable per surface.

| Surface | Form | Wrapper | Example |
| --- | --- | --- | --- |
| Branch | kebab | none | `Is312-313-315-invoice-totals` |
| Worktree dir | kebab, `/` → `-` | none | same |
| Agent row | words | `{phase} ` prefix | `[WIP] Is312-313-315 invoice totals` |
| PR title | words | `:` after the key | `Is312-313-315: invoice totals` |
| Commit subject | words | optional `{key}: ` prefix | `Is312: fix rounding` |
| Statusline | n/a | `{key}` replaces the branch column | `Is312-313-315` |

Rules that make the surfaces match:

- Only the form and wrapper vary per surface, so the same words appear in the same order everywhere. A user who wants spaces everywhere sets the branch form to `words`; one who wants kebab everywhere sets it for the row and PR title.
- The branch drops the `<user>/` segment and the `sc-<id>/slug` slash form, so branch and worktree dir are identical.
- The long ticket title moves to the PR body; the PR title is the name, not a second summary.
- Parsers match the key prefix (`^(Is|sc-)[0-9]+(-[0-9]+)*`) and keep the legacy forms until old branches drain. A description that starts with digits is ambiguous, so `<git-dir>/chain` stays authoritative for the ticket list.

### Configuration

Every template, plus the key's parts, is a setting. Resolution order, most specific wins: project `.start-ticket.conf` > per-machine config > user config > built-in default. This extends the existing `setting` helper in `start-ticket.sh`, which already resolves env, machine, then default.

Overrides, narrowest wins: a surface setting replaces the base for that surface only.

| Setting | Effect | Use |
| --- | --- | --- |
| `base` | Replaces `{key} {desc}` everywhere | Change the shape for all surfaces |
| `<surface>.form` | `kebab`, `words`, `Title`, `snake` | Kebab branch and worktree (no spaces in paths), readable row and PR title |
| `<surface>.template` | Full template for one surface | `branch.template = {type}/{base}` and `pr.template = {type}: {base}`, with the row left at the base so it omits the type |

`{base}` in a surface template means the base rendered in that surface's form, so overriding one surface never forks the wording. Defaults leave every override empty.

Conceptual token library (the DSL; a `{token:option}` substitution is the cheapest implementation and is enough):

| Token | Options |
| --- | --- |
| `{provider}` | `full` (`Issue`, `shortcut`), `brief` (`Is`, `sc-`) |
| `{chain}` | `all`, `first`, `last`; separator configurable |
| `{desc}` | source: `model`, `title` (verbatim), `ask` (prompt the user); form: `kebab`, `words`, `Title` |
| `{type}` | `bug`, `feature`, `chore`, … from the ticket's label or type; `none` when unlabelled; empty by default. Example branch template: `{type}/{base}`; the worktree dir then needs `/` → `-`, as today |
| `{base}`, `{phase}`, `{key}` | derived |
| literals | any separators or symbols |

Ship the defaults above and the single resolver; the user-facing DSL documentation can come later, but the resolver takes a template string from day one so nothing needs reworking.

### Non-ticket work

Same shape, a different key.

| Kind | Key | Description | Surfaces |
| --- | --- | --- | --- |
| Talk-driven | `tk<MMDD>[-n]`, e.g. `tk1109` | Model, set when the discussion turns into implementation | Same templates. A talk that files a ticket is relabelled and becomes ticket-driven (already the `/discuss` flow). |
| Iteration-driven | `it<MMDD>[-n]`, e.g. `it1109-2` | Goals arrive live, so there is none at start | Branch and worktree take the key only. The row and PR title add the model summary at PR time (`it1109-2: staging import fixes`). |

The key is the join between surfaces; for iteration work the description is best-effort because renaming a live branch and worktree is not worth the churn. If you would rather have the description in the branch, `{desc:ask}` at start is the configuration that gives it.

### Provider-specific and deliberately not unified

| Item | Treatment |
| --- | --- |
| Provider token (`Is`, `sc-`) and number format | Provider-specific, configurable |
| Provider CLI quirks (branch discovery, state writes) | Provider-specific |
| `Closes`/footer syntax | Provider-specific |
| Cloud sessions without the scripts | Follow the same templates from prose, until a shared resolver is callable there |
| Commit subjects | Key prefix optional, off by default; the `Closes` footer stays the authoritative link |
| Chain order in titles | Full chain in the key; use `{chain:first}` to shorten |

## Follow-up tickets

Each is one reviewable unit. #155 (PR titles on the GitHub provider) is already merged and is the first.

| # | Ticket | Depends on |
| --- | --- | --- |
| 1 | Name resolver: `(key, desc)` → surface strings from templates, with built-in defaults; persist `<git-dir>/name` | - |
| 2 | Settings layering (user, machine, project) for templates and key parts | 1 |
| 3 | Branch and worktree creation use the resolver; one slug rule for both providers; drop `<user>/` and slash forms; `{type}` token from provider labels | 1 |
| 4 | Parsers accept the new key and legacy forms (`Is<N>-`, `sc-<id>/`); fixes cloud-branch ticketless PRs | 1 |
| 5 | Agent row from the resolver; delete the hand-composed path in `session-kickoff.md`; fix the `--tab-only` label loss | 1 |
| 6 | PR title from the resolver; Shortcut provider; drop integer-only `--issue` | 1, 4 |
| 7 | Statusline shows the key | 1 |
| 8 | Ticketless keys (`tk`, `it`) and `[TALK]` as a recognised tag; hook for the planned `/iterate` command | 1, 5, 6 |
| 9 | Move project prose rules into providers/templates; update `workflow-architecture.md` | 3, 6 |
