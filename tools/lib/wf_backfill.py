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
import repo_facts  # noqa: E402
import wf_usage  # noqa: E402

SEVERITIES = ("Critical", "High", "Medium", "Low")
_FINDING_RE = re.compile(
    r"^[\s>*\-\d.)]*(?P<sev>Critical|High|Medium|Low)\**\s*\|\s*(?P<loc>[^|]+?)\s*\|\s*(?P<defect>[^|]+?)\s*(?:\|.*)?$",
    re.I)
_LOC_RE = re.compile(r"^`?(?P<path>[^:`\s]+?)`?(?::(?P<line>\d+)(?:\s*[-,]\s*\d+)*)?(?:\s*\(.*\))?$")
_REVIEW_LINE_RE = re.compile(r"(\d+)\s+rounds?:\s*(\d+)\s+fixed,\s*(\d+)\s+dismissed,\s*(\d+)\s+deferred")
EVENT_FIELD_CAP = 200


def clean_claim(text):
    return re.sub(r"\s+", " ", text).strip()


def relative_path(path, roots):
    for root in filter(None, roots):
        prefix = root.rstrip("/") + "/"
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


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
                    "claim": clean_claim(f"{path}: {sentence}")})
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
    if e.get("source") == "bot":
        if ev == "review.result":
            return (ev, "bot", e.get("run_id"), e.get("batch"))
        if e.get("comment_id") is not None:
            return (ev, "bot", e.get("run_id"), e.get("comment_id"))
        return (ev, "bot", e.get("run_id"), e.get("sha"), e.get("path"), e.get("line"), cap(e.get("claim")))
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
    top = subprocess.run(["git", "-C", git_dir, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    toplevel = top.stdout.strip()
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
            roots = [toplevel, wf_usage.session_cwd(path)]
            parsed = parse_report(t["report"])
            for p in parsed:
                p["path"] = relative_path(p["path"], roots)
            pairs = pair_findings(parsed, list(existing_findings[(agent, rnd)]))
            for i, (p, match) in enumerate(pairs):
                summary["findings"] += 1
                summary["findings_text"] += 1
                summary["findings_unmatched"] += match is None
                f = {**base, "ts": iso(t["last_ts"] or t["first_ts"]), "event": "review.finding",
                     "reviewer": agent, "round": rnd, "source": "local", "severity": p["severity"],
                     "path": p["path"], "claim": p["claim"], "agent_id": agent_id, "idx": i}
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
    have = {event_id(e) for e in existing if e.get("backfill") == 1 or e.get("source") == "bot"}
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


_COPILOT_LOGINS = {"copilot-pull-request-reviewer[bot]", "Copilot"}
_SUPPRESSED_RE = re.compile(
    r"^\s*(?:[-*]|\d+\.)\s+\*\*`?([^:`*\s]+?)(?::(\d+)(?:\s*[-,]\s*\d+)*)?`?\*\*\s*(?:[:—–-]\s*)?(.*)$"
)
_SEVERITY_RE = re.compile(r"\b(Critical|High|Medium|Low)\b", re.I)
_REJECT_RE = re.compile(
    r"\b(disagree|not a bug|false positive|rejected|intended|by design|won't fix|wontfix|invalid|already handled|not needed|unnecessary|intentional)\b|👎",
    re.I,
)
_PARTIAL_RE = re.compile(r"\bpartially\s+valid\b", re.I)
_FIXED_RE = re.compile(r"\b(fixed|addressed|applied|resolved|done|updated)\b|👍", re.I)


def clean_bot_claim(path, body):
    """Build a one-sentence claim naming path, stripped of HTML/code/markdown."""
    text = re.sub(r"```.*?```", " ", body or "", flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = clean_claim(text)
    sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0] if text else "Copilot comment"
    if path and path not in sentence:
        return clean_claim(f"{path}: {sentence}")
    return sentence


def parse_bot_severity(body):
    m = _SEVERITY_RE.search(body or "")
    return m.group(1).capitalize() if m else "Medium"


def parse_suppressed_review_body(body):
    """Extract [{path, line, text, resolved}] from Copilot review-body bullets."""
    out = []
    in_suppressed = False
    for raw in (body or "").splitlines():
        if "<summary>" in raw and "suppressed" in raw.lower():
            in_suppressed = True
            continue
        if in_suppressed and "</details>" in raw:
            in_suppressed = False
            continue
        m = _SUPPRESSED_RE.match(raw)
        if not m:
            continue
        path, line_s, rest = m.group(1), m.group(2), m.group(3)
        if not line_s and "." not in path and "/" not in path:
            continue
        resolved = "[RESOLVED]" in rest
        rest = rest.replace("[RESOLVED]", "").strip()
        out.append({
            "path": path,
            "line": int(line_s) if line_s else None,
            "text": rest,
            "resolved": resolved,
        })
    return out


def infer_bot_verdict(replies, resolved, later_touched):
    """Infer (verdict, validity, reason) from thread replies, resolution, and later commits."""
    reply_text = "\n".join(r.get("body") or "" for r in replies)
    has_fix_commit = bool(later_touched)
    if _REJECT_RE.search(reply_text):
        return "dismissed", "rejected", "disagreed-in-thread"
    if _PARTIAL_RE.search(reply_text):
        verdict = "fixed" if (resolved or has_fix_commit or _FIXED_RE.search(reply_text)) else "dismissed"
        return verdict, "partial", "partial-in-thread"
    if _FIXED_RE.search(reply_text):
        return "fixed", "valid", "fixed-in-thread"
    if has_fix_commit:
        return "fixed", "valid", "later-commit-touched-file"
    if resolved:
        return "fixed", "valid", "thread-resolved"
    return "deferred", "valid", "unresolved-at-merge"


def resolve_run_identity(branch, repo, existing):
    """Resolve (run_id, repo, ticket) matching live telemetry for branch."""
    for e in existing:
        if e.get("branch") == branch and e.get("run_id"):
            return e["run_id"], e.get("repo", repo), str(e.get("ticket", ""))
    ticket = repo_facts.ticket_from_branch(branch)
    scheme = repo_facts.ticket_scheme(branch)
    if not ticket:
        return None, repo, ""
    if scheme == "shortcut":
        run_id = f"sc-{ticket}"
    else:
        run_id = f"{repo}#{ticket}"
    for e in existing:
        if e.get("run_id", "").lower() == run_id.lower():
            return e["run_id"], e.get("repo", repo), str(e.get("ticket", ticket))
    return run_id, repo, ticket


def _override(verdicts, key, inferred):
    """(verdict, validity, reason) from the caller's triage when it has one, else inferred."""
    v = (verdicts or {}).get(str(key))
    if not v:
        return inferred
    return (v.get("verdict") or inferred[0], v.get("validity") or inferred[1], v.get("reason") or inferred[2])


def _batch_key(findings):
    ids = sorted(str(e.get("comment_id") or f"{e.get('path')}:{e.get('line')}") for e in findings)
    return hashlib.sha1("\n".join(ids).encode()).hexdigest()[:12]


def plan_bot_pr(pr_data, existing, repo, live=False, verdicts=None):
    """Reconstruct bot review.finding and review.result events from fetched PR data.

    pr_data keys: number, branch, comments, reviews, threads, commit_files
      where commit_files is [(ts_str, set_of_paths)].
    live=True is the per-round emit: events are not marked backfill, `verdicts`
    ({comment_id or "path:line": {verdict, validity, reason}}) overrides what the
    thread implies, and the review.result covers only findings not yet logged.
    Returns (new_events, summary).
    """
    branch = pr_data["branch"]
    pr_num = pr_data["number"]
    run_id, canon_repo, ticket = resolve_run_identity(branch, repo, existing)
    summary = {"pr": pr_num, "branch": branch, "run_id": run_id, "copilot_comments": 0,
               "inline": 0, "review_body": 0, "unjudged": 0, "notes": []}
    if not run_id:
        summary["notes"].append("no ticket id in branch: skipped")
        return [], summary

    comments = pr_data.get("comments") or []
    reviews = pr_data.get("reviews") or []
    threads = pr_data.get("threads") or []
    commit_files = pr_data.get("commit_files") or []

    resolved_by_cid = {}
    thread_replies_by_cid = defaultdict(list)
    for th in threads:
        nodes = (th.get("comments") or {}).get("nodes") or []
        if not nodes:
            continue
        root_id = nodes[0].get("databaseId")
        if root_id is None:
            continue
        resolved_by_cid[root_id] = bool(th.get("isResolved"))
        thread_replies_by_cid[root_id].extend(nodes[1:])

    replies_by_parent = defaultdict(list)
    for c in comments:
        pid = c.get("in_reply_to_id")
        if pid is not None:
            replies_by_parent[pid].append(c)

    base = {"v": 1, "run_id": run_id, "repo": canon_repo, "ticket": ticket,
            "branch": branch, "source": "bot", "reviewer": "copilot"}
    if not live:
        base["backfill"] = True
    new = []

    for c in comments:
        login = (c.get("user") or {}).get("login") or ""
        if login not in _COPILOT_LOGINS or c.get("in_reply_to_id") is not None:
            continue
        cid = c["id"]
        path = c.get("path") or ""
        created_at = c.get("created_at") or ""
        replies = replies_by_parent.get(cid) or thread_replies_by_cid.get(cid) or []
        resolved = resolved_by_cid.get(cid, False)
        later_touched = any(ts > created_at and path in files for ts, files in commit_files)
        verdict, validity, reason = _override(verdicts, cid, infer_bot_verdict(replies, resolved, later_touched))
        ev = {
            **base,
            "ts": created_at,
            "event": "review.finding",
            "severity": parse_bot_severity(c.get("body")),
            "verdict": verdict,
            "validity": validity,
            "reason": reason,
            "path": path,
            "claim": clean_bot_claim(path, c.get("body")),
            "comment_id": cid,
            "sha": c.get("original_commit_id") or c.get("commit_id") or "",
        }
        line = c.get("original_line") or c.get("line")
        if line is not None:
            ev["line"] = line
        new.append(ev)
        summary["inline"] += 1

    for rv in reviews:
        login = (rv.get("user") or {}).get("login") or ""
        if login not in _COPILOT_LOGINS:
            continue
        submitted_at = rv.get("submitted_at") or ""
        rv_sha = rv.get("commit_id") or ""
        for item in parse_suppressed_review_body(rv.get("body")):
            path = item["path"]
            later_touched = any(ts > submitted_at and path in files for ts, files in commit_files)
            verdict, validity, reason = _override(
                verdicts, f"{path}:{item['line']}", infer_bot_verdict([], item["resolved"], later_touched))
            ev = {
                **base,
                "ts": submitted_at,
                "event": "review.finding",
                "severity": parse_bot_severity(item["text"]),
                "verdict": verdict,
                "validity": validity,
                "reason": reason,
                "path": path,
                "claim": clean_bot_claim(path, item["text"]),
                "sha": rv_sha,
            }
            if item["line"] is not None:
                ev["line"] = item["line"]
            new.append(ev)
            summary["review_body"] += 1

    summary["copilot_comments"] = summary["inline"] + summary["review_body"]
    if live:
        have = {event_id(e) for e in existing if e.get("source") == "bot"}
        new = [e for e in new if event_id(e) not in have]
    if live:
        judged = {str(k) for k in (verdicts or {})}
        summary["unjudged"] = sum(
            1 for e in new
            if str(e.get("comment_id") or f"{e.get('path')}:{e.get('line')}") not in judged)
    counts = Counter(e["verdict"] for e in new)
    result_logged = any(e.get("event") == "review.result" and e.get("source") == "bot"
                        and e.get("run_id") == run_id for e in existing)
    if new and (live or not result_logged):
        latest_ts = max((e["ts"] for e in new if e.get("ts")), default="")
        new.append({
            **{k: v for k, v in base.items() if k != "reviewer"},
            "ts": latest_ts,
            "event": "review.result",
            "fixed": counts["fixed"],
            "dismissed": counts["dismissed"],
            "deferred": counts["deferred"],
            "reviewers": "copilot",
            **({"batch": _batch_key(new)} if live else {}),
        })
    return new, summary


def _gh_json(args):
    r = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:3])} failed: {r.stderr.strip()}")
    return json.loads(r.stdout)


