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

    def test_interpreted_and_wrapped_test_commands_match(self):
        for cmd in ["bash ./x.test.sh", "sh /abs/x.test.sh", "python3 -I wf_report_test.py",
                    "yarn --cwd /x test", "uv run pytest", "timeout 60 pytest",
                    "python3 -m unittest wf_report_test"]:
            with self.subTest(cmd):
                self.transcript("w", [bash_call("2026-10-20T09:00:00Z", "t1", cmd),
                                     bash_result("2026-10-20T09:00:10Z", "t1")])
                self.assertEqual(len(list(wf_usage.read_tests(wf_usage.transcripts_for_session("w")[0][0]))), 1)

    def test_plain_test_word_is_not_a_test_run(self):
        self.transcript("w", [bash_call("2026-10-20T09:00:00Z", "t1", "test -f x && echo ok"),
                              bash_result("2026-10-20T09:00:01Z", "t1")])
        self.assertEqual(list(wf_usage.read_tests(wf_usage.transcripts_for_session("w")[0][0])), [])


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

    def test_long_context_cache_read_uses_table(self):
        usd = self.p.cost(self.rec(model="claude-haiku-5-5", input=150_000, cache_read=1_000_000))
        self.assertAlmostEqual(usd, (150_000 * 0.5 + 1_000_000 * 0.05) / 1e6)

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
        self.assertEqual((r["reviews"]["fixed"], r["reviews"]["dismissed"], r["reviews"]["deferred"]), (5, 3, 1))
        self.assertEqual(r["reviews"]["bot_batches"], 1)
        self.assertEqual(r["reviews"]["by_reviewer"], {
            "correctness-reviewer": {"fixed": 2, "dismissed": 1, "deferred": 0,
                                     "valid": 2, "rejected": 1, "partial": 0, "validity_unreported": 0},
            "robustness-reviewer": {"fixed": 1, "dismissed": 1, "deferred": 1,
                                    "valid": 0, "rejected": 1, "partial": 1, "validity_unreported": 1}})
        self.assertEqual(r["reviews"]["validity"], {"valid": 2, "rejected": 2, "partial": 1, "validity_unreported": 1})
        self.assertEqual(r["reviews"]["overlap"], {"keys_total": 4, "keys_raised_by_2plus": 1,
                                                   "pairs": {"correctness-reviewer↔robustness-reviewer": 1}})
        self.assertEqual(r["reviews"]["dismissed_findings"], [
            {"reviewer": "correctness-reviewer", "round": 1, "reason": "hypothetical risk"},
            {"reviewer": "robustness-reviewer", "round": 2, "reason": "cost exceeds plausible impact"}])
        self.assertIn("copilot", r["reviews"]["reviewers"])
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
        self.assertIsNone(r["cost_by_stage_usd"]["PLAN"], "stage mixing priced and unpriced models is unknown")

    def test_parallel_sessions(self):
        self.transcript("s-par-a", [])
        self.transcript("s-par-b", [])
        r = self.report()["acme/w#4"]
        self.assertEqual(r["peak_parallel_sessions"], 2)
        self.assertEqual(r["session_seconds"], 45 * 60)
        self.assertEqual(r["wall_seconds"], 30 * 60)

    def test_resumed_session_copy_counted_once(self):
        self.transcript("s-par-a", [assistant("2026-10-20T11:10:00Z", "shared")])
        self.transcript("s-par-b", [assistant("2026-10-20T11:10:00Z", "shared")])
        r = self.report()["acme/w#4"]
        self.assertEqual(r["tokens_by_model"]["claude-opus-5-5"]["messages"], 1,
                         "a resumed session copies earlier messages with the same message id")

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
        self.assertIn("findings by reviewer", out)
        self.assertIn("2 valid / 1 rejected / 0 partial / 0 unreported", out)
        self.assertIn("overlap: 1 of 4 hashed finding(s) raised by ≥2 reviewers "
                      "(correctness-reviewer↔robustness-reviewer: 1)", out)
        self.assertIn("hypothetical risk (correctness-reviewer, R1)", out)

    def test_dismissed_finding_without_reason_is_gap_not_dropped(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "e.jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"v": 1, "ts": "2026-10-20T09:00:00Z", "run_id": "acme/w#5",
                                 "event": "review.finding", "reviewer": "correctness-reviewer",
                                 "severity": "High", "verdict": "dismissed", "round": 1}) + "\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = wf_report.main(["--log", path, "--now", NOW, "--json"])
        self.assertEqual(rc, 0)
        r = json.loads(buf.getvalue())["runs"][0]
        self.assertEqual(r["reviews"]["dismissed_findings"],
                         [{"reviewer": "correctness-reviewer", "round": 1, "reason": None}])
        self.assertTrue(any("no reason" in g for g in r["gaps"]))
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--log", path, "--now", NOW, "--run", "acme/w#5"])
        self.assertIn("reason unknown (correctness-reviewer, R1)", buf.getvalue())

    def test_unknown_finding_verdict_ignored(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "e.jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"v": 1, "ts": "2026-10-20T09:00:00Z", "run_id": "acme/w#5",
                                 "event": "review.finding", "reviewer": "x", "verdict": "wat"}) + "\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--log", path, "--now", NOW, "--json"])
        r = json.loads(buf.getvalue())["runs"][0]
        self.assertEqual(r["reviews"]["by_reviewer"], {})
        self.assertTrue(any("unrecognized verdict" in g for g in r["gaps"]))

    def test_finding_events_stand_in_for_missing_review_result(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "e.jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"v": 1, "ts": "2026-10-20T09:00:00Z", "run_id": "acme/w#5",
                                 "event": "review.round", "round": 1, "state": "start"}) + "\n")
            fh.write(json.dumps({"v": 1, "ts": "2026-10-20T09:05:00Z", "run_id": "acme/w#5",
                                 "event": "review.round", "round": 1, "state": "end"}) + "\n")
            fh.write(json.dumps({"v": 1, "ts": "2026-10-20T09:06:00Z", "run_id": "acme/w#5",
                                 "event": "review.finding", "reviewer": "correctness-reviewer",
                                 "severity": "High", "verdict": "fixed", "round": 1}) + "\n")
            fh.write(json.dumps({"v": 1, "ts": "2026-10-20T09:06:10Z", "run_id": "acme/w#5",
                                 "event": "review.finding", "reviewer": "correctness-reviewer",
                                 "severity": "Medium", "verdict": "dismissed", "round": 1,
                                 "reason": "hypothetical"}) + "\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--log", path, "--now", NOW, "--json"])
        r = json.loads(buf.getvalue())["runs"][0]["reviews"]
        self.assertEqual((r["fixed"], r["dismissed"], r["deferred"]), (1, 1, 0))
        self.assertEqual(r["reviewers"], ["correctness-reviewer"])
        self.assertFalse(any("findings unknown" in g for g in json.loads(buf.getvalue())["runs"][0]["gaps"]))

    def write_log(self, events):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "e.jsonl")
        with open(path, "w") as fh:
            for e in events:
                fh.write(json.dumps(e) + "\n")
        return path

    def finding(self, ts, run, **kw):
        return {"v": 1, "ts": ts, "run_id": run, "event": "review.finding",
                "reviewer": "correctness-reviewer", "severity": "High", "verdict": "fixed", **kw}

    def test_old_finding_events_without_validity_counted_as_unreported(self):
        path = self.write_log([self.finding("2026-10-20T09:00:00Z", "acme/w#5", round=1),
                               self.finding("2026-10-20T09:01:00Z", "acme/w#5", verdict="dismissed", round=1)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--log", path, "--now", NOW, "--json"])
        r = json.loads(buf.getvalue())["runs"][0]
        self.assertEqual(r["reviews"]["validity"], {"validity_unreported": 2})
        self.assertEqual(r["reviews"]["by_reviewer"]["correctness-reviewer"]["validity_unreported"], 2)
        self.assertFalse(any("unrecognized validity" in g for g in r["gaps"]))

    def test_bad_validity_and_key_values_are_gapped(self):
        path = self.write_log([
            self.finding("2026-10-20T09:00:00Z", "acme/w#5", round=1, validity="wat"),
            self.finding("2026-10-20T09:01:00Z", "acme/w#5", round=1, validity="valid", key="not-hex")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--log", path, "--now", NOW, "--json"])
        r = json.loads(buf.getvalue())["runs"][0]
        self.assertEqual(r["reviews"]["validity"], {"valid": 1, "validity_unreported": 1})
        self.assertEqual(r["reviews"]["overlap"], {"keys_total": 0, "keys_raised_by_2plus": 0, "pairs": {}})
        self.assertTrue(any("unrecognized validity" in g for g in r["gaps"]))
        self.assertTrue(any("malformed key" in g for g in r["gaps"]))

    def test_valid_finding_without_key_is_gapped(self):
        path = self.write_log([
            self.finding("2026-10-20T09:00:00Z", "acme/w#5", round=1, validity="valid"),
            self.finding("2026-10-20T09:01:00Z", "acme/w#5", round=1, validity="rejected")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--log", path, "--now", NOW, "--json"])
        r = json.loads(buf.getvalue())["runs"][0]
        self.assertIn("1 valid/partial review.finding event(s) without key excluded from overlap", r["gaps"])

    def test_same_reviewer_re_raising_is_not_overlap(self):
        key = "a" * 64
        path = self.write_log([
            self.finding("2026-10-20T09:00:00Z", "acme/w#5", round=1, validity="valid", key=key),
            self.finding("2026-10-20T09:05:00Z", "acme/w#5", round=2, validity="valid", key=key),
            self.finding("2026-10-20T09:06:00Z", "acme/w#5", round=2, reviewer="robustness-reviewer",
                         verdict="dismissed", validity="valid", key="b" * 64)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--log", path, "--now", NOW, "--json"])
        r = json.loads(buf.getvalue())["runs"][0]["reviews"]
        self.assertEqual(r["overlap"], {"keys_total": 2, "keys_raised_by_2plus": 0, "pairs": {}})

    def test_aggregate_mix_vs_rounds_and_effectiveness(self):
        events = []
        for i, (run, reviewers, rounds) in enumerate([
                ("acme/w#10", ["correctness-reviewer", "robustness-reviewer"], 2),
                ("acme/w#11", ["correctness-reviewer", "robustness-reviewer"], 2),
                ("acme/w#12", ["correctness-reviewer"], 1)]):
            ts = f"2026-10-20T1{i}:00:00Z"
            events.append({"v": 1, "ts": ts, "run_id": run, "event": "review.result",
                           "round": rounds, "fixed": 1, "dismissed": 0, "deferred": 0,
                           "reviewers": ",".join(reviewers)})
            events.append({"v": 1, "ts": ts, "run_id": run, "event": "review.finding",
                           "reviewer": reviewers[0], "severity": "High", "verdict": "fixed",
                           "round": 1, "validity": "valid", "key": f"{i:x}" * 32})
            events.append({"v": 1, "ts": ts, "run_id": run, "event": "finalize.check", "verdict": "ready"})
        path = self.write_log(events)
        buf = io.StringIO()
        with redirect_stdout(buf):
            wf_report.main(["--log", path, "--now", NOW, "--since", "30d"])
        out = buf.getvalue()
        self.assertIn("reviewer effectiveness (merged runs):", out)
        self.assertIn("correctness-reviewer: 3 valid / 0 rejected / 0 partial (3 run(s))", out)
        self.assertIn("reviewer mix vs rounds (merged runs):", out)
        self.assertIn("correctness-reviewer + robustness-reviewer  2 run(s)  median 2 rounds", out)
        self.assertIn("correctness-reviewer  1 run(s)  median 1 rounds", out)
        self.assertNotIn("median 2.0", out)


class MalformedLog(unittest.TestCase):
    def test_wrongly_typed_fields_are_skipped_not_fatal(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "e.jsonl")
        with open(path, "w") as fh:
            fh.write('{"ts":123,"run_id":"a","event":"x"}\n')
            fh.write('{"ts":"2026-10-20T00:00:00Z","run_id":["a"],"event":"x"}\n')
            fh.write('[1,2]\n')
            fh.write('{"ts":"2026-10-20T00:00:00","run_id":"naive","event":"x"}\n')
            fh.write('{"ts":"2026-10-20T00:00:00Z","run_id":"ok#1","event":"x"}\n')
        events, bad = wf_report.load_events(path)
        self.assertEqual(bad, 4)
        self.assertEqual([e["run_id"] for e in events], ["ok#1"])


class Prune(unittest.TestCase):
    def test_missing_log_prunes_nothing(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        self.assertEqual(wf_report.prune(os.path.join(d, "none", "e.jsonl"), 1, datetime.now(timezone.utc)), 0)

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
