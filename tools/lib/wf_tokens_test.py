"""Tests for wf_tokens and `wf_report --usage`: all-session token breakdowns.

    python3 -m unittest tools/lib/wf_tokens_test.py

Transcripts are synthetic, written per test into a temp projects dir.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wf_report  # noqa: E402

NOW = "2026-10-26T00:00:00Z"
WORKTREE = "/home/u/dev/acme/7-add-widget"
JOBS = "/home/u/.claude/jobs/abc123/tmp"
GOVERNOR = "/home/u/dev/acme/.claude/worktrees/governor-context"
OTHER = "/home/u/notes"
FW = "fw-model-a"


def assistant(ts, mid, model="claude-opus-5-5", inp=100, out=1000, read=0, write=0, cwd=None):
    usage = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": write, "cache_creation": {"ephemeral_1h_input_tokens": 0}}
    e = {"type": "assistant", "timestamp": ts, "message": {"id": mid, "model": model, "usage": usage,
                                                           "content": [{"type": "text", "text": "SECRET PROMPT TEXT"}]}}
    if cwd:
        e["cwd"] = cwd
    return e


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.projects = os.path.join(self.root, "projects")
        os.environ["WF_CLAUDE_PROJECTS"] = self.projects
        self.addCleanup(os.environ.pop, "WF_CLAUDE_PROJECTS", None)
        self.events = os.path.join(self.root, "events.jsonl")
        open(self.events, "w").close()
        self.pricing = os.path.join(self.root, "pricing.json")
        self.write_pricing({})

    def write_pricing(self, extra):
        base = {"as_of": "2026-10-06", "cache_write_5m_multiplier": 1.25, "cache_write_1h_multiplier": 2.0,
                "models": {"claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.2},
                           "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.2}, **extra}}
        with open(self.pricing, "w") as fh:
            json.dump(base, fh)

    def write_events(self, *events):
        with open(self.events, "w") as fh:
            for e in events:
                fh.write(json.dumps({"v": 1, **e}) + "\n")

    def transcript(self, session, entries, agent=None, project="-p"):
        d = os.path.join(self.projects, project)
        if agent:
            d = os.path.join(d, session, "subagents")
            path = os.path.join(d, f"agent-{agent}.jsonl")
        else:
            path = os.path.join(d, session + ".jsonl")
        os.makedirs(d, exist_ok=True)
        with open(path, "w") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        if agent:
            with open(path[:-6] + ".meta.json", "w") as fh:
                json.dump({"agentType": agent}, fh)

    def usage(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = wf_report.main(["--usage", "--json", "--log", self.events, "--pricing", self.pricing,
                                 "--now", NOW, "--since", "30d", *args])
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())

    def rows(self, result, view):
        return {r["key"]: r for r in result["views"][view]}


class Breakdowns(UsageTest):
    def test_mixed_backends_and_unpriced_model_keep_token_totals(self):
        self.transcript("s1", [
            assistant("2026-10-20T09:00:00Z", "a", cwd=OTHER),
            assistant("2026-10-20T09:01:00Z", "b", model=FW, inp=500, out=2000, read=7000),
        ])
        r = self.usage()
        self.assertEqual((r["totals"]["input"], r["totals"]["output"], r["totals"]["cache_read"]), (600, 3000, 7000))
        models = self.rows(r, "model")
        self.assertIsNone(models[FW]["weighted"])
        self.assertAlmostEqual(models["claude-opus-5-5"]["weighted"], (100 * 4 + 1000 * 20) / 1e6)
        self.assertTrue(models["claude-opus-5-5"]["weighted_complete"])
        self.assertAlmostEqual(r["totals"]["weighted"], models["claude-opus-5-5"]["weighted"])
        self.assertFalse(r["totals"]["weighted_complete"], "unpriced usage marks the total partial, not blank")

    def test_optional_rate_for_non_anthropic_model_gives_weighted_total(self):
        self.write_pricing({FW: {"input": 0.5, "output": 2.0, "cache_read": 0.1,
                                 "source": "owner-supplied", "as_of": "2026-10-30"}})
        self.transcript("s1", [assistant("2026-10-20T09:00:00Z", "a", model=FW, inp=1_000_000, out=0)])
        self.assertAlmostEqual(self.usage()["totals"]["weighted"], 0.5)
        self.assertTrue(self.usage()["totals"]["weighted_complete"])

    def test_session_types(self):
        for sid, cwd in [("t", WORKTREE), ("j", JOBS), ("g", GOVERNOR), ("o", OTHER)]:
            self.transcript(sid, [assistant("2026-10-20T09:00:00Z", "m-" + sid, cwd=cwd)])
        types = self.rows(self.usage(), "type")
        self.assertEqual({k: v["messages"] for k, v in types.items()},
                         {"ticket": 1, "governor/jobs": 2, "other": 1})

    def test_governor_substring_in_repo_name_is_not_governor(self):
        self.transcript("a", [assistant("2026-10-20T09:00:00Z", "m-a", cwd="/home/u/dev/governor-app/7-x")])
        self.assertEqual(set(self.rows(self.usage(), "type")), {"ticket"})

    def test_subagent_keeps_cwd_when_main_transcript_is_outside_window(self):
        self.transcript("s1", [assistant("2026-01-01T09:00:00Z", "a", cwd=WORKTREE)])
        old = os.path.join(self.projects, "-p", "s1.jsonl")
        os.utime(old, (0, 0))
        self.transcript("s1", [assistant("2026-10-20T09:00:00Z", "b")], agent="Explore")
        self.assertEqual(set(self.rows(self.usage(), "type")), {"ticket"})

    def test_worktree_name_is_ticket_without_telemetry(self):
        self.transcript("s1", [assistant("2026-10-20T09:00:00Z", "a", cwd=WORKTREE)])
        r = self.usage()
        self.assertEqual(set(self.rows(r, "ticket")), {"7-add-widget"})
        self.assertEqual(set(self.rows(r, "stage")), {"—"})

    def test_unreadable_pricing_keeps_tokens_and_blanks_weight(self):
        self.transcript("s1", [assistant("2026-10-20T09:00:00Z", "a", out=42)])
        self.pricing = os.path.join(self.root, "missing.json")
        r = self.usage()
        self.assertEqual(r["totals"]["output"], 42)
        self.assertIsNone(r["totals"]["weighted"])

    def test_agent_type_split(self):
        self.transcript("s1", [assistant("2026-10-20T09:00:00Z", "a", out=100)])
        self.transcript("s1", [assistant("2026-10-20T09:01:00Z", "b", out=200)], agent="correctness-reviewer")
        self.transcript("s1", [assistant("2026-10-20T09:02:00Z", "c", out=400)], agent="robustness-reviewer")
        agents = self.rows(self.usage(), "agent")
        self.assertEqual({k: v["output"] for k, v in agents.items()},
                         {"main": 100, "correctness-reviewer": 200, "robustness-reviewer": 400})

    def test_ticket_and_stage_from_telemetry(self):
        self.write_events(
            {"ts": "2026-10-20T09:00:05.000Z", "event": "session.start", "run_id": "acme/w#7", "session_id": "s1"},
            {"ts": "2026-10-20T09:10:00.000Z", "event": "phase", "run_id": "acme/w#7", "session_id": "s1", "phase": "WIP"},
            {"ts": "2026-10-20T09:30:00.000Z", "event": "phase", "run_id": "acme/w#7", "session_id": "s1", "phase": "DONE"})
        self.transcript("s1", [assistant("2026-10-20T09:05:00Z", "a", out=1), assistant("2026-10-20T09:20:00Z", "b", out=10)])
        self.transcript("s2", [assistant("2026-10-20T09:20:00Z", "c", out=100)], project="-q")
        r = self.usage()
        self.assertEqual({k: v["output"] for k, v in self.rows(r, "ticket").items()}, {"acme/w#7": 11, "—": 100})
        self.assertEqual({k: v["output"] for k, v in self.rows(r, "stage").items()}, {"PLAN": 1, "WIP": 10, "—": 100})

    def test_days_dedup_and_window(self):
        dup = assistant("2026-10-20T09:00:00Z", "same")
        self.transcript("s1", [dup, assistant("2026-10-21T09:00:00Z", "b")])
        self.transcript("s1-resumed", [dup])
        self.transcript("old", [assistant("2026-01-01T09:00:00Z", "z")])
        r = self.usage()
        self.assertEqual({k: v["messages"] for k, v in self.rows(r, "day").items()},
                         {"2026-10-20": 1, "2026-10-21": 1})

    def test_breakdowns_sum_to_total(self):
        self.transcript("s1", [assistant("2026-10-20T09:00:00Z", "a", cwd=OTHER),
                               assistant("2026-10-21T09:00:00Z", "b", model=FW)])
        r = self.usage()
        for view, rows in r["views"].items():
            self.assertEqual(sum(x["output"] for x in rows), r["totals"]["output"], view)


class TopSessions(UsageTest):
    def test_ranked_by_output_with_span_and_top_model_and_no_content(self):
        self.transcript("big", [assistant("2026-10-20T09:00:00Z", "a", out=500, cwd=WORKTREE),
                                assistant("2026-10-20T10:00:00Z", "b", model=FW, out=5000, cwd=WORKTREE)])
        self.transcript("big", [assistant("2026-10-20T09:30:00Z", "c", out=100)], agent="Explore")
        self.transcript("small", [assistant("2026-10-20T09:00:00Z", "d", out=50, cwd=OTHER)])
        r = self.usage("--by", "sessions", "--top", "1")
        self.assertEqual(r["views"], {})
        (top,) = r["top_sessions"]
        self.assertEqual((top["session"], top["messages"], top["output"], top["top_model"]), ("big", 3, 5600, FW))
        self.assertEqual((top["span_start"][:16], top["span_end"][:16]), ("2026-10-20T09:00", "2026-10-20T10:00"))
        self.assertEqual(top["project_dir"], WORKTREE)
        self.assertNotIn("SECRET", json.dumps(r))

    def test_non_positive_top_is_rejected(self):
        for bad in ("0", "-1"):
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                wf_report.main(["--usage", "--top", bad, "--log", self.events])

    def test_usage_rejects_run_and_detail(self):
        for flag in (["--run", "x"], ["--detail"]):
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                wf_report.main(["--usage", "--log", self.events, *flag])

    def test_partial_weight_is_starred_in_text(self):
        self.transcript("s1", [assistant("2026-10-20T09:00:00Z", "a", cwd=OTHER),
                               assistant("2026-10-20T09:01:00Z", "b", model=FW)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--usage", "--by", "day", "--log", self.events, "--pricing", self.pricing,
                            "--now", NOW, "--since", "30d"])
        self.assertRegex(buf.getvalue(), r"\d\.\d+\*")

    def test_text_output_has_labelled_weighted_column_and_no_content(self):
        self.transcript("s1", [assistant("2026-10-20T09:00:00Z", "a", model=FW, cwd=OTHER)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--usage", "--log", self.events, "--pricing", self.pricing, "--now", NOW, "--since", "30d"])
        text = buf.getvalue()
        self.assertIn("list-price proxy", text)
        self.assertIn("n/a", text)
        self.assertNotIn("SECRET", text)


if __name__ == "__main__":
    unittest.main()
