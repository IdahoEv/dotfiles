# Workstream tag states, transitions and needs-you signal

Status: approved and implemented (#168). Tags live in `.workstream.json`; logic is `apply_transition` in `tools/lib/workstream.py`. Tag groups are adjacent with no spaces, matching the existing `[WIP][PR]` rendering.

## Decision

The session name prefix is `[!]<stage-or-review>[PR] <label>`. Each part is optional except the second slot.

```
[!][L2✓ G1][PR] <label>      local accepted, GitHub in round 1, needs you
[WIP] <label>                  implementing
[L- G-][PR] <label>           both reviews planned, none started
```

## Slots

| Slot | Values | Notes |
| --- | --- | --- |
| `[!]` | present or absent | Needs the user, whatever the cause. Always first. |
| Stage | `PLAN`, `WIP`, `MERGED`, `DONE` | Shown when no review is planned or running |
| Review group | one tag per planned source, space-separated, in brackets | Replaces the stage while review is active |
| `[PR]` | present or absent | A PR exists; dropped by `MERGED` and `DONE` |

`READY` and `REVIEWED` are removed. "Ready for review" is `L-`; "review finished" is every planned source `✓`.

## Review tag

`<source><round><status>`

| Part | Values |
| --- | --- |
| Source | `L` local, `G` GitHub or external bots, `H` human |
| Round | digit; omitted before round 1 |
| Status | none = in progress, `-` = planned, not started, `✓` = accepted |

| Tag | Meaning |
| --- | --- |
| `L-` | planned, not started |
| `L2` | in progress, round 2 |
| `L2✓` | accepted after 2 rounds |

- `✓` is U+2713, not the emoji `✅`: one cell wide and needs no emoji font. ASCII fallback is `+`.
- Only planned sources appear. Serial, parallel and single-source runs differ only in which tags are present and their status.
- Reviewer-vs-fixer is not encoded; it is visible once the session is open.
- A source can return from `✓` or a digit to `-` on rework.

## Planned sources (interim)

One function in `agent-phase.sh` derives the set: `L` always; `G` unless `~/.config/local-review-only` is set; `H` never, unless a command marks it. The planned review config (sources, round limit, serial/parallel) will come from the workstream settings system; replacing this function is the only change then. Out of scope here.

## Needs-you rule

`[!]` is raised by any command or phase and does not name its cause; the session does.

| Cause | Raised by |
| --- | --- |
| Question open, or plan ready for approval | The session, before asking |
| Failed design gate | Review cycle |
| GitHub auth failure, reviewer failed to run, no PR found | `/open-pr`, `/github-review-comments` |
| Poll timeout or stall | `/github-review-comments` |
| Every planned source `✓` with a PR open (awaiting merge) | `--review ... ok` or `--pr`, automatically |

**Clearing:** any `agent-phase.sh` stage, review or PR change clears it, and a `UserPromptSubmit` hook runs `agent-phase.sh --ok` so it clears when the user replies. The record (and so the statusline) clears from the hook's working directory. The agent-row mirror also needs `CLAUDE_JOB_DIR` in the hook's environment, which is unverified; if absent, the row clears at the next transition.

## Transitions

| From | To | Trigger |
| --- | --- | --- |
| `PLAN` | `WIP` | Plan approved |
| `WIP` | `[L-]`, `[L- G-]` | Acceptance criteria met, tests green; planned sources set |
| source `-` | source `1` | That review starts |
| source `N` | source `N+1` | Next round |
| source `N` | source `N✓` | Accepted |
| any review state | `WIP` | Substantial changes; sources reset, `[PR]` kept |
| any | `MERGED`, `DONE` | `/land`, `/finalize` (drop `[PR]`) |

## Interface

```
agent-phase.sh <PLAN|WIP|MERGED|DONE>
agent-phase.sh --plan-reviews                    # add planned sources as "-"; keeps started ones
agent-phase.sh --review <L|G|H> <N|next|-> [ok]  # round N, the next round, or planned
agent-phase.sh --review <L|G|H> ok               # accepted, round kept
agent-phase.sh --attn | --ok
agent-phase.sh --pr | --show | --clear
```

Commands report facts (source, round, accepted); only `agent-phase.sh` builds tag strings.

## Implementation scope

`agent-phase.sh` and its tests, statusline parser (render `[!]` prominently), `UserPromptSubmit` hook in `dot_claude/settings`, `local-review-cycle-procedure`, `github-review-comments`, `open-pr` (md and sh), `finalize`, `start.md`, `CLAUDE.md.tmpl`, `finalize-check`, telemetry tests, `docs/workflow-architecture.md`.
