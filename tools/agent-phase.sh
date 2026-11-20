#!/usr/bin/env bash
# agent-phase.sh — stamp a ticket's workflow phase onto .workstream.json and its agent-view row.
#
#   agent-phase.sh [--dir <path>] <PLAN|WIP|MERGED|DONE>   set the stage; drops review tags
#   agent-phase.sh [--dir <path>] --plan-reviews            add the planned review sources, not started
#   agent-phase.sh [--dir <path>] --review <L|G|H> <N|next|-|drop> [ok]
#   agent-phase.sh [--dir <path>] --review <L|G|H> ok       N = round in progress, next = the round
#                                                           after the current one, - = planned,
#                                                           ok = accepted (keeps the current round)
#   agent-phase.sh [--dir <path>] --pr                      a PR exists
#   agent-phase.sh [--dir <path>] --attn | --ok             raise / clear the needs-you flag
#   agent-phase.sh [--dir <path>] --show | --clear
#
# Claude Code's agent view (`claude agents`) shows two state axes already:
# `status` (idle/busy — process level, set by the daemon) and `state`
# (working/blocked/done — turn level, set by the model). Neither says where a
# workstream is in ITS lifecycle. This script encodes that third axis as a prefix
# on the session's display name, the only field that is model-writable, unbounded,
# and visible in both the TUI and `claude agents --json`:
#
#   [!][L2✓ G1][PR] Sc74618 Build Docker Image
#
#   [!]        needs the user, whatever the cause; always first
#   stage      [PLAN] [WIP] [MERGED] [DONE] — shown when no review is planned
#   reviews    one tag per planned source, replacing the stage while review is active:
#              <source><round><status>; source L local, G GitHub/bots, H human;
#              status: none = in progress, - = planned, ✓ = accepted
#   [PR]       a PR exists; MERGED and DONE drop it
#
# Any stage, review or PR change clears [!]. It is raised by --attn, and
# automatically when every planned source is accepted and a PR is open (awaiting
# merge). A UserPromptSubmit hook runs --ok so it clears when the user replies.
# The tag logic lives in lib/workstream.py (apply_transition); this script is the
# CLI, the telemetry emit and the state.json mirror. Design:
# docs/2026-11-19-workstream-tag-states.md.
#
# The name after the number is distilled from the ticket title by
# start-ticket.sh (gt::distill_title); this script only rewrites the prefix.
#
# Why the name and not the color: `/color` is declared `terminalOriented` with
# `requires:{ink:true}` and, unlike `/rename`, carries no `supportsNonInteractive`
# flag — a `--bg` session has no ink renderer, so a ticket agent cannot color
# itself when it changes phase. The palette is also only 8 colors and is already
# used per-agent-type in `.claude/agents/*.md` frontmatter, so overloading it
# would make a purple row ambiguous. Color stays free for a repo/project axis.
#
# Updates `.workstream.json` in the target worktree (`--dir`, default `.`) for
# every session when a workstream record exists, and additionally writes
# `~/.claude/jobs/<id>/state.json` inside a Claude background session. That
# state file is Claude Code internals rather than documented API, so the
# `state.json` step is deliberately defensive: it no-ops (exit 0, silent)
# whenever it isn't looking at a background session it understands. The
# alternative — the supported `/rename` command — can only be driven by the
# model mid-conversation, not by a shell step in a hook or script, which is
# exactly where the phase transitions happen.
#
# Nothing here is authoritative. The phase is self-reported, so a session that
# dies mid-ticket keeps a stale prefix; `/board` recomputes true state from git
# + the tracker and is the thing to trust when they disagree.
#
# Exit codes: 0 always on the happy path AND on every "not applicable" case
#             (no `.workstream.json`, not a bg session, no job dir, unreadable
#             state) — callers embed this in larger workflows and must not abort
#             over a cosmetic label.
#             1 usage error only (bad phase name or option).

set -euo pipefail

die() { printf 'agent-phase: %s\n' "$*" >&2; exit 1; }

PHASES="PLAN WIP MERGED DONE"

usage() {
  printf 'usage: agent-phase.sh [--dir <path>] <%s>\n       agent-phase.sh [--dir <path>] --review <L|G|H> <N|next|-|drop> [ok] | --review <L|G|H> ok\n       agent-phase.sh [--dir <path>] --plan-reviews | --pr | --attn | --ok | --show | --clear\n' \
    "$(echo "$PHASES" | tr ' ' '|')" >&2
}

# ---- args -------------------------------------------------------------------
dir="."
phase="" action="" src="" round="" accepted=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dir)
      [ "$#" -ge 2 ] && [ -n "$2" ] || { usage; die "--dir requires a path"; }
      dir="$2"
      shift 2
      ;;
    --dir=*)
      dir="${1#--dir=}"
      [ -n "$dir" ] || { usage; die "--dir requires a path"; }
      shift
      ;;
    --show|--clear|--pr|--attn|--ok|--plan-reviews)
      [ -z "$action" ] || { usage; die "unexpected extra argument: $1"; }
      action="${1#--}"
      shift
      ;;
    --review)
      [ -z "$action" ] || { usage; die "unexpected extra argument: $1"; }
      action="review"
      src="${2:-}" round="${3:-}"
      case "$src" in L|G|H) ;; *) usage; die "unknown review source '$src' (expected L, G or H)" ;; esac
      if [ "$round" = "ok" ]; then
        round="keep" accepted=1; shift 3
      else
        [[ "$round" =~ ^([1-9][0-9]*|-|next|keep|drop)$ ]] || { usage; die "bad round '$round' (expected a number >= 1, -, next, keep or drop)"; }
        case "${4:-}" in
          "") shift 3 ;;
          ok) accepted=1; shift 4 ;;
          *) usage; die "unknown status '$4' (expected ok)" ;;
        esac
      fi
      ;;
    -h|--help)
      sed -n '2,/^set -euo/p' "$0" | sed '$d'
      exit 0
      ;;
    -*)
      usage; die "unknown option: $1"
      ;;
    *)
      [ -z "$action" ] || { usage; die "unexpected extra argument: $1"; }
      action="set"
      phase="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
      case " $PHASES " in
        *" $phase "*) ;;
        *) usage; die "unknown phase '$1' (expected one of: $PHASES)" ;;
      esac
      shift
      ;;
  esac
