#!/usr/bin/env bash
# agent-phase.sh — stamp a workstream's state onto its agent-view row.
#
#   agent-phase.sh <PLAN|WIP|MERGED|DONE>      set the stage; drops review tags
#   agent-phase.sh --plan-reviews              add the planned review sources (not started); keeps any already running
#   agent-phase.sh --review <L|G|H> <N|next|-> [ok]
#   agent-phase.sh --review <L|G|H> ok         N = round in progress, next = the round
#                                              after the current one, - = planned, ok =
#                                              accepted (keeps the current round)
#   agent-phase.sh --pr                        a PR exists
#   agent-phase.sh --attn | --ok               raise / clear the needs-you flag
#   agent-phase.sh --show | --clear
#
# Claude Code's agent view (`claude agents`) shows two state axes already:
# `status` (idle/busy — process level, set by the daemon) and `state`
# (working/blocked/done — turn level, set by the model). Neither says where a
# workstream is in ITS lifecycle. This script encodes that third axis as a prefix
# on the session's display name, the only field that is model-writable, unbounded,
# and visible in both the TUI and `claude agents --json`:
#
#   [!] [L2✓ G1] [PR] Sc74618 Build Docker Image
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
# Design: docs/2026-11-19-workstream-tag-states.md.
#
# The planned sources are decided here and nowhere else: L always, G unless
# ~/.config/local-review-only, H never. A settings layer will replace that.
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
# Writes `~/.claude/jobs/<id>/state.json` directly. That file is Claude Code
# internals rather than documented API, so this is deliberately defensive: it
# no-ops (exit 0, silent) whenever it isn't looking at a background session it
# understands. The alternative — the supported `/rename` command — can only be
# driven by the model mid-conversation, not by a shell step in a hook or
# script, which is exactly where the transitions happen.
#
# Nothing here is authoritative. The state is self-reported, so a session that
# dies mid-ticket keeps a stale prefix; `/board` recomputes true state from git
# + the tracker and is the thing to trust when they disagree.
#
# Exit codes: 0 always on the happy path AND on every "not applicable" case
#             (not a bg session, no job dir, unreadable state) — callers embed
#             this in larger workflows and must not abort over a cosmetic label.
#             1 usage error only (bad stage, source or round).

set -euo pipefail

die() { printf 'agent-phase: %s\n' "$*" >&2; exit 1; }

PHASES="PLAN WIP MERGED DONE"

usage() {
  printf 'usage: agent-phase.sh <%s>\n       agent-phase.sh --review <L|G|H> <N|next|-> [ok]\n       agent-phase.sh --plan-reviews | --pr | --attn | --ok | --show | --clear\n' \
    "$(echo "$PHASES" | tr ' ' '|')" >&2
}

# ---- args -------------------------------------------------------------------
phase="" action="set" src="" round="" accepted=""
case "${1:-}" in
  --show)    action="show" ;;
  --clear)   action="clear" ;;
  --pr)      action="pr" ;;
  --attn)    action="attn" ;;
  --ok)      action="ok" ;;
  --plan-reviews) action="plan-reviews" ;;
  --review)
    action="review"
    src="${2:-}" round="${3:-}"
    case "$src" in L|G|H) ;; *) usage; die "unknown review source '$src' (expected L, G or H)" ;; esac
    if [ "$round" = "ok" ]; then round="keep"; accepted=1; shift; fi
    [[ "$round" =~ ^([1-9][0-9]*|-|next|keep)$ ]] || { usage; die "bad round '$round' (expected a number >= 1, -, next or keep)"; }
    if [ -z "$accepted" ]; then
      case "${4:-}" in "") ;; ok) accepted=1 ;; *) usage; die "unknown status '$4' (expected ok)" ;; esac
    fi
    ;;
  -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0 ;;
  "")        usage; exit 1 ;;
  -*)        usage; die "unknown option: $1" ;;
  *)
    phase="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
    case " $PHASES " in
      *" $phase "*) ;;
      *) usage; die "unknown phase '$1' (expected one of: $PHASES)" ;;
    esac
    ;;
esac

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
  review) [ -n "$accepted" ] || [ "$round" = "-" ] || emit_phase REVIEW ;;
esac

# ---- locate the session's state file ----------------------------------------
# CLAUDE_JOB_DIR is exported into every tool call of a background session and
# names that session's own job dir. Its absence means we're in an interactive
# session (iTerm launcher, plain `claude`), where there is no agent-view row to
# label — not an error, just nothing to do.
job_dir="${CLAUDE_JOB_DIR:-}"
[ -n "$job_dir" ] || exit 0

state_file="$job_dir/state.json"
[ -f "$state_file" ] && [ -r "$state_file" ] && [ -w "$state_file" ] || exit 0

