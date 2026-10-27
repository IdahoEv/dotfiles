"""Summarize workflow telemetry: per-run and aggregate time, tokens, reviews, tests.

Reads the JSONL event log written by lib/telemetry.sh and, through wf_usage,
the Claude Code transcripts of the sessions those events name. Anything a
source didn't record is reported as unknown with the reason, never as zero.
"""

import argparse
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wf_usage  # noqa: E402

STAGES = ["PLAN", "WIP", "REVIEW", "REVIEWED", "MERGED", "DONE"]
TOKEN_KEYS = ["input", "output", "cache_read", "cache_write_5m", "cache_write_1h"]


def log_path():
    if os.environ.get("WF_TELEMETRY_LOG"):
        return os.environ["WF_TELEMETRY_LOG"]
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(state, "workflow-telemetry", "events.jsonl")


def load_events(path):
    events, bad = [], 0
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    e = None
                if not (isinstance(e, dict) and all(isinstance(e.get(k), str) and e[k] for k in ("ts", "run_id", "event"))):
                    bad += 1
                    continue
                e["_ts"] = wf_usage.parse_ts(e["ts"])
                if e["_ts"] is None:
                    bad += 1
                    continue
                events.append(e)
    except FileNotFoundError:
        pass
    events.sort(key=lambda e: e["_ts"])
    return events, bad


def fmt_dur(seconds):
    if seconds is None:
        return "unknown"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def fmt_tok(n):
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e3 else str(n)


def fmt_usd(x):
    return "unknown" if x is None else f"${x:.2f}"


