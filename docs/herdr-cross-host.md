# Can herdr collect session and workstream data across hosts?

**I recommend extending herdr (`herdr-core`) instead of building our own transport.** Session records stay the source for our metadata. A small collector reads them through herdr, joins them to herdr's live terminal list, and copies a few short values into terminal labels for panes. In tests, remote changes arrived in under 0.25 s, but herdr sees only sessions in its own terminals and **drops an unreachable host's rows instead of marking them stale**.

Why:

- herdr already carries live state and blocking questions between hosts over SSH.
- It has nowhere to keep records that outlast their terminals, apart from small shared documents we would have to fill ourselves.
- It sees only agents attached to its terminals, so sessions run another way, such as in the `claude agents` view, need data from our records.

This design is for sessions started once it is built. Picking up sessions that already exist is not a requirement.

## What was tested

Marks: **T** tested, **D** read from docs or source (linked), **U** unverified, including inferences.

Tested on 2026-11-27 with macOS arm64 and a second Linux x86_64 host: `herdr-core` (`hc`) 0.1.22 on both, `herdr-app` 0.1.18 on the Mac, Claude Code 2.1.332 and agy 1.5.13 on both, Codex 0.169.0 (Mac) and 0.171.0 (Linux), OpenCode 2.3.2 (Mac only). I used separate throwaway herdr sessions and installed no agent integrations.