done
[ -n "$action" ] || { usage; exit 1; }

# ---- telemetry --------------------------------------------------------------
# Recorded for every session, not just background ones: the phase change is
# real even when there is no agent-view row to label.
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
emit_phase() {
  # shellcheck source=lib/telemetry.sh
  { . "$SCRIPT_DIR/lib/telemetry.sh" && wf::emit phase "phase=$1"; } || true
}
case "$action" in
  set)    emit_phase "$phase" ;;
  review) [ -n "$accepted" ] || [ "$round" = "-" ] || [ "$round" = "drop" ] || emit_phase REVIEW ;;
esac

# ---- .workstream.json tags ----------------------------------------------------
ws_row=""
if [ -x "$SCRIPT_DIR/workstream.sh" ]; then
  ws="$SCRIPT_DIR/workstream.sh"
  case "$action" in
    show)
      if "$ws" phase --dir "$dir" --show 2>/dev/null; then
        exit 0
      fi
      ;;
    clear|pr|attn|ok|plan-reviews) "$ws" phase --dir "$dir" "--$action" >/dev/null 2>&1 || true ;;
    review)
      "$ws" phase --dir "$dir" --review "$src" "$round" ${accepted:+ok} >/dev/null 2>&1 || true ;;
    set)       "$ws" phase --dir "$dir" "$phase" >/dev/null 2>&1 || true ;;
  esac
  # Awaiting merge: every planned review accepted with a PR open. Recorded as REVIEWED
  # so the telemetry stage report keeps its post-review bucket.
  case "$action" in
    pr|review) "$ws" phase --dir "$dir" --awaiting-merge 2>/dev/null && emit_phase REVIEWED ;;
  esac
  ws_row="$("$ws" render row --dir "$dir" 2>/dev/null || true)"
fi

# ---- locate the session's state file ----------------------------------------
# CLAUDE_JOB_DIR is exported into every tool call of a background session and
# names that session's own job dir. Its absence means we're in an interactive
# session (iTerm launcher, plain `claude`), where there is no agent-view row to
# label (`.workstream.json` was already updated above) — not an error, just
# nothing to do for `state.json`.
job_dir="${CLAUDE_JOB_DIR:-}"
[ -n "$job_dir" ] || exit 0

state_file="$job_dir/state.json"
[ -f "$state_file" ] && [ -r "$state_file" ] && [ -w "$state_file" ] || exit 0

command -v python3 >/dev/null || exit 0

# ---- rewrite the name's phase prefix ----------------------------------------
# Python rather than sed/jq: the write must be atomic (os.replace) because the
# daemon rewrites this same file on every status change, and a partial write
# would corrupt a session's state, not just its label. jq isn't guaranteed
# present; python3 ships with macOS.
PHASE="$phase" ACTION="$action" SRC="$src" ROUND="$round" ACCEPTED="$accepted" WS_ROW="$ws_row" \
  LIB_DIR="$SCRIPT_DIR/lib" python3 - "$state_file" <<'PY'
import json, os, sys, tempfile

path     = sys.argv[1]
action   = os.environ["ACTION"]
ws_row   = os.environ.get("WS_ROW", "")

try:
    with open(path) as fh:
        state = json.load(fh)
except (OSError, ValueError):
    sys.exit(0)          # unreadable or mid-write by the daemon; cosmetic, skip

name = state.get("name")
if not isinstance(name, str):
    sys.exit(0)

sys.path.insert(0, os.environ["LIB_DIR"])
import workstream  # noqa: E402

if action == "show":
    print(workstream.name_prefix(name))
    sys.exit(0)

if ws_row:
    new = ws_row
else:
    # No workstream record: apply the transition to the name's own prefix.
    kw = {
        "clear": dict(clear=True), "pr": dict(pr=True), "attn": dict(attn=True), "ok": dict(ok=True),
        "plan-reviews": dict(plan_reviews=True),
        "review": dict(review=(os.environ["SRC"], os.environ["ROUND"], bool(os.environ["ACCEPTED"]))),
        "set": dict(phase=os.environ["PHASE"]),
    }[action]
    try:
        new = workstream.retag_name(name, **kw)
    except ValueError:
        sys.exit(0)
if new == name:
    sys.exit(0)

state["name"] = new
# nameSource=user stops Claude Code's auto-naming from overwriting the phase
# prefix with a summary of the conversation partway through the ticket.
state["nameSource"] = "user"

# Atomic replace: write a sibling temp file, fsync, then rename over the
# original. Rename is atomic within a filesystem, so a concurrent daemon read
# sees either the old file or the new one, never a truncated one.
dirname = os.path.dirname(path) or "."
fd, tmp = tempfile.mkstemp(dir=dirname, prefix=".state.json.")
try:
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    sys.exit(0)          # never fail a ticket workflow over a display label

print(new)
PY