class Run:
    def __init__(self, run_id, events, now, stale_hours, pricing, test_re):
        self.run_id = run_id
        self.events = events
        self.now = now
        self.gaps = []
        self.start = events[0]["_ts"]
        self.last_event = events[-1]["_ts"]
        self.status, self.status_reason = self._status(stale_hours)
        # A closed run ends at its last event. An unclosed one has no end
        # marker, so its sessions' usage is read up to now and the run ends at
        # whichever came last.
        closed = self.status in ("done", "merged")
        self.end = self.last_event if closed else now
        self.stages = self._stages()
        self.sessions = self._sessions()
        self._usage(pricing, test_re)
        if not closed:
            last_seen = max([self.last_event] + [t for ts in self.usage_ts.values() for t in ts])
            if self.status == "stalled" and now - last_seen <= timedelta(hours=stale_hours):
                self.status, self.status_reason = "open", ""
            self.end = now if self.status == "open" else last_seen
            self.stages = [(s, a, b if i + 1 < len(self.stages) else self.end)
                           for i, (s, a, b) in enumerate(self.stages)]
        self.sessions_spans = self._session_spans()
        self.reviews = self._reviews()
        self.failures = self._failures()

    def of(self, name):
        return [e for e in self.events if e["event"] == name]

    def _status(self, stale_hours):
        phases = {e.get("phase") for e in self.of("phase")}
        if "DONE" in phases:
            return "done", ""
        if "MERGED" in phases or any(e.get("verdict") == "ready" for e in self.of("finalize.check")):
            return "merged", ""
        # A session whose last word was a StopFailure, with nothing after it in the run.
        last_by_session = {}
        for e in self.events:
            if e.get("session_id"):
                last_by_session[e["session_id"]] = e
        failed = [e for e in last_by_session.values() if e["event"] == "session.fail"]
        if failed and failed[-1]["_ts"] >= self.last_event:
            return "interrupted", f"StopFailure ({failed[-1].get('error', 'unknown')})"
        if self.now - self.last_event > timedelta(hours=stale_hours):
            return "stalled", f"no events for {fmt_dur((self.now - self.last_event).total_seconds())}"
        return "open", ""

    def _stages(self):
        """[(stage, start, end)] from phase events; PLAN until the first one."""
        marks = [(self.start, "PLAN")]
        for e in self.of("phase"):
            if e.get("phase") in STAGES and e["phase"] != marks[-1][1]:
                marks.append((e["_ts"], e["phase"]))
        if not self.of("phase"):
            self.gaps.append("no phase events (non-background session, or agent-phase.sh never ran): all time counted as PLAN")
        spans = []
        for i, (t, stage) in enumerate(marks):
            spans.append((stage, t, marks[i + 1][0] if i + 1 < len(marks) else self.end))
        return spans

    def stage_at(self, ts):
        for stage, start, end in reversed(self.stages):
            if ts >= start:
                return stage
        return "PLAN"

    def _sessions(self):
        # ticket.start runs in the launching session (governor, /start), whose
        # tokens belong to other work; only sessions seen inside the run count.
        return sorted({e["session_id"] for e in self.events if e.get("session_id") and e["event"] != "ticket.start"})

    def _usage(self, pricing, test_re):
        self.tokens = defaultdict(lambda: defaultdict(int))  # (model, stage) -> key -> n
        self.cost = defaultdict(float)                     # stage -> usd
        self.cost_model = defaultdict(float)               # model -> usd
        self.unpriced = defaultdict(int)                   # model -> output tokens
        self.stage_unpriced = set()                        # stages with any unpriced usage
        self.by_agent = defaultdict(int)                   # agent_type -> output tokens
        self.tests = []
        self.usage_ts = defaultdict(list)                  # session -> [ts]
        seen = set()  # message ids across the run: a resumed session copies earlier messages
        lo, hi = self.start, self.end + timedelta(minutes=1)
        for sid in self.sessions:
            files = wf_usage.transcripts_for_session(sid)
            if not files:
                self.gaps.append(f"session {sid[:8]}: no transcript found; its tokens are unknown")
                continue
            for path, agent in files:
                for rec in wf_usage.read_usage(path, agent):
                    if rec["ts"] is None or not (lo <= rec["ts"] <= hi) or rec["id"] in seen:
                        continue
                    seen.add(rec["id"])
                    self.usage_ts[sid].append(rec["ts"])
                    stage = self.stage_at(rec["ts"])
                    bucket = self.tokens[(rec["model"], stage)]
                    for k in TOKEN_KEYS:
                        bucket[k] += rec[k]
                    bucket["messages"] += 1
                    usd = pricing.cost(rec) if pricing else None
                    if usd is None:
                        self.unpriced[rec["model"]] += rec["output"]
                        self.stage_unpriced.add(stage)
                    else:
                        self.cost[stage] += usd
                        self.cost_model[rec["model"]] += usd
                    self.by_agent[agent or "main"] += rec["output"]
                for t in wf_usage.read_tests(path, test_re):
                    if t["start"] and lo <= t["start"] <= hi:
                        t["stage"] = self.stage_at(t["start"])
                        self.tests.append(t)
        for model in self.unpriced:
            self.gaps.append(f"model {model}: not in pricing table; cost unknown")

    def _session_spans(self):
        spans = {}
        for sid in self.sessions:
            ts = [e["_ts"] for e in self.events if e.get("session_id") == sid] + self.usage_ts.get(sid, [])
            spans[sid] = (min(ts), max(ts))
        return spans

    def peak_parallel(self):
        edges = sorted([(a, 1) for a, _ in self.sessions_spans.values()] + [(b, -1) for _, b in self.sessions_spans.values()],
                       key=lambda x: (x[0], -x[1]))
        cur = peak = 0
        for _, d in edges:
            cur += d
            peak = max(peak, cur)
        return peak

    def _reviews(self):
        rounds = {e.get("round") for e in self.of("review.round") if e.get("state") == "end"}
        results = self.of("review.result")
        bot = [e for e in results if e.get("source") == "bot"]
        out = {"rounds": len(rounds), "bot_batches": len(bot),
               "fixed": None, "dismissed": None, "deferred": None, "reviewers": set(),
               "by_reviewer": defaultdict(lambda: defaultdict(int)),
               "dismissed_findings": []}
        for e in self.of("review.finding"):
            rv, verdict = e.get("reviewer", "unknown"), e.get("verdict", "unknown")
            if verdict not in ("fixed", "dismissed", "deferred"):
                continue
            counts = out["by_reviewer"][rv]
            for k in ("fixed", "dismissed", "deferred"):
                counts.setdefault(k, 0)
            counts[verdict] += 1
            if verdict == "dismissed":
                out["dismissed_findings"].append((rv, e.get("round"), e.get("reason")))
        if results:
            for k in ("fixed", "dismissed", "deferred"):
                vals = [e[k] for e in results if isinstance(e.get(k), int)]
                out[k] = sum(vals) if vals else None
            for e in results:
                out["reviewers"].update(r for r in str(e.get("reviewers", "")).split(",") if r)
            local_rounds = [e["round"] for e in results if isinstance(e.get("round"), int)]
            out["rounds"] = max([out["rounds"]] + local_rounds)
        elif rounds:
            self.gaps.append("review rounds ran but no review.result: findings unknown")
        if out["dismissed_findings"] and any(rsn is None for _, _, rsn in out["dismissed_findings"]):
            self.gaps.append("a dismissed review.finding has no reason: report shows 'reason unknown'")
        return out

    def _failures(self):
        return {
            "ticket_start_failed": sum(1 for e in self.of("ticket.start") if e.get("outcome") == "fail"),
            "pr_open_failed": sum(1 for e in self.of("pr.open") if e.get("outcome") == "fail"),
            "session_failures": len(self.of("session.fail")),
            "session_starts": len(self.of("session.start")),
        }

    def total_cost(self):
        return None if self.unpriced or not self.tokens else sum(self.cost.values())

    def as_dict(self):
        tok = defaultdict(lambda: defaultdict(int))
        for (model, stage), b in self.tokens.items():
            for k, v in b.items():
                tok[model][k] += v
        test_secs = [t["seconds"] for t in self.tests if t["seconds"] is not None]
        return {
            "run_id": self.run_id,
            "status": self.status,
            "status_reason": self.status_reason,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "wall_seconds": (self.end - self.start).total_seconds(),
            "stages": [{"stage": s, "seconds": (b - a).total_seconds()} for s, a, b in self.stages],
            "sessions": len(self.sessions),
            "peak_parallel_sessions": self.peak_parallel(),
            "session_seconds": sum((b - a).total_seconds() for a, b in self.sessions_spans.values()),
            "tokens_by_model": {m: dict(v) for m, v in tok.items()},
            "cost_by_stage_usd": {s: (None if s in self.stage_unpriced else self.cost.get(s, 0.0))
                                 for s in set(self.cost) | self.stage_unpriced},
            "cost_by_model_usd": {m: (None if m in self.unpriced else self.cost_model[m]) for m in tok},
            "cost_usd": self.total_cost(),
            "cost_is_estimate": True,
            "output_tokens_by_agent": dict(self.by_agent),
            "reviews": {**self.reviews, "reviewers": sorted(self.reviews["reviewers"]),
                        "by_reviewer": {r: dict(v) for r, v in self.reviews["by_reviewer"].items()},
                        "dismissed_findings": [{"reviewer": rv, "round": rd, "reason": rs}
                                      for rv, rd, rs in self.reviews["dismissed_findings"]]},
            "tests": {
                "runs": len(self.tests),
                "failed": sum(1 for t in self.tests if not t["ok"]),
                "reruns": len(self.tests) - len({t["key"] for t in self.tests}),
                "seconds": sum(test_secs),
            },
            "failures": self.failures,
            "gaps": self.gaps,
        }


