# Ticket naming across surfaces

Spike for #156. Today a ticket is spelled four ways (`sc-7`, `Sc7`, `Is7`, `#7`) by seven independent code paths, and nothing guarantees the branch, worktree, agent row and PR title read alike. Proposal: a **workstream** record in the worktree holds one name `(key, description)`; every surface is rendered from it by templates the user can override per user, machine or project.

## Current state

"Det" = script-derived; "Model" = written by the model from prose instructions.

| Surface | Format today | Defined in | Det/Model |
| --- | --- | --- | --- |
| Branch, GitHub | `<N>-<first 6 title words>` | `start-ticket-providers/github.sh` | Det |
| Branch, Shortcut | `sc-<id>/<last 5 title words>` (user segment stripped) | `worktree-manager.sh` (419-500) | Det |
| Branch, cloud sessions | `Is<N>-<slug>` | project prose | Model |
| Worktree dir | branch with `/` → `-` | `worktree-manager.sh` (677) | Det |
| Agent row | `[PHASE][PR] Is<N>\|Sc<id> <3-4 words>`; chain `Is7+8` | `start-ticket.sh` `make_label`, `agent-phase.sh` | Det prefix, Model words |
| Agent row, session-kickoff path | same, hand-composed | `tools/session-kickoff.md` | Model |
| PR title | `Is<N>: <bare title>`; none for Shortcut | `open-pr-providers/*.sh` `pr_title`, repair in `open-pr.sh` (310-340) | Det prefix, Model title |
| Commit subject | unspecified; `Closes` footer only | `commands/open-pr.md` | Model |
| Kickoff first line | `Working on GitHub issue #N …` / `Shortcut story N …` | `start-ticket.sh` (644) | Det |
| Statusline | Ticket role: `project \| branch(40) \| [PHASE] \| PR`, no id or label; plain role: session title | `executable_statusline.sh` (66-77) | Det |
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
10. **`[TALK]`** is outside `PHASES` and the statusline regex, so it renders as a plain-title session.
11. **Project prose duplicates provider logic** (PR-title prefix, `Closes` footer), once per cloud and local path.
12. **Commit subjects and the statusline** carry no ticket key.

## Proposal

### The workstream

A **workstream** is the unit everything else hangs off: one agent session plus one worktree, with an optional ticket, branch and PR. It outlives any single Claude session, because sessions are restarted and resumed inside it. Its state is one file, `.workstream.json`, in the worktree (excluded through `.git/info/exclude`, not synced to other trees). It is the single source of truth for naming, tags and the statusline.

| Field | Meaning |
| --- | --- |
| `kind` | `ticket`, `talk` or `iteration`. `[TALK]` and `[ITERATE]` are kinds, not tags. |
| `tickets`, `ticket_provider` | `[{id, url}]` and the tracker; empty for talk and iteration until a ticket is filed |
| `key`, `key_aliases`, `desc`, `type` | The name inputs. Old keys are kept as aliases after a rename. |
| `template_source` | Which level supplied the templates: default, user, machine or project |
| `tags` | Tag states (`PLAN`, `WIP`, `REVIEW`, …). A set: several can hold at once. |
| `pr`, `reviews` | PR number and URL; local and remote review counts |
| `claude_sessions` | Session ids that have attached, so restart, resume and fork need no special case |

Derived names (branch, worktree, row, PR title) are computed from the inputs, not stored. Implementation is Python, stdlib only, minimum 3.11; the shell scripts become thin callers. The review-gating rules (reviewers, round limits, timeouts) could join the record later and are out of scope.

### Name

`name = (key, desc)`.

- **key**: deterministic. Ticket work: `{provider}{chain}` (`Is312+313+315`, `sc-7435`). Talk and iteration: `tk<MMDD>[-n]` and `it<MMDD>[-n]`.
- **desc**: 2-4 words, mostly nouns, no filler verbs (*implement*, *build*, *add*). Model-written from the ticket title, or from the starting prompt for talk and iteration. Stored in the record.

Every surface derives from one base template, `{key} {desc}`, and differs only by a **form** (case and separator) and a **wrapper** (prefix, suffix, tag):

| Surface | Form | Wrapper | Example |
| --- | --- | --- | --- |
| Branch | kebab | none | `Is312+313+315-invoice-totals` |
| Worktree dir | kebab, `/` → `-` | none | same |
| Agent row | words | tags prefix | `[WIP] Is312+313+315 invoice totals` |
| PR title | words | `:` after the key | `Is312+313+315: invoice totals` |
| Commit subject | words | optional `{key}: ` prefix | `Is312: fix rounding` |
| Statusline | n/a | line 1 is generated from the record | see below |

