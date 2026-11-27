# Can herdr collect session and workstream data across hosts?

**I recommend extending herdr (`herdr-core`) instead of building our own transport.** The [session and workstream records](workstream-schema.md) stay the only authoritative stored state; the collector's last-seen copy is derived, disposable and used when a host's data is unavailable, including a missing record. A small collector reads the records through herdr, joins them to herdr's live terminal list, and copies a few short values into terminal labels for panes. A test panel in the `herdr-app` window showed emoji labels from both hosts. The recommendation depends on matching each record to its terminal, which is [only partly proven](#what-the-collector-and-records-need). In tests, remote changes arrived in under 0.25 s, but herdr sees only sessions in its own terminals and an unreachable host's rows **vanish from `terminal.list` while the app keeps showing the old ones**.

Why:

- herdr already carries live state and blocking questions between hosts over SSH.
- It has nowhere to keep records that outlast their terminals, apart from small shared documents we would have to fill ourselves.
- It sees only agents attached to its terminals, so sessions run another way, such as in the `claude agents` view, need data from our records.

This design is for sessions started once it is built. Picking up sessions that already exist is not a requirement.

## What was tested

Marks: **T** tested, **D** read from docs or source (linked), **U** unverified, including inferences.

Tested on 2026-11-27 with macOS arm64 and a second Linux x86_64 host: `herdr-core` (`hc`) 0.1.22 on both, `herdr-app` 0.1.18 on the Mac, Claude Code 2.1.332 and agy 1.5.13 on both (1.5.18 in later reruns), Codex 0.169.0 (Mac) and 0.171.0 (Linux), OpenCode 2.3.2 (Mac) and 2.4.2 (Linux, later reruns). I used separate throwaway herdr sessions and installed no agent integrations.