def print_run(r, out):
    d = r.as_dict()
    w = out.write
    w(f"== {d['run_id']}  [{d['status']}{': ' + d['status_reason'] if d['status_reason'] else ''}]\n")
    w(f"wall {fmt_dur(d['wall_seconds'])}  ({d['start'][:16]} → {d['end'][:16]})\n")
    w(f"sessions {d['sessions']}, peak parallel {d['peak_parallel_sessions']}, "
      f"summed session time {fmt_dur(d['session_seconds'])}\n")
    stage_secs = defaultdict(float)
    for s in d["stages"]:
        stage_secs[s["stage"]] += s["seconds"]
    w("\nstage      elapsed   est. cost\n")
    for s in STAGES:
        if s in stage_secs or s in r.cost or s in r.stage_unpriced:
            cost = "unknown" if (not r.tokens or s in r.stage_unpriced) else fmt_usd(r.cost.get(s))
            w(f"{s:<10} {fmt_dur(stage_secs.get(s)):>8}   {cost:>9}\n")
    if d["tokens_by_model"]:
        w("\nmodel                input   output  cache-rd  cache-wr  est. cost\n")
        for model, t in sorted(d["tokens_by_model"].items()):
            w(f"{model:<18} {fmt_tok(t['input']):>7} {fmt_tok(t['output']):>8} {fmt_tok(t['cache_read']):>9} "
              f"{fmt_tok(t['cache_write_5m'] + t['cache_write_1h']):>9}  {fmt_usd(d['cost_by_model_usd'].get(model)):>9}\n")
        w(f"total est. cost {fmt_usd(d['cost_usd'])}\n")
    else:
        w("\ntokens: unknown (no transcripts matched this run's sessions)\n")
    rv = d["reviews"]
    if rv["rounds"] or rv["fixed"] is not None:
        f = lambda k: "?" if rv[k] is None else rv[k]  # noqa: E731
        w(f"\nreview: {rv['rounds']} local round(s), {rv['bot_batches']} bot batch(es); fixed {f('fixed')} / dismissed {f('dismissed')} / deferred {f('deferred')}"
          f"{'  reviewers: ' + ', '.join(rv['reviewers']) if rv['reviewers'] else ''}\n")
    if r.reviews["by_reviewer"]:
        w("findings by reviewer:\n")
        for name, counts in sorted(r.reviews["by_reviewer"].items()):
            w(f"  {name}: {counts.get('fixed', 0)} fixed / {counts.get('dismissed', 0)} dismissed / {counts.get('deferred', 0)} deferred\n")
        if r.reviews["dismissed_findings"]:
            w("  dismissed:\n")
            for rv_name, rnd, reason in r.reviews["dismissed_findings"]:
                rr = f"R{rnd}" if isinstance(rnd, int) else "R?"
                w(f"    {reason or 'reason unknown'} ({rv_name}, {rr})\n")
    t = d["tests"]
    w(f"tests: {t['runs']} run(s), {t['failed']} failed, {t['reruns']} rerun(s), {fmt_dur(t['seconds'])}\n")
    fl = d["failures"]
    if any(fl[k] for k in ("ticket_start_failed", "pr_open_failed", "session_failures")):
        w(f"failures: start {fl['ticket_start_failed']}, pr.open {fl['pr_open_failed']}, session {fl['session_failures']}\n")
    for g in d["gaps"]:
        w(f"  ! {g}\n")
    w("\n")