def resolve_repo_slug(repo=None):
    if repo:
        d = _gh_json(["repo", "view", repo, "--json", "nameWithOwner"])
    else:
        d = _gh_json(["repo", "view", "--json", "nameWithOwner"])
    return d["nameWithOwner"]


def fetch_pr_bot_data(number, repo, with_commit_files=True):
    owner, name = repo.split("/", 1)
    pr = _gh_json(["pr", "view", str(number), "--repo", repo, "--json", "number,headRefName"])
    comments = _gh_json(["api", f"repos/{owner}/{name}/pulls/{number}/comments", "--paginate"])
    reviews = _gh_json(["api", f"repos/{owner}/{name}/pulls/{number}/reviews", "--paginate"])
    gql_q = (
        "query($owner:String!,$name:String!,$num:Int!){"
        "repository(owner:$owner,name:$name){pullRequest(number:$num){"
        "reviewThreads(first:100){nodes{isResolved comments(first:20){nodes{databaseId body}}}}}}}"
    )
    gql = _gh_json(["api", "graphql", "-f", f"query={gql_q}", "-F", f"owner={owner}",
                    "-F", f"name={name}", "-F", f"num={number}"])
    threads = (((gql.get("data") or {}).get("repository") or {}).get("pullRequest") or {}).get("reviewThreads", {}).get("nodes") or []

    has_copilot = any(
        ((c.get("user") or {}).get("login") in _COPILOT_LOGINS and c.get("in_reply_to_id") is None)
        for c in comments
    ) or any(
        ((rv.get("user") or {}).get("login") in _COPILOT_LOGINS and parse_suppressed_review_body(rv.get("body")))
        for rv in reviews
    )
    commit_files = []
    if has_copilot and with_commit_files:
        pr_commits = _gh_json(["api", f"repos/{owner}/{name}/pulls/{number}/commits", "--paginate"])
        for cm in pr_commits:
            sha = cm.get("sha")
            ts = ((cm.get("commit") or {}).get("committer") or {}).get("date") or ""
            detail = _gh_json(["api", f"repos/{owner}/{name}/commits/{sha}"])
            files = {f.get("filename") for f in detail.get("files") or [] if f.get("filename")}
            commit_files.append((ts, files))
    return {
        "number": pr["number"],
        "branch": pr["headRefName"],
        "comments": comments,
        "reviews": reviews,
        "threads": threads,
        "commit_files": commit_files,
    }