`hc` and `herdr-app` are different products from the older [`herdr` terminal UI](#the-older-herdr-terminal-ui), which I did not install.

## What the collector and records need

Collector:

- Keep a last-seen copy for each host. A missing row means unknown, not finished.
- Check host state, set its own timeout on every call, and do not rely on events to detect an outage.
- Read records by running a workstream command with `hc exec --on <machine>`, because the [concept doc](workstream-concept.md#records-and-storage) routes all reads through those commands. `hc file read` was measured only as a transport.
- Each monitored host needs that command, with a format version in its output; running it through `hc exec` is untested (U). A missing or incompatible command means that host's records are unknown, not empty.
- Decide who writes and clears each label it copies, since labels have no expiry.

Requirements for the session and workstream records ([#274](https://github.com/IdahoEv/dotfiles/issues/274), [#275](https://github.com/IdahoEv/dotfiles/issues/275)):

| Need | Reason |
| --- | --- |
| Our session ID, the agent's own session ID, tool and transcript location | herdr's terminal record has no lasting native session ID or resume data; OpenCode's ID appears only while working (T) |
| Role or purpose tag, project, optional workstream ID | herdr has no such fields (T) |
| A read command that lists a host's sessions and open workstreams, including those with no session, and links them | A workstream without a session is [normal](workstream-concept.md#edge-cases). The command keeps storage layout out of the collector |
| A per-host list of open workstreams that maps each ID to its record location, readable without any session and updated on create, move, finish and drop | Records live in worktrees, and only sessions link to workstreams, by ID |
| Optional herdr terminal address plus that core's permanent ID | Joins a record to live state. Addresses are per core, machine names are local to the viewing host, and cores have [permanent IDs](https://github.com/herdrdev/herdr-core/blob/v0.1.22/schema/hc.openrpc.json) (D). A terminal may outlive its session, leaving old labels behind (U) |
| Last-updated time | A file read carries no sign that its contents are current |
| What the request holds up and the effort to answer | herdr has neither (T) |
| Own activity and attention data for sessions outside herdr terminals | herdr reports nothing for them (T) |
| Latest activity, and attention cause, request and start of waiting, recorded whenever the writer can observe them, including inside herdr; what it can observe is untested (U) | The concept doc requires [activity](workstream-concept.md#two-records) and [attention data](workstream-concept.md#attention). [Coverage varies by agent](#what-herdr-already-tracks), status clears on exit and unreachable rows vanish (T). The collector prefers herdr's value while present; for an unreachable host it has only its last-seen copy |
| For sessions inside herdr, no copies of turn count, title or folder that herdr reports for that agent | herdr already has them (T). `cwd` is the launch folder; the current one is [`foreground.cwd`](https://github.com/herdrdev/herdr-core/blob/v0.1.22/schema/README.md) (D) |
| A writer that works despite agent sandboxes, for example outside the agent | [Some agents could not label their own terminal](#can-an-agent-write-its-own-data) |

The record-to-terminal join is unproven: whether agent hooks receive the terminal's address (`HC_TERMINAL_ID`) is untested (U), and it was [empty in Codex's shell](#can-an-agent-write-its-own-data) on the Mac (T). Labelling the terminal with our session ID at launch (`hc run --label`) is an untested alternative (U).

## How herdr collects across hosts

| Topic | Finding | Mark |
| --- | --- | --- |
| Transport | SSH runs `herdr-core connect`, a JSON API over standard input and output. SSH does authentication and encryption; no TCP port opens | T, [D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/machines.md) |
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
| Foreground process | read about twice a second; heartbeat every 15 s | [D](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/machines.md) |

Changes made while disconnected appeared on reconnect. Restarting the remote test core kept the live terminal, its status, labels and a document (T).

When an agent exits, its terminal becomes `finished`, status and title clear, and labels stay. The default `hc ls` hides it; `--all` shows it (T).

### When a host is unreachable

I broke the link from the Mac with a wrapper passed to `machine add --via`. Failure timing with a plain SSH target is untested (U).

| Behavior | Link cut | Link silently hung |
| --- | --- | --- |
| `machine.list` | `unreachable`, with `since_ms` and `why` | stays `connected` for about 44 s, then `connecting` |
| `terminal.list` | remote rows disappear; no cached or dimmed rows | remote rows are silently left out; the first call took 3.0 s |
| Events | none on the cut | none until about 45 s |
| Remote calls | `get`, `read`, `label` and `doc.get` fail at once with `unavailable` | see below |
| Recovery | reconnected 4.2 s after restore (about 2 s with `machine.connect`), then sent a `missed` snapshot | reconnect at about 45 s, with a `missed` snapshot |

All rows are T. The `terminal.list` result also has a [`machines` array](https://github.com/herdrdev/herdr-core/blob/v0.1.22/schema/hc.openrpc.json) with each host's `state`, `since_ms` and `why` (D). I did not record what it showed during either failure (U).

During a hang, `hc exec --on box --timeout 5` took **40.0 s** despite the timeout. A following `hc file read`, started about 40 s into the hang, failed 4.8 s later with "lost the line" and a warning that the call may have run. `hc machine ls` stayed instant (T).

What the `herdr-app` window shows here is untested. From its [source](https://github.com/herdrdev/herdr-app/blob/v0.1.18/src/hc.rs), I suspect it keeps old rows, since a cut sends no removal event (U). Its [guide](https://github.com/herdrdev/herdr-app/blob/v0.1.18/defaults/AGENTS.md) says an offline host's layout is `unavailable` (D).

## What herdr already tracks

Agents report their own state through the [OSC 7501 protocol](https://mitchellh.com/writing/program-status-osc7501) ([spec](https://www.superlogical.com/rex/docs/build/program-status)), terminal escape codes that carry the states `idle`, `working`, `done`, `blocked` and `error`. `hc` [does not guess status from screen text](https://github.com/herdrdev/herdr-core/blob/v0.1.22/crates/herdr-core/src/status.rs) (D). A [third-party post](https://dev.to/roidayan/osc-7501-your-coding-agent-can-now-tell-your-terminal-it-needs-you-29a) lists support from Claude Code 2.1.295, Codex 0.163.0 and OpenCode 2.2.0 (D).

| Agent | Activity (T) | Needs attention | Session identity (T) |
| --- | --- | --- | --- |
| Claude Code, both hosts | `working` with the current action; `done` with the final reply | `blocked` permission (folder trust); `blocked` question with its text and options (T) | session title; no session ID |
| Codex, both hosts | `working`, `done`, `idle`; no message | `blocked` untested (U). **Nothing is reported during its update or hook-review startup dialogs** (T) | title; no session ID |
| agy, both hosts | `working`, `done` with a message, `idle` | `blocked` permission, including the full command, and `blocked` question (T) | no title, no session ID |
| OpenCode, Mac only (not installed on Linux) | `idle`, `working`; ends `idle`, not `done` | `blocked` untested (U) | title; a child record carries its session ID only while working |

- `error` and Claude subagent records are untested (U).
- `status_ms` is when the state last changed, and `turn` counts each exit from `working` ([source](https://github.com/herdrdev/herdr-core/blob/v0.1.22/crates/herdr-core/src/status.rs), D). Status clears when the program exits (T).
- `send` to a `blocked` terminal is refused without `--force` (T).
- herdr clients share a [`herdr.seen` label](https://github.com/herdrdev/herdr-app/blob/v0.1.18/docs/labels.md) to record that a finished turn was seen, and `herdr.pinned` to pin (D).
- `herdr-app` documents a separate [resume signal](https://github.com/herdrdev/herdr-app/blob/v0.1.18/README.md) (OSC 7577) for agents that send it (D). I saw no resume data from these four (T).
- **Only agents attached to an `hc` terminal are visible** (T). The `claude agents` view reported no status, though its title said two sessions awaited input (T). With my settings, bare `claude` opens that view; `claude "<prompt>"` opened a session that reported (T). Attaching from that view, tmux inside `hc` and cloud sessions are untested (U).

## Ways to carry our metadata

| Carrier | Carries | Limits | Effort | Mark |
| --- | --- | --- | --- | --- |
| Terminal name | slug | 1–32 of `a-z 0-9 - _ .`; no emoji; set at start, no rename | none | T |
| Terminal title (agent session name) | emoji and text | owned by the program, cleared on exit | none | T |
| Labels (`hc label`) | emoji tags, IDs, short values | a 5,000-character value and keys with spaces or emoji worked; upper limit unknown (U). No expiry | low | T |
| Custom status report (OSC 7501) | emoji title, message of about 330 characters | the agent's next report would replace it (U); custom child records untested (U) | low | T |
| Shared documents (`doc.set`) | structured values | 1 MiB each; API only; name rules as for terminal names | medium | T |
| Records read through herdr (file read tested) | anything | we own the format, cache and timeouts; works for sessions outside herdr terminals | medium | T |
| Plain `ssh cat` | anything | 88–99 ms without connection reuse, against 13–15 ms for `hc file read` and 20–28 ms for `hc exec` | medium | T |
| `herdr-app` mod | display only | needs its own data source for our records | medium | [D](https://github.com/herdrdev/herdr-app/blob/v0.1.18/docs/mods.md) |

- **Renaming:** Claude's `/rename` to `🔧⏳ 276 herdr` reached the other host. Codex on the Mac showed the same name with `| work` appended. agy set no title (T). OpenCode rename is untested (U).
- **Labels:** they can be set from another host, sync through events and survive a core restart and agent exit. They last only as long as the terminal (T). herdr suggests them for [small, slowly changing values](https://github.com/herdrdev/herdr-app/blob/v0.1.18/docs/labels.md), reserves the `herdr.` prefix, and puts larger state in documents (D).
- **Documents:** they survive a restart, can live on another host, and reject stale writes by version (T). Subscribers get the name and version, not the contents, and must refetch after `missed` ([CLI and API docs](https://github.com/herdrdev/herdr-core/blob/v0.1.22/docs/commands.md), D).

### Can an agent write its own data?

Each agent was asked to label its own terminal.

| Agent | Mac | Linux |
| --- | --- | --- |
| Claude Code | worked, allowed by auto mode (T) | worked (T) |
| OpenCode | worked (T) | not installed (U) |
| agy | untested (U) | sandbox blocked it as read-only; worked after approval to run outside (T) |
| Codex (`--no-daemon`) | failed: `HC_TERMINAL_ID` was empty in its shell (T) | failed (T); I suspect the sandbox (U) |

## Showing it in a pane and reading it from an agent

| Use | Pane | Agent |
| --- | --- | --- |
| Tags and session state | **Yes** (T): my test script in an `hc` terminal listed both hosts, blocked first, with emoji labels, app, kind, message and host state | **Likely** (U): the script read the same JSON through `hc connect` (T); I did not test an agent reading it |
| Triage | Same script showed remote blocking questions first (T). Holds-up and effort need our records (T) | the script read herdr fields (T); record files can be read remotely (T). I did not test an agent doing the triage (U) |

For the native `herdr-app` window:

- Showing custom labels there is untested, because the test would have changed my live app (U).
- A throwaway mod passed `herdr-app check`, which shows only that it loads and renders once (T).
- The mod API's `agents()` list lacks `msg`, `kind` and labels; `terminals()` returns full core records ([source](https://github.com/herdrdev/herdr-app/blob/v0.1.18/src/hc.rs), D). Mods can also run commands and read files on a remote host ([guide](https://github.com/herdrdev/herdr-app/blob/v0.1.18/defaults/AGENTS.md), D).
- App screens omit terminals without the app's labels, including ones on other hosts that it did not start ([guide](https://github.com/herdrdev/herdr-app/blob/v0.1.18/defaults/AGENTS.md), D).

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
| Use herdr as is | No: misses sessions outside its terminals, our attention fields and last-known state of a lost host |
| **Extend `herdr-core`** | **Recommended** |
| Build our own collection | No: would rebuild SSH transport, live state and events that work today |