def print_aggregate(runs, out, min_n=3):
    w = out.write
    w(f"{'run':<34} {'status':<11} {'wall':>8} {'est. cost':>9} {'rounds':>6} {'tests':>5}\n")
    for r in runs:
        d = r.as_dict()
        w(f"{d['run_id'][:34]:<34} {d['status']:<11} {fmt_dur(d['wall_seconds']):>8} "
          f"{fmt_usd(d['cost_usd']):>9} {d['reviews']['rounds']:>6} {d['tests']['runs']:>5}\n")
    finished = [r.as_dict() for r in runs if r.status in ("merged", "done")]
    w(f"\n{len(runs)} run(s), {len(finished)} merged/done, "
      f"{sum(1 for r in runs if r.status in ('interrupted', 'stalled'))} interrupted/stalled\n")
    if len(finished) < min_n:
        w(f"per-ticket medians need ≥{min_n} merged runs; have {len(finished)}\n")
        return
    priced = [d["cost_usd"] for d in finished if d["cost_usd"] is not None]
    w(f"median wall per merged ticket: {fmt_dur(statistics.median(d['wall_seconds'] for d in finished))}\n")
    w(f"median est. cost per merged ticket: "
      f"{fmt_usd(statistics.median(priced)) if priced else 'unknown'} ({len(priced)}/{len(finished)} fully priced)\n")
    w(f"median review rounds: {statistics.median(d['reviews']['rounds'] for d in finished)}\n")