def list_merged_prs_since(repo, since):
    prs = _gh_json(["pr", "list", "--repo", repo, "--state", "merged", "--limit", "1000",
                    "--json", "number,mergedAt"])
    return sorted(p["number"] for p in prs if (p.get("mergedAt") or "") >= since)


def format_bot_summary(s, written, skipped):
    notes = "".join(f" ({n})" for n in s["notes"])
    return (f"PR #{s['pr']} ({s['branch']} -> {s['run_id'] or 'none'}): "
            f"{s['copilot_comments']} copilot comments ({s['inline']} inline, {s['review_body']} body); "
            f"events written {written}, already present {skipped}{notes}")


def run_bot(args):
    repo = resolve_repo_slug(args.repo)
    pr_nums = list(args.pr)
    if args.since:
        for n in list_merged_prs_since(repo, args.since):
            if n not in pr_nums:
                pr_nums.append(n)
    if not pr_nums:
        print(f"No merged PRs found in {repo} since {args.since or 'always'}.")
        return 0
    existing = load_log(args.log)
    verdicts = None
    if args.verdicts:
        try:
            with open(args.verdicts) as fh:
                verdicts = {str(k): v for k, v in json.load(fh).items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError) as e:
            if not args.live:
                raise
            print(f"telemetry: verdicts file unreadable, inferring verdicts: {e}", file=sys.stderr)
    for n in pr_nums:
        try:
            pr_data = fetch_pr_bot_data(n, repo, with_commit_files=not args.live)
        except SystemExit as e:
            if not args.live:
                raise
            print(f"telemetry: bot findings for PR {n} not recorded: {e}", file=sys.stderr)
            continue
        new, summary = plan_bot_pr(pr_data, existing, repo, live=args.live, verdicts=verdicts)
        if summary["unjudged"]:
            print(f"telemetry: {summary['unjudged']} bot finding(s) on PR {n} have no verdicts entry; "
                  "verdicts inferred from the thread", file=sys.stderr)
        written, skipped = append_new(args.log, new, existing, args.dry_run)
        print(format_bot_summary(summary, written, skipped))
        if not args.dry_run and written:
            existing = load_log(args.log)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wf-backfill.sh", description=__doc__)
    ap.add_argument("--pr", action="append", default=[], type=int, help="PR number (repeatable)")
    ap.add_argument("--branch", action="append", default=[], help="branch name (repeatable)")
    ap.add_argument("--repo", help="owner/repo, to select events and PRs (default: current repo's PRs; any repo's events)")
    ap.add_argument("--git-dir", default=".", help="checkout holding the branch (default: cwd)")
    ap.add_argument("--log", default=os.environ.get("WF_TELEMETRY_LOG") or os.path.join(
        os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "workflow-telemetry", "events.jsonl"))
    ap.add_argument("--projects", default=None, help="transcripts root (default: WF_CLAUDE_PROJECTS or ~/.claude/projects)")
    ap.add_argument("--bot", action="store_true", help="backfill bot findings from GitHub PR reviews/comments")
    ap.add_argument("--since", help="backfill bot findings for merged PRs on/after YYYY-MM-DD (implies --bot)")
    ap.add_argument("--live", action="store_true",
                    help="per-round emit for an open PR (implies --bot): events are not marked backfill")
    ap.add_argument("--verdicts", help="JSON file {comment_id or path:line: {verdict, validity, reason}} overriding inference (--live)")
    ap.add_argument("--dry-run", action="store_true", help="report only; append nothing")
    args = ap.parse_args(argv)

    if args.since or args.live:
        args.bot = True
    if args.live and os.environ.get("WF_TELEMETRY") == "0":
        return 0
    if args.bot:
        try:
            return run_bot(args)
        except (SystemExit, OSError, ValueError) as e:
            if not args.live:
                raise
            print(f"telemetry: bot findings not recorded: {e}", file=sys.stderr)
            return 0

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