command -v python3 >/dev/null || exit 0

# ---- planned review sources ---------------------------------------------------
planned="L"
[ -e "$HOME/.config/local-review-only" ] || planned="L G"

# ---- rewrite the name's tag prefix ------------------------------------------
# Python rather than sed/jq: the write must be atomic (os.replace) because the
# daemon rewrites this same file on every status change, and a partial write
# would corrupt a session's state, not just its label. jq isn't guaranteed
# present; python3 ships with macOS.
out="$(PHASE="$phase" ACTION="$action" SRC="$src" ROUND="$round" ACCEPTED="$accepted" \
  PLANNED="$planned" python3 - "$state_file" <<'PY'
import json, os, re, sys, tempfile

path     = sys.argv[1]
phase    = os.environ["PHASE"]
action   = os.environ["ACTION"]
src      = os.environ["SRC"]
rnd      = os.environ["ROUND"]
accepted = bool(os.environ["ACCEPTED"])
planned  = os.environ["PLANNED"].split()

try:
    with open(path) as fh:
        state = json.load(fh)
except (OSError, ValueError):
    sys.exit(0)          # unreadable or mid-write by the daemon; cosmetic, skip

name = state.get("name")
if not isinstance(name, str):
    sys.exit(0)

# Parse the prefix we previously applied. Anchored to the known tag shapes so a
# ticket whose real title starts with bracketed text (e.g. "[spike] try X") keeps
# it. Legacy [REVIEW]/[REVIEWED]/[READY] stages are consumed and dropped.
TOKEN = r"[LGH](?:\d+✓?|-|✓)"
rest = name
attn = stage = None
reviews = {}
m = re.match(r"\[!\]\s*", rest)
if m:
    attn, rest = True, rest[m.end():]
m = re.match(r"\[(PLAN|WIP|MERGED|DONE|REVIEW|REVIEWED|READY)\]\s*", rest)
if m:
    stage = m.group(1) if m.group(1) in ("PLAN", "WIP", "MERGED", "DONE") else None
    rest = rest[m.end():]
else:
    m = re.match(r"\[(%s(?: %s)*)\]\s*" % (TOKEN, TOKEN), rest)
    if m:
        for tok in m.group(1).split():
            n = re.search(r"\d+", tok)
            status = "ok" if tok.endswith("✓") else "planned" if tok.endswith("-") else "run"
            reviews[tok[0]] = (int(n.group()) if n else 0, status)
        rest = rest[m.end():]
m = re.match(r"\[PR\]\s*", rest)
pr = bool(m)
if m:
    rest = rest[m.end():]
bare = rest

def tag(s):
    n, status = reviews[s]
    if status == "planned":
        return s + "-"
    return s + (str(n) if n else "") + ("✓" if status == "ok" else "")

def prefix():
    middle = ""
    if reviews:
        middle = "[%s]" % " ".join(tag(s) for s in "LGH" if s in reviews)
    elif stage:
        middle = "[%s]" % stage
    return " ".join(t for t in ("[!]" if attn else "", middle, "[PR]" if pr else "") if t)

def render():
    return " ".join(t for t in (prefix(), bare) if t)

def awaiting_merge():
    return bool(reviews) and pr and all(st == "ok" for _, st in reviews.values())

if action == "show":
    print(prefix())
    sys.exit(0)

emit = ""
if action == "clear":
    attn, stage, reviews, pr = None, None, {}, False
elif action == "attn":
    attn = True
elif action == "ok":
    attn = None
else:
    attn = None            # every real transition clears the flag
    if action == "pr":
        pr = True
    elif action == "plan-reviews":
        stage = None
        for s in planned:
            reviews.setdefault(s, (0, "planned"))
    elif action == "review":
        stage = None
        prev = reviews.get(src, (0, "planned"))[0]
        n = {"-": 0, "keep": prev, "next": prev + 1}.get(rnd) if not rnd.isdigit() else int(rnd)
        reviews[src] = (n, "ok" if accepted else "planned" if rnd == "-" else "run")
    else:
        stage, reviews = phase, {}
        if phase in ("MERGED", "DONE"):
            pr = False
    if action in ("pr", "review") and awaiting_merge():
        attn = True
        emit = "REVIEWED"

new = render()
if new == name:
    sys.exit(0)

state["name"] = new
# nameSource=user stops Claude Code's auto-naming from overwriting the tags
# with a summary of the conversation partway through the ticket.
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

if emit:
    print("emit=" + emit)
print(new)
PY
)" || true

# Review acceptance is only known once the name has been parsed, so the
# REVIEWED telemetry event comes back from the rewrite.
case "$out" in emit=REVIEWED*) emit_phase REVIEWED ;; esac
[ -z "$out" ] || printf '%s\n' "${out##*$'\n'}"