def prune(path, days, now):
    """Drop events older than <days>. Lines appended while pruning are carried over."""
    if not os.path.exists(path):
        return 0
    lock = path + ".lock"
    try:
        os.mkdir(lock)
    except FileExistsError:
        raise SystemExit(f"wf-report: {lock} exists; another prune is running (remove it if stale)")
    try:
        return _prune(path, days, now)
    finally:
        os.rmdir(lock)


def _prune(path, days, now):
    cutoff = now - timedelta(days=days)
    with open(path, "rb") as fh:
        data = fh.read()
    kept = []
    for line in data.splitlines(keepends=True):
        try:
            ts = wf_usage.parse_ts(json.loads(line)["ts"])
        except (ValueError, KeyError, TypeError):
            continue
        if ts and ts >= cutoff:
            kept.append(line)
    tmp = path + ".prune"
    with open(tmp, "wb") as fh:
        fh.writelines(kept)
        with open(path, "rb") as src:
            src.seek(len(data))
            fh.write(src.read())
    os.replace(tmp, path)
    return len(data.splitlines()) - len(kept)


def parse_since(s, now):
    m = re.fullmatch(r"(\d+)([dhw])", s or "")
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return now - {"d": timedelta(days=n), "h": timedelta(hours=n), "w": timedelta(weeks=n)}[unit]
    ts = wf_usage.parse_ts(s if s and "T" in s else f"{s}T00:00:00+00:00")
    if ts is None:
        raise SystemExit(f"wf-report: --since wants Nd/Nh/Nw or YYYY-MM-DD, got '{s}'")
    return ts


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wf-report.sh", description=__doc__)
    ap.add_argument("--run", help="one run id, e.g. owner/repo#40 or sc-12345")
    ap.add_argument("--since", default="14d", help="Nd, Nh, Nw or YYYY-MM-DD (default 14d)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--detail", action="store_true", help="per-run detail after the aggregate table")
    ap.add_argument("--stale-hours", type=float, default=24)
    ap.add_argument("--prune", type=int, metavar="DAYS", help="delete events older than DAYS and exit")
    ap.add_argument("--log", default=log_path())
    ap.add_argument("--pricing", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "model-pricing.json"))
    ap.add_argument("--test-re", default=os.environ.get("WF_TEST_RE", wf_usage.DEFAULT_TEST_RE))
    ap.add_argument("--now", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    now = wf_usage.parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    if a.prune is not None:
        print(f"pruned {prune(a.log, a.prune, now)} event(s)")
        return 0
    try:
        pricing = wf_usage.Pricing(a.pricing)
    except (OSError, ValueError, KeyError):
        pricing = None
        print(f"wf-report: pricing table unreadable ({a.pricing}); costs unknown", file=sys.stderr)

    events, bad = load_events(a.log)
    by_run = defaultdict(list)
    for e in events:
        by_run[e["run_id"]].append(e)
    if a.run:
        ids = [a.run] if a.run in by_run else []
    else:
        since = parse_since(a.since, now)
        ids = [rid for rid, evs in by_run.items() if evs[-1]["_ts"] >= since]
    runs = [Run(rid, by_run[rid], now, a.stale_hours, pricing, a.test_re) for rid in ids]
    runs.sort(key=lambda r: r.start)

    if a.json:
        json.dump({"log": a.log, "unparseable_lines": bad, "runs": [r.as_dict() for r in runs]}, sys.stdout, indent=2, default=str)
        print()
        return 0
    if not runs:
        print(f"no runs{' matching ' + a.run if a.run else ''} in {a.log}")
        return 1 if a.run else 0
    if bad:
        print(f"! {bad} unparseable line(s) in {a.log} skipped\n")
    if a.run:
        print_run(runs[0], sys.stdout)
    else:
        print_aggregate(runs, sys.stdout)
        if a.detail:
            print()
            for r in runs:
                print_run(r, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
