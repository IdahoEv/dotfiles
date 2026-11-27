# Session and workstream record schemas (v0)

**The session and workstream records are the only stored session and workstream state.** Tags, the `!` marker, statuslines, session names and herdr panels are generated from them, the same way for every agent. A session links to its workstream, never the reverse. Review progress is stored once, with one entry per reviewer.

This is the target design; none of it is built. [Record lifecycles](workstream-lifecycle.md) covers when records are created and destroyed.

## Common rules

- Records are JSON. Times are UTC strings such as `2026-11-27T20:13:15Z`.
- `schema_version` is the integer `0`. A tool that meets a higher number reports it and does not write.
- All writes go through workstream commands. "Writer" below names what calls them.
- Fields inside a list or object share its writer and reader.
- **Req:** yes, no, or the condition that makes the field required.
- Fields marked **provisional** may change with what herdr provides. The [herdr findings](https://github.com/IdahoEv/dotfiles/pull/277) are not merged yet.

| Record | Location |
| --- | --- |
| Session | `~/.local/state/workstream/sessions/<id>.json` (**tentative**) |
| Workstream | `<worktree>/.workstream.json` |
| [Open-workstream list](#open-workstream-list) entry | `~/.local/state/workstream/open/<workstream-id>.json` (**tentative**) |

## Session record

| Field | Type | Req | Writer | Reader | Needed for | Why stored |
| --- | --- | --- | --- | --- | --- | --- |
| `schema_version` | integer | yes | Every write | Every reader | Reading older records | The format can't be guessed safely |
| `id` | string, `<tool>-<native_id>` | yes | Start hook | Commands, displays | One name across agents; the file name | Native IDs are unique only per agent |
| `tool` | `claude`, `codex`, `opencode`, `agy`; open set | yes | Start hook | Takeover, running check, displays | Choosing how to resume and check | Only the hook knows reliably |
| `native_id` | string | yes | Start hook | Resume, transcript lookup | Resuming; matching later events | The agent's own key |
| `state` | `open`, `ended` | yes | Hooks, takeover | Lead check, lists | Knowing an end was seen | End events aren't kept anywhere else |
| `end_reason` | `exit`, `clear`, `replaced`, `removed` | when `ended` | Same | Resume, displays | Explaining why it ended | Not recoverable later |
| `updated_at` | time | yes | Every write | Lists, triage | Showing how old the information is | File times change on copy |
| `repo` | string, `owner/name` or directory name | no | Start hook | Lists, final log | Grouping by project | The folder may be gone by the final log |
| `cwd` | absolute path | no | Start hook | Lead check, resume | Finding the sessions in a worktree | Agents don't all report it afterward |
| `workstream_id` | string | no | Start hook, promotion, takeover; removed, with `role`, by talk, governor, finish or drop | Everything that joins the two records | The link | A directory can be shared by unlinked sessions |
| `role` | `lead`, `helper` | when linked | Takeover, lead check, promotion, start hook (`helper`, a declared role, or carried over by `/clear`) | Lead check, displays | Knowing who moves the work forward | Intent can't be observed |
| `purpose` | `talk`, `governor`, `project-review`, `iterate`, `implement`; open set | no | Launcher, command, agent, or your request | Displays, auto-link | Telling sessions apart | Intent can't be observed |
| `purpose_source` | `user`, `launcher`, `agent` | with `purpose` | Same | Purpose updates | A guess never overrides you or changes a link | Not recoverable later |
| `goal` | string | no; unlinked and helpers only | Launcher, agent, or your request | Displays, triage | Saying what the session is for | A transcript summary is costly and unreliable |
| `goal_source` | `user`, `launcher`, `agent` | with `goal` | Same | Goal updates | A guess never overrides you | Not recoverable later |
| `previous_id` | session `id` | no | Start hook after `/clear` | Takeover, transcript lookup | Reaching earlier context | The agent doesn't keep the chain for us |
| `transcript_path` | absolute path | no | Start hook | Takeover, final log | Handoff and later analysis | Layouts differ and change per agent |
| `process` | `{pid, started_at}` | no, **provisional** | Start hook | Running check | Telling this process from a reused PID | The process can't be found from the session ID on every agent |
| `activity` | [activity](#provisional-session-objects) | no, **provisional** | Agent hooks | Displays, triage | Sessions herdr can't see | A past event can't be queried |
| `attention` | list of [attention entries](#attention) | no | Session, agent hooks | Displays, triage | What the session needs from you | Only the session knows |
| `herdr` | [herdr object](#provisional-session-objects) | no, **provisional** | Start hook | herdr views | Joining to a herdr terminal | The join can't be derived; it is unproven |

- **A lead has no goal of its own:** displays show the workstream slug.
- A goal is never asked for.
- **One record holds `lead`.** When another takes the role, including after `/clear`, the old one becomes `helper`. Takeover first sets it to `ended`, `replaced`; until a successor exists it keeps `lead`, so a failed launch leaves it findable.
- The format allows more than one lead; v0 commands don't create a second.
- Not stored: session title, folder name or turn count that herdr already reports.

### Provisional session objects

| Object | Field | Type | Req | Why stored |
| --- | --- | --- | --- | --- |
| `activity` | `value` | `working`, `waiting`, `idle` | yes | A past event can't be queried |
| | `updated_at` | time | yes | Without it, old activity looks current |
| `herdr` | `terminal` | string, terminal address | no | herdr doesn't know our session ID |
| | `core_id` | string, herdr's permanent ID | no | As above |

### Example

```json
{
  "schema_version": 0,
  "id": "claude-3f2a9c10-7b1e-4d55-9a0f-1c2e8d7b6a41",
  "tool": "claude",
  "native_id": "3f2a9c10-7b1e-4d55-9a0f-1c2e8d7b6a41",
  "state": "open",
  "updated_at": "2026-11-27T20:40:02Z",
  "repo": "IdahoEv/dotfiles",
  "cwd": "/home/me/dotfiles/Is274-record-lifecycles",
  "workstream_id": "ws-9c41e07a52bd",
  "role": "lead",
  "purpose": "implement",
  "purpose_source": "launcher",
  "transcript_path": "/home/me/.claude/projects/dotfiles/3f2a9c10.jsonl",
  "process": { "pid": 48213, "started_at": "2026-11-27T19:02:11Z" },
  "activity": { "value": "waiting", "updated_at": "2026-11-27T20:40:02Z" },
  "attention": [
    {
      "cause": "question",
      "request": "Approve the field list?",
      "since": "2026-11-27T20:40:02Z",
      "effort": "5 minutes"
    }
  ]
}
```

## Workstream record

| Field | Type | Req | Writer | Reader | Needed for | Why stored |
| --- | --- | --- | --- | --- | --- | --- |
| `schema_version` | integer | yes | Every write | Every reader | Reading older records | The format can't be guessed safely |
| `id` | string, `ws-` + 12 random hex digits | yes, never changes | Create | Session link, list, telemetry | Identity across renames and ticket changes | Slug, tickets and branch can all change |
| `slug` | lowercase words | yes | Create, rename | Naming, displays | [Names](workstream-concept.md#names) | A drafted slug can't be reproduced |
| `title` | string | no; defaults to the slug | Create, edit command | PR title, displays | A fuller title | Your choice |
| `tickets` | list of [tickets](#tickets); may be empty | yes | Kickoff, edit command | Naming, PR, telemetry | Linking and chaining work | Branch names don't reliably hold them |
| `branch` | string | yes | Create, commands that switch branches | Commands, surprise check | Noticing an unexpected branch | git shows the current branch, not the expected one |
| `prs` | list of [PRs](#prs); may be empty | yes | PR commands and sync | Commands, displays, lists | Several PRs over one workstream | History, offline display and surprise checks |
| `stage` | `plan`, `wip`, `review` | yes | Kickoff, plan approval, review commands | Displays, triage | Where the work is | Not visible in git or GitHub |
| `stage_updated_at` | time | yes | Each `stage` write, including the same value | Displays, triage | How long in this stage; newer than a merge? | Not recoverable later |
| `reviews` | list of [reviews](#reviews); may be empty | yes | Kickoff and review commands | Displays, ready-to-merge check, triage | Progress of each reviewer | Local reviews leave no GitHub trace; bot rounds aren't marked reliably |
| `attention` | list of [attention entries](#attention) | no | Workflow commands | Displays, triage | Failures that outlive a session | A failed command leaves nothing to query |
| `type` | string | no | Create | The `{type}` naming token | Branch and name formats | Your choice |
| `group` | string | no | Create, edit command | Lists | Related workstreams, including across repos | Nothing else connects them |
| `settings` | [setting overrides](#setting-overrides) | no | Edit command, creation flags | Settings lookup | Settings for this workstream only | They exist nowhere else |

### Tickets

| Field | Type | Req | Needed for | Why stored |
| --- | --- | --- | --- | --- |
| `provider` | `github`, `shortcut`; open set | yes | Key and commands; a chain may mix providers | A bare number doesn't say which tracker |
| `id` | string | yes | Identifying the ticket | Not reliably in the branch name |
| `url` | string | no | Links, where the provider's URL can't be built | Not every provider's URL can be built |

### PRs

| Field | Type | Req | Needed for | Why stored |
| --- | --- | --- | --- | --- |
| `number` | integer | yes | Identifying the PR | A branch can have had several PRs |
| `url` | string | no | Links without a GitHub call | Saves a lookup in offline displays |
| `state` | `open`, `merged`, `closed` | yes | Display; GitHub stays authoritative | Offline display; noticing an unexpected change |
| `merged_at` | time | when `merged` | Telling a fresh merge from later work | Compared offline with stage and review times |
| `head` | commit SHA | no | The sync check | The sync check runs without a network call |
| `head_source` | `push`, `remote` | with `head`, if known | Keeping a push from being overwritten by an older remote read | The SHA doesn't show where it came from |

### Reviews

| Field | Type | Req | Needed for | Why stored |
| --- | --- | --- | --- | --- |
| `source` | `local`, `github`, `human`; open set | yes | Grouping in compact displays | A reviewer's name doesn't give its kind |
| `reviewer` | string, such as `coderabbit` or `bugbot` | no | Separate rounds per reviewer. Omitted only while the source's reviewer isn't named; the first named one replaces that entry | GitHub doesn't cover local or planned reviewers |
| `status` | `planned`, `running`, `accepted` | yes | What's left, what's running | Planned and accepted aren't visible elsewhere |
| `round` | integer, `0` before the first | yes | Rounds started by this reviewer | Rounds aren't marked reliably elsewhere |
| `updated_at` | time | yes | Showing a stalled review, such as "unchanged for 3 days" | Local and in-progress reviews leave no trace |

- There is at most one entry per `source` and `reviewer`.
- Entries are independent: reviews run in any order or in parallel.
- **A review starting moves `stage` to `review`.** Listing planned reviews doesn't. It stays there after all are accepted.
- Setting `stage` to `plan` or `wip` returns every entry to `planned` and keeps its `round`. One reviewer can also be reset alone.
- A reviewer that is no longer planned is removed.
- Old age alone never marks a review failed.
- This is step tracking for reviews only. It enforces nothing; [general step tracking](workstream-concept.md#unproven-tracking-step-status) remains unproven.
- **Gap:** no command records rounds per GitHub bot today.

### Setting overrides

`settings` holds only the values that differ for this workstream, nested like the [config keys](workstream-config.md): `review.max_rounds` is `{"review": {"max_rounds": 1}}`.

| Rule | Detail |
| --- | --- |
| Precedence | `WS_*` environment variables, then `settings`, then the [lower layers](workstream-config.md#layers) |
| Required checks | An environment variable cannot set a key that declares a required check |
| Weakening | Agents ask you before writing an override that weakens one. The record stores only the override, with no separate approval or waiver |

Which keys declare required checks is not yet defined, and the record can't prove you approved a change.

### Example

```json
{
  "schema_version": 0,
  "id": "ws-9c41e07a52bd",
  "slug": "record lifecycles and schemas",
  "tickets": [
    { "provider": "github", "id": "274" },
    { "provider": "github", "id": "275" }
  ],
  "branch": "Is274+275-session-workstream-record-lifecycles",
  "prs": [{ "number": 300, "state": "open", "head": "8b4a0ea", "head_source": "push" }],
  "stage": "review",
  "stage_updated_at": "2026-11-27T21:00:00Z",
  "reviews": [
    { "source": "local", "reviewer": "local-cycle", "status": "accepted", "round": 2, "updated_at": "2026-11-27T21:30:00Z" },
    { "source": "github", "reviewer": "coderabbit", "status": "running", "round": 2, "updated_at": "2026-11-27T22:10:00Z" },
    { "source": "github", "reviewer": "bugbot", "status": "accepted", "round": 1, "updated_at": "2026-11-27T21:50:00Z" }
  ],
  "attention": [],
  "settings": { "review": { "max_rounds": 1 } }
}
```

## Attention

Both records use the same entry.

| Field | Type | Req | Needed for | Why stored |
| --- | --- | --- | --- | --- |
| `cause` | `question`, `plan-approval`, `design-gate`, `auth`, `reviewer-failed`, `review-stalled`, `no-pr`, `unknown`; open set | yes | Sorting the queue | Only the writer knows |
| `request` | string | yes | What is being asked | Only the writer knows |
| `since` | time | yes | How long it has waited | The moment isn't recorded elsewhere |
| `holds_up` | string | no | Priority | Only the asker knows |
| `effort` | string, the asking agent's estimate | no | Triage | Only the asker can estimate it |
| `subject` | a review, `{source, reviewer}` with `reviewer` as in that review, or a PR, `{pr}` by number; workstream entries only | no | Clearing only what changed | The cause doesn't say which review or PR |

| Entry on | Holds | Cleared when |
| --- | --- | --- |
| Session | Its own questions and approvals | You reply to that session. A reply to another session leaves it |
| Workstream | Command failures, such as a stalled review or failed sign-in | Its subject changes or is removed, the failed command later succeeds, or `stage` takes a new value, which clears them all. With no subject, only the last two apply. The entry survives the session |

- "Ready to merge" is not an entry. It is worked out when there is at least one review, all are accepted, and a PR is open.
- **Unverified:** detecting a reply on each agent. A reply to a question dialog may fire no prompt hook, so the agent clears the entry.
- Whether herdr supplies any of these fields is **provisional**.

## Generated displays

These rules reproduce the [current tags](2026-11-19-workstream-tag-states.md). No display is read back as state.

| Shown | Generated when |
| --- | --- |
| `!` | The workstream or the displayed session has an attention entry, or the workstream is ready to merge. A workstream view includes its linked sessions |
| `PLAN`, `WIP` | `stage` is `plan` or `wip`, even with planned reviews |
| Review group, such as `L2✓ G2` | `stage` is `review`. One tag per `source`: highest `round`; `✓` if all accepted, `-` if all planned, otherwise in progress |
| `MERGED` | No PR is open, the latest is merged, and neither `stage` nor any review changed after `merged_at`. It replaces `PLAN`, `WIP` and the review group |
| `PR` | A PR is open |
| `DONE` | Written by finish on the session's name as the records are destroyed |
| `TALK`, `ITERATE` | The displayed session's `purpose` is `talk` or `iterate` |

Compact tags group reviewers; wider displays can show each one.

## Open-workstream list

One small file per workstream on this host.

| Field | Type | Req | Writer | Reader | Needed for | Why stored |
| --- | --- | --- | --- | --- | --- | --- |
| `schema_version` | integer | yes | Every write | Every reader | Reading older entries | As above |
| `id` | workstream `id` | yes | Create, conversion | Link lookup, lists | Finding a record from a session | The link holds only an ID |
| `path` | absolute worktree path | yes | Create, move | Same | Locating the record | Scanning every project folder is unreliable |

- Finish and drop remove the entry.
- A listed workstream is **gone** when its worktree is missing. With no entry, or an unreadable record, it is "can't tell".
- Hand edits can leave entries stale or missing.

```json
{ "schema_version": 0, "id": "ws-9c41e07a52bd", "path": "/home/me/dotfiles/Is274-record-lifecycles" }
```

## Agent handoff

| Needed | From |
| --- | --- |
| The workstream and its worktree | The list entry, then the workstream record |
| The old lead | The session record with this `workstream_id` and `role: lead` |
| Old context | Its `transcript_path`; `previous_id` for earlier ones |
| Whether to replace it | `state`, then the running check using `tool`, `native_id` and `process` |
| Tickets and code | `tickets`, `branch`, `prs` |

## Migrating `.workstream.json`

**Convert on write:** new code reads both formats. The first change to an old record, including linking a session to it or changing its lead, rewrites it as v0, assigns its `id` and adds its list entry. A record with no `schema_version` is old. Until converted, it isn't in the list, so a governor doesn't list it.

| Current field | Result | v0 |
| --- | --- | --- |
| `version` | Moved | `schema_version`, set to `0` |
| `kind` | Dropped | One kind; talk and iterate are session `purpose` |
| `tickets[].id`, `tickets[].url` | Kept | `tickets[]` |
| `ticket_provider` | Moved | `tickets[].provider` |
| `key` | Dropped | Derived from the tickets; without any, the slug |
| `key_aliases` | Dropped | The ID survives renames |
| `desc` | Moved | `slug`; if empty, from the branch name |
| `type` | Kept | `type` |
| `template_source` | Dropped | Looked up from settings |
| `tags`: `PLAN`, `WIP` | Moved | `stage` |
| `tags`: review tags | Moved | `reviews`, with `L`/`G`/`H` as `source` and no `reviewer`. The digit is `round`, else `0`. `-` is `planned`, `✓` `accepted`, neither `running`. `stage` is `review` if any has started, else `wip` |
| `tags`: `!` | Moved | One `attention` entry: cause `unknown`, a placeholder `request`, `since` the conversion time. Dropped if there are review tags, all `✓`, and `PR`: ready to merge is derived |
| `tags`: `PR` | Dropped | Derived from `prs` |
| `tags`: `MERGED`, `DONE` | Moved | `stage: review`; the converted PR is `merged`. With no `pr` object, no PR entry is made and the merge isn't kept |
| `tags`: `REVIEW`, `REVIEWED`, `READY`, custom | Dropped | None |
| `pr.number`, `url`, `state`, `head`, `head_source` | Moved | One `prs[]` entry. A missing `state` (normal today) is `merged` with a `MERGED` or `DONE` tag, else `open` until a sync |
| `reviews.local`, `reviews.remote` | Moved | `round` on the matching source, keeping the larger of this and the tag's. With no tag, a count above 0 makes a `planned` entry; a count of 0 makes none |
| `reviews.local_running`, `reviews.remote_running` | Moved | `status: running` on that entry, made if missing; sets `stage: review` |
| `claude_sessions`, `codex_sessions` | Dropped | No session records are made from them |

- `branch` comes from the worktree. `stage_updated_at`, each review's `updated_at` and any `merged_at` are all the conversion time. A record with no stage or review tag gets `wip`.
- Older `<git-dir>/chain` files convert the same way, as ticket lists.
- A converted workstream has no lead record, so the [lead check](workstream-lifecycle.md#lead-check-and-takeover) asks. Codex launch can no longer reuse a thread from `codex_sessions`.

## Left out

`model`, `effort`, session start time, `host` and base branch: no use for them in a record is established. Also out: a snapshot format and general step status.

## Effect on related work

None of these is edited here.

| Item | Effect |
| --- | --- |
| [#270](https://github.com/IdahoEv/dotfiles/issues/270) sessions list | Its `sessions[]` list is replaced by session records and a one-way link. `log_path` becomes `transcript_path`. `model`, `effort`, `host`, `started_at`, `ended_at` and `context_dir` are dropped; an end is recorded without its time. Unmet as written: the model, effort and host flags (AC 2), recording at launch (AC 3), last-seen values (AC 4) and the snapshot lookup (AC 5). Per-agent hook gaps still apply. |
| [#164](https://github.com/IdahoEv/dotfiles/issues/164) talk and iteration | Conflicts: a talk has no workstream until promoted; there is one kind and no key aliases; takeover replaces its resume script. A rename keeps the old branch and worktree names instead of moving them. Its prune sweep isn't part of these lifecycles. |
| [#255](https://github.com/IdahoEv/dotfiles/pull/255) tag states (merged) | Tags become output. Review counts and tag strings merge into per-reviewer entries. Stored stages are `plan`, `wip`, `review`. `[L- G-]` no longer shows before a review starts. A prompt no longer clears workstream failures or the ready-to-merge `!`, and a review or PR change clears only the failures about it. Session names stop being parsed for state. |
| [PR #262](https://github.com/IdahoEv/dotfiles/pull/262) layered settings | Its JSON files and `.workstreams/` folder differ from [workstream-config.md](workstream-config.md), which it marks superseded; expect an edit conflict. Nested `settings` works with either. It preserves key aliases, which v0 drops. |

## Open

- How each GitHub bot's rounds are detected.
- Which setting keys declare required checks, and how they are enforced.
- Provisional fields, until the herdr findings are accepted.
