"""Token usage across every Claude Code session, independent of ticket telemetry.

Tokens are measured and always summed in full. The weighted column applies the
list-price table as a relative-weight proxy for quota burn; a model missing from
the table contributes tokens but no weight, and marks its group's weight partial.
"""

import os
import re
import sys
from collections import defaultdict
from datetime import timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wf_usage  # noqa: E402

VIEWS = ["day", "ticket", "stage", "agent", "model", "type"]
TOKEN_KEYS = ["input", "output", "cache_read"]
NO_VALUE = "—"
WEIGHT_HEADER = "weighted (list-price proxy, not billing)"
_WORKTREE_RE = re.compile(r"(?:\d+|[a-z]+-\d+)-[a-z]")


def session_type(cwd, in_run):
    """ticket worktree | governor/jobs | other"""
    path = cwd or ""
    if "/.claude/jobs/" in path or "/governor" in path or "-claude-jobs-" in path:
        return "governor/jobs"
    if in_run or _WORKTREE_RE.match(os.path.basename(path)):
        return "ticket"
    return "other"


class Group:
    def __init__(self):
        self.messages = 0
        self.tok = defaultdict(int)
        self.weight = 0.0
        self.priced = 0
        self.output_by_model = defaultdict(int)
        self.first = self.last = None

    def add(self, rec, usd):
        self.messages += 1
        for k in TOKEN_KEYS:
            self.tok[k] += rec[k]
        self.tok["cache_write"] += rec["cache_write_5m"] + rec["cache_write_1h"]
        self.output_by_model[rec["model"]] += rec["output"]
        if usd is not None:
            self.weight += usd
            self.priced += 1
        self.first = rec["ts"] if self.first is None else min(self.first, rec["ts"])
        self.last = rec["ts"] if self.last is None else max(self.last, rec["ts"])

    def weighted(self):
        """(value or None, complete)"""
        if not self.priced:
            return None, False
        return self.weight, self.priced == self.messages

    def top_model(self):
        return max(self.output_by_model, key=self.output_by_model.get)

    def as_dict(self):
        w, complete = self.weighted()
        return {"messages": self.messages, **{k: self.tok[k] for k in TOKEN_KEYS + ["cache_write"]},
                "weighted": w, "weighted_complete": complete}


def collect(root, runs_by_session, runs, since, now, pricing):
    """[(rec, tags)] for every deduplicated message in [since, now]."""
    out, seen, cwds = [], set(), {}
    for path, sid, agent in wf_usage.all_transcripts(root, since):
        if agent is None:
            cwds[sid] = wf_usage.session_cwd(path)
    for path, sid, agent in wf_usage.all_transcripts(root, since):
        cwd = cwds.get(sid)
        run = runs.get(runs_by_session.get(sid))
        for rec in wf_usage.read_usage(path, agent):
            if rec["ts"] is None or not (since <= rec["ts"] <= now) or rec["id"] in seen:
                continue
            seen.add(rec["id"])
            if run:
                ticket, stage = run.run_id, run.stage_at(rec["ts"])
            elif _WORKTREE_RE.match(os.path.basename(cwd or "")):
                ticket, stage = os.path.basename(cwd), NO_VALUE
            else:
                ticket, stage = NO_VALUE, NO_VALUE
            out.append((rec, {
                "session": sid, "cwd": cwd, "day": rec["ts"].astimezone(timezone.utc).date().isoformat(),
                "ticket": ticket, "stage": stage, "agent": agent or "main", "model": rec["model"],
                "type": session_type(cwd, run is not None),
                "usd": pricing.cost(rec) if pricing else None,
            }))
    return out


def group_by(items, key):
    groups = defaultdict(Group)
    for rec, tags in items:
        groups[tags[key]].add(rec, tags["usd"])
    return groups


def top_sessions(items, n):
    groups, cwd = defaultdict(Group), {}
    for rec, tags in items:
        groups[tags["session"]].add(rec, tags["usd"])
        cwd[tags["session"]] = tags["cwd"]
    ranked = sorted(groups.items(), key=lambda kv: -kv[1].tok["output"])[:n]
    return [{"session": sid, "project_dir": cwd[sid] or NO_VALUE, "span_start": g.first.isoformat(),
             "span_end": g.last.isoformat(), "top_model": g.top_model(), **g.as_dict()} for sid, g in ranked]


def build(items, views, top):
    result = {"totals": None, "views": {}}
    total = Group()
    for rec, tags in items:
        total.add(rec, tags["usd"])
    result["totals"] = total.as_dict()
    for v in views:
        if v == "sessions":
            continue
        groups = group_by(items, v)
        order = sorted(groups) if v == "day" else sorted(groups, key=lambda k: -groups[k].tok["output"])
        result["views"][v] = [{"key": k, **groups[k].as_dict()} for k in order]
    if "sessions" in views:
        result["top_sessions"] = top_sessions(items, top)
    return result


def _tok(n):
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e3 else str(n)


def _weight(row):
    if row["weighted"] is None:
        return "n/a"
    return f"{row['weighted']:.2f}" + ("" if row["weighted_complete"] else "*")


def render(result, out):
    w = out.write
    w(f"tokens per message are measured; '{WEIGHT_HEADER}' is n/a for models missing from the price table, * = partial\n")
    for view, rows in result["views"].items():
        kw = min(max([len(str(r["key"])) for r in rows] + [len(view)]), 56)
        w(f"\nby {view}\n{view:<{kw}} {'msgs':>6} {'input':>8} {'output':>8} {'cache-rd':>9} {'cache-wr':>9}  weighted\n")
        for r in rows + [{"key": "total", **result["totals"]}]:
            w(f"{str(r['key'])[:kw]:<{kw}} {r['messages']:>6} {_tok(r['input']):>8} {_tok(r['output']):>8} "
              f"{_tok(r['cache_read']):>9} {_tok(r['cache_write']):>9}  {_weight(r)}\n")
    if "top_sessions" in result:
        w(f"\ntop sessions by output tokens\n{'session':<10} {'msgs':>5} {'input':>8} {'output':>8} {'cache-rd':>9} {'cache-wr':>9}  "
          f"{'span':<12} {'top model':<40} project dir\n")
        for r in result["top_sessions"]:
            span = f"{r['span_start'][5:16]}→{r['span_end'][11:16]}" if r["span_start"][:10] == r["span_end"][:10] \
                else f"{r['span_start'][5:10]}→{r['span_end'][5:10]}"
            w(f"{r['session'][:8]:<10} {r['messages']:>5} {_tok(r['input']):>8} {_tok(r['output']):>8} "
              f"{_tok(r['cache_read']):>9} {_tok(r['cache_write']):>9}  {span:<12} {r['top_model'][:40]:<40} {r['project_dir']}\n")