Rules that make the surfaces match:

- Only the form and wrapper vary per surface, so the same words appear in the same order everywhere.
- The branch drops the `<user>/` segment and the `sc-<id>/slug` slash form, so branch and worktree dir are identical.
- The long ticket title moves to the PR body; the PR title is the name.
- Parsers read the record first, then match the key prefix (`^(Is|sc-)[0-9]+(\+[0-9]+)*`; `+` keeps a numeric description such as `Is7-404-pages` from reading as a chain) and the legacy forms until old branches drain.

### Statusline

Line 1 comes from the record alone:

`project | workstream name | tags | PR # | local/remote review counts`

Anything shown there is a field the record owns, so the writers (`open-pr.sh`, the review flows, `agent-phase.sh`) update the record and nothing else decides what the user sees. Claude's own `state.json` becomes a view that `agent-phase.sh` mirrors from the record.

### Configuration

Layering, most specific wins: project `.start-ticket.conf` > per-machine config > user config > built-in default.

| Setting | Effect | Use |
| --- | --- | --- |
| `base` | Replaces `{key} {desc}` everywhere | Change the shape for all surfaces |
| `<surface>.form` | `kebab`, `words`, `Title`, `snake` | Kebab branch and worktree, readable row and PR title |
| `<surface>.template` | Full template for one surface | `branch.template = {type}/{base}` and `pr.template = {type}: {base}`, row left at the base so it omits the type |

`{base}` in a surface template means the base rendered in that surface's form, so overriding one surface never forks the wording. Defaults leave every override empty.

| Token | Options |
| --- | --- |
| `{provider}` | `full` (`Issue`, `shortcut`), `brief` (`Is`, `sc-`) |
| `{chain}` | `all`, `first`, `last`; separator configurable |
| `{desc}` | source: `model`, `title` (verbatim), `ask` (prompt the user); form: `kebab`, `words`, `Title` |
| `{type}` | `bug`, `feature`, `chore`, … from the ticket's label or type; empty by default |
| `{base}`, `{tags}`, `{key}` | derived |
| literals | any separators or symbols |

The resolver takes a template string from day one; user-facing DSL documentation can come later.

### Lifecycle

- **Ticket**: `/start` creates the worktree and record from the ticket(s).
- **Talk and iteration**: `/discuss <topic>` (today a main-checkout session with no worktree) and a new `/iterate <topic>` create the worktree, branch and record immediately, named from the topic (`it1109-ui-hud-alignment`). A worktree guards `main` from accidental changes and is cheap to create. Unused ones are swept later: clean, no commits, old, no live session.
- **Mid-stream ticket**: filing a ticket attaches it to the workstream and renames it.
- **Rename**: `rename-workstream.sh "<slug>"` runs `git branch -m` and `git worktree move`, updates the record and row, and asks the user to `/cd`. Once a PR exists it fails closed; `--force` renames anyway and leaves the PR name behind, `--force-with-pr` opens a new PR and loses the old one's comments.
- **Resume**: for an orphaned worktree, a script prints the record so the agent starts from it instead of from a hand-written prompt.

### Provider-specific and deliberately not unified

| Item | Treatment |
| --- | --- |
| Provider token (`Is`, `sc-`) and number format | Provider-specific, configurable |
| Provider CLI quirks (branch discovery, state writes) | Provider-specific |
| `Closes`/footer syntax | Provider-specific |
| Cloud sessions without the scripts | Follow the same templates from prose, until the resolver is callable there |
| Commit subjects | Key prefix optional, off by default; the `Closes` footer stays the authoritative link |
| Chain order in titles | Full chain in the key; `{chain:first}` shortens |
| Tag states | Not redefined here; see the last follow-up |

## Follow-up tickets

Each is one reviewable unit. #155 (PR titles on the GitHub provider) is already merged and is the first.

| Ticket | Scope | Depends on |
| --- | --- | --- |
| #160 | Workstream record, resolver and settings layering | - |
| #161 | Branch, worktree and parsers use the resolver (fixes cloud-branch ticketless PRs) | #160 |
| #162 | Agent row and statusline read the record; fix the `--tab-only` label loss | #160 |
| #163 | PR title and providers: Shortcut provider, prose rules into providers, update `workflow-architecture.md` | #160, #161 |
| #164 | Talk and iteration lifecycle, `rename-workstream.sh`, resume script, sweep rule | #160, #162, #163 |
| #168 | Review tag states and transitions (local and GitHub review, going back a stage) | #160 |