`hc` and `herdr-app` are different products from the older [`herdr` terminal UI](#the-older-herdr-terminal-ui), which I did not install.

## What the collector and records need

The [record schemas](workstream-schema.md) define a [session record](workstream-schema.md#session-record) per session and a [workstream record](workstream-schema.md#workstream-record) in its worktree, plus one file per open workstream in a host's [open-workstream list](workstream-schema.md#open-workstream-list). A session links to its workstream by ID; the workstream keeps no session list.

Collector:

- Keep a last-seen copy of each host's data, with the time it was read. A missing row means unknown, not finished. The [lifecycle](workstream-lifecycle.md#triggers-by-agent) already counts a session on another host as "can't tell".
- Check host state and do not rely on events to detect an outage.
- Enforce its own deadline outside `hc` on every call, because `--timeout` [did not bound a hung `hc exec`](#when-a-host-is-unreachable). An outside 5 s deadline ended a hung `hc exec`, and a local call afterwards worked (T). On expiry, treat that host's data from the call as unknown, not empty.
- Read records by running a workstream command with `hc exec --on <machine>`, because the [concept doc](workstream-concept.md#records-and-storage) routes all reads through those commands. `hc file read` was measured only as a transport, and reading the JSON files directly would give up that rule.
- Each monitored host needs that command, with the records' `schema_version` in its output; a stand-in command run through `hc exec` returned JSON in about 20 ms, and a missing one failed with `spawn_failed` (T). A missing command, or records with a higher `schema_version` than the collector knows, mean that host's records are unknown, not empty. A tool that meets a higher number reports it and does not write ([common rules](workstream-schema.md#common-rules)).
- Decide who writes and clears each label it copies, since labels have no expiry.

Requirements for the two records ([record schemas](workstream-schema.md), from [#274](https://github.com/IdahoEv/dotfiles/issues/274) and [#275](https://github.com/IdahoEv/dotfiles/issues/275)):

| Need | Where in the schemas | Status | Reason |
| --- | --- | --- | --- |
| Our session ID, the agent's own session ID, tool and transcript location | Session `id`, `native_id`, `tool`, `transcript_path` | Met | herdr's terminal record has no lasting native session ID or resume data; OpenCode's ID appears only while working (T) |
| Role or purpose tag, project, optional workstream ID | Session `role`, `purpose`, `repo`, `workstream_id` | Met | herdr has no such fields (T) |
| Whether a session is open or ended, and why | Session `state`, `end_reason` | Met | A destroyed record and an unreachable host look the same (U), so the collector still needs its last-seen copy |
| Optional herdr terminal address plus that core's permanent ID | Session `herdr.terminal`, `herdr.core_id`, **provisional** | Met, provisional | Joins a record to live state. Addresses are per core, machine names are local to the viewing host, and cores have [permanent IDs](https://github.com/herdrdev/herdr-core/blob/v0.1.22/schema/hc.openrpc.json) (D). A terminal may outlive its session, leaving old labels behind (U) |
| Latest activity, and attention cause, request, start of waiting, what it holds up and effort | Session `activity.value`, `.updated_at`; `attention[].cause`, `.request`, `.since`, `.holds_up`, `.effort`; **provisional** | Met, provisional | The concept doc requires [activity](workstream-concept.md#two-records) and [attention data](workstream-concept.md#attention), and herdr has neither for sessions outside its terminals (T). The `cause` set already names workflow failures such as `auth` and `review-stalled` |
| The workstream's goal, branch, tickets and PRs, to name and group its sessions | Workstream `title`, `slug`, `branch`, `tickets`, `prs` | Met | herdr has no workstream record: no slug, tickets or PRs (T), and its [branch](https://github.com/herdrdev/herdr-app/blob/v0.1.18/defaults/herdr.d.ts) is the pane's current one, not the workstream's expected one (D); only the records connect a project to its sessions |
| Stage, review progress and workstream-level failures, to triage a host | Workstream `stage`, `stage_updated_at`, `reviews`, `attention` | Met | Local review rounds leave no GitHub trace ([reviews](workstream-schema.md#reviews)) and a failed command leaves nothing to query ([attention](workstream-schema.md#attention)) (D); herdr has neither (T) |
| For sessions inside herdr, no copies of turn count, title or folder that herdr reports for that agent | [Not stored](workstream-schema.md#session-record); session `cwd` is stored for resume and the lead check | Met while live; **missing title** once ended | herdr clears the title and current folder on exit (T) but keeps the turn count and launch `cwd` ([source](https://github.com/herdrdev/herdr-core/blob/v0.1.22/crates/herdr-core/src/status.rs), D), so only the title is unavailable once ended. `cwd` is the launch folder; the current one is [`foreground.cwd`](https://github.com/herdrdev/herdr-core/blob/v0.1.22/schema/README.md) (D) |
| Last-updated time on everything it reads | `updated_at` on both records; the [open-workstream list](workstream-schema.md#open-workstream-list) entry has none | Met for records, **missing** on list entries | A file read carries no sign that its contents are current, so a stale list entry looks live and hand edits can leave entries stale or missing (U) |
| A per-host list of open workstreams that maps each ID to its record location, readable without any session and updated on create, move, finish and drop | [Open-workstream list](workstream-schema.md#open-workstream-list): one file per workstream with `id` and `path`, location tentative | Met, tentative location | Records live in worktrees, and only sessions link to workstreams, by ID ([D](workstream-schema.md#session-record)). A workstream without a session is [normal](workstream-concept.md#edge-cases) |
| A read command that lists a host's sessions and open workstreams, including those with no session, and links them | None: the schemas fix file locations and writes only | **Missing** | The concept doc routes all reads through [commands](workstream-concept.md#records-and-storage) (D). Without one, the collector reads files directly and gives up that rule |
| A writer that works despite agent sandboxes, for example outside the agent | The [lifecycle](workstream-lifecycle.md#triggers-by-agent) lists writing session records from a sandbox as unverified on all four agents | Requirement stands, untested (U) | [Some agents could not label their own terminal](#can-an-agent-write-its-own-data) |

While a host is connected, the collector shows herdr's value for anything both hold, such as activity; the records are what remain for sessions outside herdr terminals and for a host it cannot reach. [Coverage varies by agent](#what-herdr-already-tracks), status clears on exit and unreachable rows vanish (T).

The record-to-terminal join is partly proven. Claude Code's session-start hook received the terminal address (`HC_TERMINAL_ID`) on both hosts (T). Other agents' hooks are untested (U), and Codex's shell on the Mac [had no address](#can-an-agent-write-its-own-data) (T). Labelling the terminal at launch (`hc run --label`) is an untested alternative (U). One terminal is not always one session: see OpenCode [below](#what-herdr-already-tracks).

## How herdr collects across hosts

| Topic | Finding | Mark |
| --- | --- | --- |
| Transport | SSH runs `hc connect`, a JSON API over standard input and output ([D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/commands.md)). SSH does authentication and encryption; the core listens on a local Unix socket, not a public TCP port ([D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/security.md)) | T |
| Ownership | Each host's core owns its terminals and files; the local core merges lists and events | [D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/machines.md) |
| Setup per host | `hc` installed (`machine add` offers to copy it, `--install` for scripts) and SSH access. Then `hc machine add <ssh target> --name box` | [D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/machines.md) |
| Linux | The core needs systemd lingering to outlive logout; `machine ls` reports it as `keeps_running_after_logout` | T (already on), [D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/machines.md) |
| Login prompts | A Tailscale SSH browser check blocked non-interactive SSH until a person approved it | T |
| Failed login | Password and host-key prompts need a person. The machine shows `needs_login`; retries after 2 min, 5 min, then every 10 min | [D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/machines.md) |
| Access granted | Full command, file and terminal access to that account | [D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/security.md) |
| API stability | "Preview", version 0.x, additive changes only | [D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/schema/README.md) |
| Removing a host | `machine rm` only forgets it locally; its terminals keep running | [D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/machines.md) |

### Data per session

| Group | Fields (T) |
| --- | --- |
| Identity | `address`, `name`, `parent`, `identity`, `template`, `labels` |
| Process | `argv`, `cwd`, `pid`, `foreground`, `state`, `exit_code`, `signal`, `reason` |
| Agent status | `status` (`state`, `kind`, `progress`, `app`, `title`, `msg`), `status_ms`, `turn`, `reported`, child `records` |
| Display and lifecycle | `title`, `screen`, `cols`, `rows`, `created_ms`, `finished_ms`, `keep`, `rm`, `die_with_parent`, `notify` |

Piped `hc ls --json` is shortened and omits labels, `msg`, `kind` and `status_ms`. For full records use `terminal.list` over `hc connect`, `hc get` or event subscriptions (T). `hc ls --label k=v` filters across hosts (T). The API has no terminal rename (T, [schema](https://github.com/herdrdev/herdr-core/blob/v0.1.22/schema/README.md)).

### Freshness

| Change | Time to reach the Mac | Mark |
| --- | --- | --- |
| Remote label, including the call that set it | about 26 ms (3 samples) | T |
| Shared document write | 27 ms | T |
| Agent status report triggered by sending input | about 225 ms | T |
| Foreground process | read about twice a second; heartbeat every 15 s | [D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/schema/README.md) |

Changes made while disconnected appeared on reconnect. Restarting the remote test core kept the live terminal, its status, labels and a document (T).

When an agent exits, its terminal becomes `finished`, status and title clear, and labels stay. The default `hc ls` hides it; `--all` shows it (T).

### When a host is unreachable

I broke the link from the Mac with a wrapper passed to `machine add --via`. That let me break it without changing the network or the second host, and then cut a plain SSH link for real (below).

| Behavior | Link cut | Link silently hung |
| --- | --- | --- |
| `machine.list` | `unreachable`, with `since_ms` and `why` | stays `connected` for about 44 s, then `connecting` |
| `terminal.list` | remote rows disappear; no cached or dimmed rows | remote rows are silently left out; the first call took 3.0 s |
| Events | none on the cut | none until about 45 s |
| Remote calls | `get`, `read`, `label` and `doc.get` fail at once with `unavailable` | see below |
| Recovery | reconnected 4.2 s after restore (about 2 s with `machine.connect`), then sent a `missed` snapshot | reconnect at about 45 s, with a `missed` snapshot |

All rows are T. The `terminal.list` result carries a `machines` array with each host's state. In a rerun it showed `unreachable`, `since_ms` and `why` after a cut, but **`connected` for about 43 s of a hang while the host's rows were missing** (T).

### A real network cut

I dropped all traffic on the Linux host for 3 minutes with a firewall rule, over a plain SSH link (T).

| Time | `terminal.list` |
| --- | --- |
| 4 s after the cut (first sample) | rows gone, host still `connected`; the call took 3 s |
| by 19 s | `connecting` |
| about 29 s | `unreachable`; `why` quotes the SSH error, including the host's IP address |
| 21 s after the network returned | `connected`, rows back, a `missed` event |

Subscribers got no event during the cut.

During a hang, `hc exec --on box --timeout 5` took **40.0 s** despite the timeout. A following `hc file read`, started about 40 s into the hang, failed 4.8 s later with "lost the line" and a warning that the call may have run. `hc machine ls` stayed instant (T).

During the same cut, **`herdr-app` kept the old remote row, still `blocked`**. A test panel's `machines()` reported the host `unavailable`, the sidebar said `unreachable`, and the remote terminal showed a reconnecting notice; it was restored afterwards (T). A panel or collector must mark a row stale from the host's state, because the row alone looks current.

## What herdr already tracks

Agents report their own state through the [OSC 7501 protocol](https://mitchellh.com/writing/program-status-osc7501) ([spec](https://www.superlogical.com/rex/docs/build/program-status)), terminal escape codes that carry the states `idle`, `working`, `done`, `blocked` and `error`. `hc` [does not guess status from screen text](https://github.com/herdrdev/herdr-core/blob/v0.1.22/crates/herdr-core/src/status.rs) (D). A [third-party post](https://dev.to/roidayan/osc-7501-your-coding-agent-can-now-tell-your-terminal-it-needs-you-29a) lists support from Claude Code 2.1.295, Codex 0.163.0 and OpenCode 2.2.0 (D).

| Agent | Activity (T) | Needs attention | Session identity (T) |
| --- | --- | --- | --- |
| Claude Code, both hosts | `working` with the current action; `done` with the final reply | `blocked` permission (folder trust); `blocked` question with its text and options (T) | session title; no session ID |
| Codex, both hosts | `working`, `done`, `idle`; no message | `blocked` permission, without the request text (T); `blocked` question untested (U). **Nothing is reported during its update or hook-review startup dialogs** (T) | title; no session ID |
| agy, both hosts | `working`, `done` with a message, `idle` | `blocked` permission, including the full command, and `blocked` question (T) | no title, no session ID |
| OpenCode, both hosts | `idle`, `working`; ends `idle`, not `done` | `blocked` permission on both hosts and question on Linux, with a generic message (T) | title; a child record carries its session ID while working or blocked |

- Claude reported `error` with the API error text. A subagent had its own `working` record, removed when it finished (T). `error` from other agents is untested (U).
- **With two OpenCode terminals on Linux, one reported the other's blocking question** while its own session had finished (T). I infer they shared one OpenCode server (U).
- `status_ms` is when the state last changed, and `turn` counts each exit from `working` ([source](https://github.com/herdrdev/herdr-core/blob/v0.1.22/crates/herdr-core/src/status.rs), D). Status clears when the program exits (T).
- `send` to a `blocked` terminal is refused without `--force` (T).
- herdr clients share a [`herdr.seen` label](https://github.com/herdrdev/herdr-app/blob/v0.1.18/docs/labels.md) to record that a finished turn was seen, and `herdr.pinned` to pin (D).
- `herdr-app` v0.1.18's [README and docs](https://github.com/herdrdev/herdr-app/tree/v0.1.18/docs) name no resume signal (D), and I saw no resume data from these four (T). Whether a newer version adds one is unverified (U).
- **Only agents attached to an `hc` terminal are visible** (T). The `claude agents` view reported no status, though its title said two sessions awaited input (T). With my settings, bare `claude` opens that view; `claude "<prompt>"` opened a session that reported (T). A background session attached with `claude attach` did report its blocking question. Claude inside tmux inside `hc` reported nothing on either host. Cloud sessions are untested (U).

## Ways to carry our metadata

| Carrier | Carries | Limits | Effort | Mark |
| --- | --- | --- | --- | --- |
| Terminal name | slug | 1–32 of `a-z 0-9 - _ .`; no emoji; set at start, no rename | none | T |
| Terminal title (agent session name) | emoji and text | owned by the program, cleared on exit | none | T |
| Labels (`hc label`) | emoji tags, IDs, short values | a 5,000-character value and keys with spaces or emoji worked; upper limit unknown (U). No expiry | low | T |
| Custom status report (OSC 7501) | emoji title, message of about 330 characters | the agent's next report would replace it (U); custom child records untested (U) | low | T |
| Shared documents (`doc.set`) | structured values | 1 MiB each; API only; name rules as for terminal names | medium | T |
| Records read through herdr (file read and a stand-in command tested) | anything | we own the format, cache and timeouts; works for sessions outside herdr terminals | medium | T |
| Plain `ssh cat` | anything | 88–99 ms without connection reuse, against 13–15 ms for `hc file read` and 20–28 ms for `hc exec` | medium | T |
| `herdr-app` mod | labels and status | needs its own data source for our records | medium | T |

- **Renaming:** Claude's `/rename` to `🔧⏳ 276 herdr` reached the other host. Codex on the Mac showed the same name with `| work` appended. agy set no title (T). OpenCode rename is untested (U).
- **Labels:** they can be set from another host, sync through events and survive a core restart and agent exit. They last only as long as the terminal (T). herdr suggests them for [small, slowly changing values](https://github.com/herdrdev/herdr-app/blob/v0.1.18/docs/labels.md), reserves the `herdr.` prefix, and puts larger state in documents (D).
- **Documents:** they survive a restart, can live on another host, and reject stale writes by version (T). Subscribers get the name and version, not the contents, and must refetch after `missed` ([CLI and API docs](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/commands.md), D).

### Can an agent write its own data?

Each agent was asked to label its own terminal.

| Agent | Mac | Linux |
| --- | --- | --- |
| Claude Code | worked, allowed by auto mode (T) | worked (T) |
| OpenCode | worked (T) | worked (T) |
| agy | failed: running `hc` gave "operation not permitted" (T); cause not established (U) | sandbox blocked it as read-only; worked after approval to run outside (T) |
| Codex (`--no-daemon`) | failed: `HC_TERMINAL_ID` was empty in its shell (T) | failed: its sandbox made the herdr state directory read-only (T) |

## Showing it in a pane and reading it from an agent

| Use | Pane | Agent |
| --- | --- | --- |
| Tags and session state | **Yes** (T): a test script in an `hc` terminal and a `herdr-app` panel showed both hosts with emoji labels | **Yes** (T): through test scripts, Claude Code read both hosts' state and labels from `hc connect` |
| Triage | The script showed remote blocking questions first (T). Holds-up and effort need our records (T) | **Yes** (T): a separate Claude run ranked blocked agents on both hosts using herdr data and stand-in remote records. It noted that permission requests lacked the command |

In the `herdr-app` window (T):

- In a mod (an add-on panel), `terminals()` gives `status` as a bare word. The kind and message are in a separate `report` field. `agents()` lacks them and labels ([source](https://github.com/herdrdev/herdr-app/blob/v0.1.18/defaults/herdr.d.ts), D).
- A new mod did not dock by itself in the default layout; `pane.split` opened it.
- The built-in Agents list did not show my test terminals, which lacked the app's labels ([guide](https://github.com/herdrdev/herdr-app/blob/v0.1.18/defaults/AGENTS.md)).
- Mods can also run commands and read files on a remote host ([guide](https://github.com/herdrdev/herdr-app/blob/v0.1.18/defaults/AGENTS.md), D).

## The older `herdr` terminal UI

All D, from the v0.9.5 docs. I made no two-host test because the installed stack is `hc` and `herdr-app`.

| Topic | `herdr` v0.9.5 |
| --- | --- |
| Cross-host | [Saved SSH machines](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/connecting-machines.mdx) in one agent list; each host runs its own server |
| Unreachable host | last state stays [visible but dimmed](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/connecting-machines.mdx); reconnect delay grows to 2 min |
| Command-line reads | `herdr --machine <label> agent list`, [one host per call](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/cli-reference.mdx) |
| Agent state | Claude Code, Codex and agy from [screen detection](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/agents.mdx), so an unknown prompt can show as idle; the OpenCode [integration](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/integrations.mdx) reports state |
| Session identity | integrations report native session IDs and support [resume](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/session-state.mdx) |
| Custom data | [pane metadata](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/socket-api.mdx): tokens, titles and state labels, 80 characters each, expiry up to 24 h; usable in the sidebar |
| Rename | [`herdr agent rename`](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/cli-reference.mdx) |

Whether its custom tokens cross hosts is unverified (U). I saw only descriptions of the third-party tools `herdr-remote` and `herdrm`, which target this UI, and did not evaluate them (U).

## Options

| Option | Verdict |
| --- | --- |
| Use herdr as is | No: misses sessions outside its terminals, our attention fields and our records' last-known values for a lost host |
| **Extend `herdr-core`** | **Recommended.** Build a collector beside it on the public API, which already carries live state, events and SSH transport; the only change it needs from `herdr-core` itself is a terminal rename |
| Build our own collection | No: would rebuild the transport, live state and events that work today, including plain `ssh` at 88–99 ms a call |

All three keep the records; the choice is only how a collector reaches the other hosts.
