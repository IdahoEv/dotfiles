"""One-off backfill of review telemetry for PRs that finished /local-review-cycle
before finding text, round SHAs and reviewer models were recorded.

Sources: the telemetry log (which sessions and rounds ran), reviewer subagent
transcripts (model, tokens, findings text), and git history (head SHA per round).
Output: appended events in the live schema (docs/workflow-telemetry.md) marked
backfill=1. Existing lines are never rewritten and re-runs append nothing.
Fields no source holds are reported as unknown, never as zero.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wf_usage  # noqa: E402

SEVERITIES = ("Critical", "High", "Medium", "Low")
_FINDING_RE = re.compile(
    r"^[\s>*\-\d.)]*(?P<sev>Critical|High|Medium|Low)\**\s*\|\s*(?P<loc>[^|]+?)\s*\|\s*(?P<defect>[^|]+?)\s*(?:\|.*)?$",
    re.I)
_LOC_RE = re.compile(r"^`?(?P<path>[^:`]+?)`?(?::(?P<line>\d+)(?:[-,]\d+)*)?$")
_REVIEW_LINE_RE = re.compile(r"(\d+)\s+rounds?:\s*(\d+)\s+fixed,\s*(\d+)\s+dismissed,\s*(\d+)\s+deferred")
EVENT_FIELD_CAP = 200


def normalize_claim(text):
    s = re.sub(r"\s+", " ", text.lower())
    s = re.sub(r"[^a-z0-9 .\-/]", "", s)
    s = s.rstrip(" .-")
    s = re.sub(r"^(the|a|an) ", "", s)
    return s.strip()


def bucket(line):
    if not line:
        return "L0"
    lo = ((line - 1) // 10) * 10 + 1
    return f"L{lo}-L{lo + 9}"


def finding_key(path, line, claim):
    return hashlib.sha256(f"{path}\n{bucket(line)}\n{claim}".encode()).hexdigest()


def parse_report(text):
    """[{severity, path, line, claim}] from reviewer-contract finding lines."""
    out = []
    for raw in (text or "").splitlines():
        m = _FINDING_RE.match(raw)
        if not m:
            continue
        loc = _LOC_RE.match(m["loc"].strip())
        if not loc:
            continue
        path = loc["path"].strip()
        line = int(loc["line"]) if loc["line"] else None
        sentence = re.split(r"(?<=[.!?])\s", m["defect"].strip(), maxsplit=1)[0]
        out.append({"severity": m["sev"].capitalize(), "path": path, "line": line,
                    "claim": normalize_claim(f"{path} {sentence}")})
    return out


def read_transcript(path):
    """{first_ts, last_ts, model, tokens_in, tokens_out, report} for one subagent transcript."""
    info = {"first_ts": None, "last_ts": None, "tokens_in": 0, "tokens_out": 0, "report": None}
    models, seen, last_text = Counter(), set(), None
    for e in wf_usage._entries(path):
        ts = wf_usage.parse_ts(e.get("timestamp"))
        if ts:
            info["first_ts"] = info["first_ts"] or ts
            info["last_ts"] = ts
        if e.get("type") != "assistant":
            continue
        msg = e.get("message") or {}
        usage, model = msg.get("usage"), msg.get("model")
        mid = msg.get("id") or e.get("uuid")
        if usage and model and model != "<synthetic>" and mid not in seen:
            seen.add(mid)
            models[model] += usage.get("output_tokens") or 0
            info["tokens_in"] += sum(usage.get(k) or 0 for k in
                                     ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            info["tokens_out"] += usage.get("output_tokens") or 0
        for c in msg.get("content") or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and c.get("name") == "SubagentHandback":
                info["report"] = (c.get("input") or {}).get("message")
            elif c.get("type") == "text":
                last_text = c.get("text")
    info["model"] = models.most_common(1)[0][0] if models else None
    if info["report"] is None:
        info["report"] = last_text
    return info


def default_base(git_dir, ref):
    for cand in ("origin/HEAD", "origin/main", "main", "origin/master", "master"):
        if cand != ref and subprocess.run(["git", "-C", git_dir, "rev-parse", "--verify", "-q", cand],
                                          capture_output=True).returncode == 0:
            return cand
    return None


def head_sha_at(git_dir, ref, ts):
    """Newest commit exclusive to ref's first-parent chain committed at or before ts.

    Commits already on the default branch are excluded so a rebase or amend that
    post-dates the round reads as unknown rather than as a main-branch commit.
    """
    cmd = ["git", "-C", git_dir, "rev-list", "-1", "--first-parent", f"--before={ts.isoformat()}", ref]
    base = default_base(git_dir, ref)
    merged = base and subprocess.run(["git", "-C", git_dir, "merge-base", "--is-ancestor", ref, base],
                                     capture_output=True).returncode == 0
    if base and not merged:
        cmd.append(f"^{base}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and sha else None


def resolve_ref(git_dir, branch):
    for ref in (branch, f"origin/{branch}"):
        if subprocess.run(["git", "-C", git_dir, "rev-parse", "--verify", "-q", ref],
                          capture_output=True).returncode == 0:
            return ref
    return None


def parse_review_line(body):
    m = _REVIEW_LINE_RE.search(body or "")
    return dict(zip(("rounds", "fixed", "dismissed", "deferred"), map(int, m.groups()))) if m else None


def cap(v):
    if isinstance(v, str):
        return "".join(" " if ord(c) < 32 else c for c in v)[:EVENT_FIELD_CAP]
    return v


def event_id(e):
    """Identity of a backfilled event; equal ids mean already written."""
    ev = e["event"]
    base = (ev, e.get("branch"), e.get("reviewer"), e.get("round"))
    if ev == "review.round":
        return base + (e.get("state"),)
    if ev == "review.launch":
        return base + (e.get("agent_id"),)
    return base + (e.get("agent_id"), e.get("idx"))


def load_log(path):
    out = []
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def pair_findings(parsed, existing):
    """Pair parsed findings with existing triage events by severity, then order.

    Returns [(parsed, existing_event or None)]. The event is never altered; the
    pairing is recorded as matched_ts only.
    """
    pool = defaultdict(list)
    for e in existing:
        pool[e.get("severity")].append(e)
    return [(p, pool[p["severity"]].pop(0) if pool[p["severity"]] else None) for p in parsed]


def plan_branch(branch, events, projects, git_dir, pr_body=None):
    """(new_events, summary) for one branch. Pure apart from reading transcripts and git."""
    evs = [e for e in events if e.get("branch") == branch]
    summary = {"branch": branch, "rounds": 0, "rounds_sha": 0, "launches": 0, "launches_model": 0,
               "findings": 0, "findings_text": 0, "findings_unmatched": 0, "tokens_out": 0,
               "sessions": 0, "sessions_no_transcripts": 0, "unknown": [], "notes": []}
    if not evs:
        summary["status"] = "none"
        summary["notes"].append("no telemetry events for this branch (cloud-only or unlogged): nothing to join to")
        summary["unknown"] += ["round SHA", "reviewer model", "finding text", "reviewer tokens", "reviewer effort"]
        review = parse_review_line(pr_body)
        if review:
            summary["pr_review"] = review
        return [], summary
    template = {k: evs[0].get(k) for k in ("v", "run_id", "repo", "ticket", "branch")}
    ref = resolve_ref(git_dir, branch)
    if ref is None:
        summary["notes"].append("branch not found in git: round SHAs unknown")

    new = []
    round_evs = [e for e in evs if e["event"] == "review.round"]
    by_point = {}
    for e in round_evs:
        by_point.setdefault((e.get("round"), e.get("state")), e)
    summary["rounds"] = len(by_point)
    for e in by_point.values():
        if e.get("sha"):
            summary["rounds_sha"] += 1
            continue
        ts = wf_usage.parse_ts(e.get("ts"))
        sha = head_sha_at(git_dir, ref, ts) if ref and ts else None
        if sha:
            summary["rounds_sha"] += 1
            new.append({**e, "sha": sha, "backfill": 1})

    reviewers = {e.get("reviewer") for e in evs if e["event"] == "review.finding" and e.get("source") != "bot"}
    for e in evs:
        if e["event"] == "review.result" and e.get("source") != "bot":
            reviewers.update(r for r in str(e.get("reviewers", "")).split(",") if r)
    ends = {}
    for e in round_evs:
        ts = wf_usage.parse_ts(e.get("ts"))
        if e.get("state") == "end" and isinstance(e.get("round"), int) and ts:
            ends[e["round"]] = max(ends.get(e["round"], ts), ts)
    starts = [t for t in (wf_usage.parse_ts(e.get("ts")) for e in round_evs if e.get("state") == "start") if t]
    first_start = min(starts) if starts else None
    live_launch = {(e.get("reviewer"), e.get("round")) for e in evs
                   if e["event"] == "review.launch" and not e.get("backfill")}
    sessions = sorted({e["session_id"] for e in evs if e.get("session_id")})
    summary["sessions"] = len(sessions)
    existing_findings = defaultdict(list)
    for e in evs:
        if e["event"] == "review.finding" and e.get("source") != "bot" and not e.get("backfill"):
            existing_findings[(e.get("reviewer"), e.get("round"))].append(e)

    for sid in sessions:
        subs = [(p, a) for p, a in wf_usage.transcripts_for_session(sid, projects) if a is not None]
        if not subs:
            summary["sessions_no_transcripts"] += 1
            continue
        cands = []
        for path, agent in subs:
            if agent not in reviewers and not str(agent).endswith("-reviewer"):
                continue
            t = read_transcript(path)
            if first_start and t["first_ts"] and t["first_ts"] < first_start:
                summary["notes"].append(f"{agent} transcript {os.path.basename(path)} starts before the first round: skipped")
                continue
            # A round's reviewers finish before its end event, and an aborted attempt
            # finishes earlier than the same round's retry.
            rnd = next((r for r, end in sorted(ends.items()) if t["last_ts"] and t["last_ts"] <= end), None)
            if rnd is None:
                summary["notes"].append(f"{agent} transcript {os.path.basename(path)} ends after no logged round: skipped")
                continue
            if (agent, rnd) in live_launch:
                summary["notes"].append(f"{agent} round {rnd}: launch already logged live, not backfilled")
                continue
            cands.append((agent, rnd, path, t))
        latest = {}
        for agent, rnd, _, t in cands:
            latest[(agent, rnd)] = max(latest.get((agent, rnd), t["first_ts"]), t["first_ts"])
        for agent, rnd, path, t in cands:
            superseded = t["first_ts"] < latest[(agent, rnd)]
            agent_id = os.path.basename(path)[len("agent-"):-len(".jsonl")]
            base = {**template, "session_id": sid, "backfill": 1}
            summary["launches"] += 1
            summary["launches_model"] += bool(t["model"])
            summary["tokens_out"] += t["tokens_out"]
            launch = {**base, "ts": iso(t["first_ts"]), "event": "review.launch", "reviewer": agent,
                      "round": rnd, "source": "local", "agent_id": agent_id,
                      "tokens_in": t["tokens_in"], "tokens_out": t["tokens_out"]}
            if t["model"]:
                launch["model"] = t["model"]
            new.append(launch)
            if superseded:
                summary["notes"].append(f"{agent} round {rnd}: launch from an aborted attempt, findings not backfilled")
                continue
            pairs = pair_findings(parse_report(t["report"]), list(existing_findings[(agent, rnd)]))
            for i, (p, match) in enumerate(pairs):
                summary["findings"] += 1
                summary["findings_text"] += 1
                summary["findings_unmatched"] += match is None
                f = {**base, "ts": iso(t["last_ts"] or t["first_ts"]), "event": "review.finding",
                     "reviewer": agent, "round": rnd, "source": "local", "severity": p["severity"],
                     "path": p["path"], "claim": p["claim"], "agent_id": agent_id, "idx": i,
                     "key": finding_key(p["path"], p["line"], p["claim"])}
                if p["line"]:
                    f["line"] = p["line"]
                if match:
                    f["matched_ts"] = match["ts"]
                new.append(f)
            paired = {id(m) for _, m in pairs if m}
            summary["findings_unmatched"] += sum(1 for e in existing_findings[(agent, rnd)] if id(e) not in paired)

    n_existing = sum(len(v) for v in existing_findings.values())
    summary["findings"] = max(summary["findings"], n_existing)
    status = "full"
    if summary["sessions_no_transcripts"] or not summary["launches"] or summary["rounds_sha"] < summary["rounds"]:
        status = "partial" if (summary["rounds_sha"] or summary["launches"]) else "none"
    summary["status"] = status
    if not summary["launches"]:
        summary["unknown"] += ["reviewer model", "finding text", "reviewer tokens"]
    if summary["launches"] and summary["sessions_no_transcripts"]:
        summary["unknown"].append(f"reviewer model, finding text and tokens for "
                                  f"{summary['sessions_no_transcripts']} of {summary['sessions']} sessions")
    summary["unknown"].append("reviewer effort (not in transcripts)")
    if summary["rounds_sha"] < summary["rounds"]:
        summary["unknown"].append(f"round SHA for {summary['rounds'] - summary['rounds_sha']} of {summary['rounds']} round events")
    if summary["findings_unmatched"]:
        summary["unknown"].append(f"verdict pairing for {summary['findings_unmatched']} findings")
    review = parse_review_line(pr_body)
    if review:
        summary["pr_review"] = review
    return new, summary


def append_new(log_path, events, existing, dry_run=False):
    """Append events whose identity is not already in the log; returns (written, skipped)."""
    have = {event_id(e) for e in existing if e.get("backfill") == 1}
    fresh = []
    for e in events:
        eid = event_id(e)
        if eid in have:
            continue
        have.add(eid)
        fresh.append(e)
    if fresh and not dry_run:
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        with open(log_path, "a") as fh:
            for e in fresh:
                fh.write(json.dumps({k: cap(v) for k, v in e.items()}, separators=(",", ":")) + "\n")
    return len(fresh), len(events) - len(fresh)


def fetch_pr(number, repo=None):
    cmd = ["gh", "pr", "view", str(number), "--json", "headRefName,body"]
    if repo:
        cmd += ["--repo", repo]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"cannot read PR {number}: {r.stderr.strip()}")
    d = json.loads(r.stdout)
    return d["headRefName"], d.get("body")


def format_summary(s, written, skipped):
    def n(v, total=None):
        return f"{v}/{total}" if total is not None else str(v)
    lines = [f"{s['branch']}: {s['status']}",
             f"  recovered: round SHAs {n(s['rounds_sha'], s['rounds'])}, "
             f"reviewer launches {s['launches']} (model on {s['launches_model']}), "
             f"findings with text {s['findings_text']} of {s['findings']}"
             + (f", reviewer output tokens {s['tokens_out']}" if s["launches"] else "")]
    if s["sessions_no_transcripts"]:
        lines.append(f"  sessions without local transcripts: {s['sessions_no_transcripts']} of {s['sessions']}")
    if s.get("pr_review"):
        r = s["pr_review"]
        lines.append(f"  PR summary: {r['rounds']} rounds, {r['fixed']} fixed, {r['dismissed']} dismissed, {r['deferred']} deferred")
    lines.append("  unknown: " + ("; ".join(s["unknown"]) or "none"))
    lines += [f"  note: {x}" for x in s["notes"]]
    lines.append(f"  events written {written}, already present {skipped}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wf-backfill.sh", description=__doc__)
    ap.add_argument("--pr", action="append", default=[], type=int, help="PR number (repeatable)")
    ap.add_argument("--branch", action="append", default=[], help="branch name (repeatable)")
    ap.add_argument("--repo", help="owner/repo, to select events and PRs (default: current repo's PRs; any repo's events)")
    ap.add_argument("--git-dir", default=".", help="checkout holding the branch (default: cwd)")
    ap.add_argument("--log", default=os.environ.get("WF_TELEMETRY_LOG") or os.path.join(
        os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "workflow-telemetry", "events.jsonl"))
    ap.add_argument("--projects", default=None, help="transcripts root (default: WF_CLAUDE_PROJECTS or ~/.claude/projects)")
    ap.add_argument("--dry-run", action="store_true", help="report only; append nothing")
    args = ap.parse_args(argv)

    targets = [(b, None) for b in args.branch] + [fetch_pr(n, args.repo) for n in args.pr]
    if not targets:
        ap.error("give at least one --pr or --branch")
    existing = load_log(args.log)
    if args.repo:
        existing = [e for e in existing if e.get("repo", "").lower() == args.repo.lower()]
    for branch, body in targets:
        repos = {e.get("repo") for e in existing if e.get("branch") == branch}
        if len(repos) > 1:
            print(f"{branch}: branch name appears in {sorted(repos)}; pass --repo", file=sys.stderr)
            continue
        new, summary = plan_branch(branch, existing, args.projects, args.git_dir, body)
        written, skipped = append_new(args.log, new, existing, args.dry_run)
        print(format_summary(summary, written, skipped))
        if not args.dry_run:
            existing = load_log(args.log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
