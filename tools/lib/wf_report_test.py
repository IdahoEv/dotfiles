"""Tests for wf_usage and wf_report: aggregation, partial runs, unknown usage.

    python3 -m unittest tools/lib/wf_report_test.py

Event fixtures are in fixtures/telemetry/events.jsonl; transcripts are written
per test into a temp projects dir so each case states the usage it relies on.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wf_report  # noqa: E402
import wf_usage  # noqa: E402

EVENTS = os.path.join(HERE, "fixtures", "telemetry", "events.jsonl")
NOW = "2026-10-26T00:00:00Z"


def assistant(ts, mid, model="claude-opus-5-5", inp=100, out=1000, read=0, write=0, write_1h=0):
    usage = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": write, "cache_creation": {"ephemeral_1h_input_tokens": write_1h}}
    return {"type": "assistant", "timestamp": ts, "message": {"id": mid, "model": model, "usage": usage}}


def bash_call(ts, tid, cmd):
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": "m-" + tid, "content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}}


def bash_result(ts, tid, error=False):
    return {"type": "user", "timestamp": ts,
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": error, "content": "x"}]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        os.environ["WF_CLAUDE_PROJECTS"] = os.path.join(self.root, "projects")
        self.addCleanup(os.environ.pop, "WF_CLAUDE_PROJECTS", None)

    def transcript(self, session, entries, agent=None):
        d = os.path.join(self.root, "projects", "-repo")
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

    def report(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = wf_report.main(["--log", EVENTS, "--now", NOW, "--json", "--since", "30d", *args])
        self.assertEqual(rc, 0)
        return {r["run_id"]: r for r in json.loads(buf.getvalue())["runs"]}


class UsageAdapter(Base):
    def test_streamed_chunks_counted_once(self):
        self.transcript("s", [assistant("2026-10-20T09:00:00Z", "m1")] * 3 + [assistant("2026-10-20T09:01:00Z", "m2")])
        recs = list(wf_usage.read_usage(wf_usage.transcripts_for_session("s")[0][0]))
        self.assertEqual([r["id"] for r in recs], ["m1", "m2"])

    def test_cache_write_split_by_ttl(self):
        self.transcript("s", [assistant("2026-10-20T09:00:00Z", "m1", write=1000, write_1h=400)])
        rec = next(wf_usage.read_usage(wf_usage.transcripts_for_session("s")[0][0]))
        self.assertEqual((rec["cache_write_5m"], rec["cache_write_1h"]), (600, 400))

    def test_subagents_found_with_type(self):
        self.transcript("s", [])
        self.transcript("s", [], agent="correctness-reviewer")
        self.assertEqual([a for _, a in wf_usage.transcripts_for_session("s")], [None, "correctness-reviewer"])

    def test_session_id_cannot_escape_projects_dir(self):
        self.assertEqual(wf_usage.transcripts_for_session("../../etc"), [])

    def test_tests_timed_and_command_not_returned(self):
        self.transcript("s", [
            bash_call("2026-10-20T09:00:00Z", "t1", "FOO=1 pytest -q secret_name"),
            bash_result("2026-10-20T09:00:30Z", "t1", error=True),
            bash_call("2026-10-20T09:01:00Z", "t2", "grep pytest notes.md"),
            bash_result("2026-10-20T09:01:01Z", "t2"),
        ])
        tests = list(wf_usage.read_tests(wf_usage.transcripts_for_session("s")[0][0]))
        self.assertEqual(len(tests), 1)
        self.assertEqual((tests[0]["seconds"], tests[0]["ok"]), (30.0, False))
        self.assertNotIn("secret_name", json.dumps(tests, default=str))


class PricingTest(unittest.TestCase):
    def setUp(self):
        self.p = wf_usage.Pricing(os.path.join(HERE, "model-pricing.json"))

    def rec(self, **kw):
        base = {"model": "claude-opus-5-5", "input": 0, "output": 0, "cache_read": 0,
                "cache_write_5m": 0, "cache_write_1h": 0, "speed": None}
        return {**base, **kw}

    def test_components(self):
        self.assertAlmostEqual(self.p.cost(self.rec(input=1_000_000)), 4.0)
        self.assertAlmostEqual(self.p.cost(self.rec(output=1_000_000)), 20.0)
        self.assertAlmostEqual(self.p.cost(self.rec(cache_read=1_000_000)), 0.2)
        self.assertAlmostEqual(self.p.cost(self.rec(cache_write_5m=1_000_000)), 5.0)
        self.assertAlmostEqual(self.p.cost(self.rec(cache_write_1h=1_000_000)), 8.0)

    def test_fast_mode(self):
        self.assertAlmostEqual(self.p.cost(self.rec(output=1_000_000, speed="fast")), 40.0)

    def test_unknown_model_is_none_not_zero(self):
        self.assertIsNone(self.p.cost(self.rec(model="glm-5p3", output=10)))


class Report(Base):
    def test_complete_multi_review_run(self):
        self.transcript("s-main", [
            assistant("2026-10-20T09:05:00Z", "a"),                       # PLAN
            assistant("2026-10-20T09:20:00Z", "b", out=2000),             # WIP
            bash_call("2026-10-20T09:21:00Z", "t1", "./x.test.sh"),
            bash_result("2026-10-20T09:21:10Z", "t1", error=True),
            bash_call("2026-10-20T09:22:00Z", "t2", "./x.test.sh"),
            bash_result("2026-10-20T09:22:10Z", "t2"),
        ])
        self.transcript("s-main", [assistant("2026-10-20T09:35:00Z", "c", model="claude-sonnet-5-5")], agent="correctness-reviewer")
        r = self.report()["acme/w#1"]
        self.assertEqual(r["status"], "done")
        self.assertEqual([s["stage"] for s in r["stages"]], ["PLAN", "WIP", "REVIEW", "REVIEWED", "MERGED", "DONE"])
        self.assertEqual(r["wall_seconds"], 81 * 60)
        self.assertEqual(r["sessions"], 1, "launcher session of ticket.start is excluded")
        self.assertEqual(r["reviews"]["rounds"], 2)
        self.assertEqual((r["reviews"]["fixed"], r["reviews"]["dismissed"], r["reviews"]["deferred"]), (3, 1, 1))
        self.assertEqual(r["tests"], {"runs": 2, "failed": 1, "reruns": 1, "seconds": 20.0})
        self.assertEqual(r["failures"]["pr_open_failed"], 1)
        self.assertEqual(r["tokens_by_model"]["claude-opus-5-5"]["output"], 3000)
        self.assertEqual(r["output_tokens_by_agent"], {"main": 3000, "correctness-reviewer": 1000})
        self.assertAlmostEqual(r["cost_by_stage_usd"]["PLAN"], (100 * 4 + 1000 * 20) / 1e6)
        self.assertIsNotNone(r["cost_usd"])
        self.assertEqual(r["gaps"], [])

    def test_interrupted_run_is_not_success(self):
        self.transcript("s-int", [assistant("2026-10-20T09:10:00Z", "a")])
        r = self.report()["sc-9"]
        self.assertEqual(r["status"], "interrupted")
        self.assertIn("rate_limit", r["status_reason"])

    def test_partial_run_without_phases_is_flagged(self):
        self.transcript("s-nophase", [assistant("2026-10-20T11:01:00Z", "a")])
        r = self.report()["acme/w#2"]
        self.assertEqual(r["status"], "stalled")
        self.assertTrue(any("no phase events" in g for g in r["gaps"]))
        self.assertEqual(r["wall_seconds"], 60, "unclosed run ends at its last usage")

    def test_missing_transcript_means_unknown_tokens(self):
        r = self.report()["acme/w#3"]
        self.assertEqual(r["tokens_by_model"], {})
        self.assertIsNone(r["cost_usd"])
        self.assertTrue(any("no transcript" in g for g in r["gaps"]))

    def test_unpriced_model_makes_total_unknown(self):
        self.transcript("s-nophase", [assistant("2026-10-20T11:01:00Z", "a"),
                                      assistant("2026-10-20T11:02:00Z", "b", model="glm-5p3")])
        r = self.report()["acme/w#2"]
        self.assertIsNone(r["cost_usd"])
        self.assertIsNone(r["cost_by_model_usd"]["glm-5p3"])
        self.assertIsNotNone(r["cost_by_model_usd"]["claude-opus-5-5"])

    def test_parallel_sessions(self):
        self.transcript("s-par-a", [])
        self.transcript("s-par-b", [])
        r = self.report()["acme/w#4"]
        self.assertEqual(r["peak_parallel_sessions"], 2)
        self.assertEqual(r["session_seconds"], 45 * 60)
        self.assertEqual(r["wall_seconds"], 30 * 60)

    def test_usage_outside_run_window_excluded(self):
        self.transcript("s-main", [assistant("2026-10-19T09:00:00Z", "old"), assistant("2026-10-20T09:05:00Z", "a")])
        r = self.report()["acme/w#1"]
        self.assertEqual(r["tokens_by_model"]["claude-opus-5-5"]["messages"], 1)

    def test_bad_lines_counted(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--log", EVENTS, "--now", NOW, "--json"])
        self.assertEqual(json.loads(buf.getvalue())["unparseable_lines"], 1)

    def test_text_report_renders(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--log", EVENTS, "--now", NOW, "--since", "30d", "--detail"])
        out = buf.getvalue()
        self.assertIn("acme/w#1", out)
        self.assertIn("per-ticket medians need", out)
        self.assertIn("unparseable", out)


class Prune(unittest.TestCase):
    def test_prune_keeps_recent_and_drops_junk(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "e.jsonl")
        shutil.copy(EVENTS, path)
        now = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
        removed = wf_report.prune(path, 0, now)
        with open(path) as fh:
            kept = [json.loads(line) for line in fh]
        self.assertTrue(all(e["ts"] >= "2026-10-20T10:00" for e in kept))
        with open(EVENTS) as fh:
            self.assertEqual(removed + len(kept), sum(1 for _ in fh))
        self.assertFalse(os.path.exists(path + ".lock"))


if __name__ == "__main__":
    unittest.main()
