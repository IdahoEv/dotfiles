"""Tests for wf_backfill: report parsing, SHA lookup, join, idempotence.

    python3 -m unittest tools/lib/wf_backfill_test.py

Transcripts and the git repo are synthetic and built per test.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wf_backfill as bf  # noqa: E402

BRANCH = "7-do-thing"
SID = "11111111-aaaa"


def git(d, *a, env=None):
    e = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
         "GIT_COMMITTER_EMAIL": "t@t", **(env or {})}
    return subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, text=True, env=e).stdout.strip()


def commit(d, name, when):
    with open(os.path.join(d, name), "w") as fh:
        fh.write(name)
    git(d, "add", name)
    git(d, "commit", "-m", name, env={"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when})
    return git(d, "rev-parse", "HEAD")


def ev(event, ts, **kw):
    return {"v": 1, "ts": ts, "event": event, "run_id": "o/r#7", "repo": "o/r", "ticket": "7",
            "branch": BRANCH, "session_id": SID, **kw}


def write_agent(root, agent_id, agent_type, start, end, text, model="claude-sonnet-5-5"):
    d = os.path.join(root, "proj", SID, "subagents")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"agent-{agent_id}.meta.json"), "w") as fh:
        json.dump({"agentType": agent_type}, fh)
    rows = [{"type": "user", "timestamp": start, "message": {"role": "user", "content": "review"}},
            {"type": "assistant", "timestamp": end, "message": {
                "id": "m1", "model": model,
                "usage": {"input_tokens": 10, "output_tokens": 50, "cache_read_input_tokens": 5},
                "content": [{"type": "tool_use", "name": "SubagentHandback", "input": {"message": text}}]}}]
    with open(os.path.join(d, f"agent-{agent_id}.jsonl"), "w") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows))


class Pure(unittest.TestCase):
    def test_clean_claim_collapses_whitespace(self):
        self.assertEqual(bf.clean_claim("  a.sh:\tdrops\n the line "), "a.sh: drops the line")

    def test_parse_report_lines(self):
        text = ("High | tools/a.sh:42 | Drops the last line. Extra. | input X | fix | test\n"
                "- Low | `docs/x.md` | typo in heading | n/a | fix | none\n"
                "prose that is not a finding")
        got = bf.parse_report(text)
        self.assertEqual([(f["severity"], f["path"], f["line"]) for f in got],
                         [("High", "tools/a.sh", 42), ("Low", "docs/x.md", None)])
        self.assertEqual(got[0]["claim"], "tools/a.sh: Drops the last line.")

    def test_parse_tolerates_observed_location_shapes(self):
        text = ("MEDIUM | /w/repo/tools/a.sh:110-122 (head_sha_at) | Drops SHAs. | x | y | z\n"
                "Medium | tools/b.sh:330, 281-282 | Prints a partial total. | x | y | z\n"
                "**High** | `c.md` (line 5) | Wrong heading. | x | y | z")
        got = bf.parse_report(text)
        self.assertEqual([(f["severity"], f["path"], f["line"]) for f in got],
                         [("Medium", "/w/repo/tools/a.sh", 110), ("Medium", "tools/b.sh", 330), ("High", "c.md", None)])

    def test_relative_path_strips_known_roots(self):
        self.assertEqual(bf.relative_path("/w/repo/tools/a.sh", ["/w/repo"]), "tools/a.sh")
        self.assertEqual(bf.relative_path("tools/a.sh", ["/w/repo"]), "tools/a.sh")

    def test_no_findings_parses_empty(self):
        self.assertEqual(bf.parse_report("no findings. all tests pass"), [])

    def test_review_line(self):
        self.assertEqual(bf.parse_review_line("## Review\n2 rounds: 3 fixed, 2 dismissed, 0 deferred\n"),
                         {"rounds": 2, "fixed": 3, "dismissed": 2, "deferred": 0})
        self.assertIsNone(bf.parse_review_line("nothing"))

    def test_pairing_by_severity_then_order(self):
        existing = [{"severity": "Low", "ts": "a"}, {"severity": "High", "ts": "b"}, {"severity": "Low", "ts": "c"}]
        parsed = [{"severity": "High"}, {"severity": "Low"}, {"severity": "Low"}, {"severity": "Low"}]
        got = [m and m["ts"] for _, m in bf.pair_findings(parsed, existing)]
        self.assertEqual(got, ["b", "a", "c", None])


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", BRANCH)
        self.sha_pre = commit(self.repo, "a", "2026-10-01T10:00:00Z")
        self.sha_fix = commit(self.repo, "b", "2026-10-01T10:30:00Z")
        self.projects = os.path.join(self.tmp, "projects")
        self.log = os.path.join(self.tmp, "events.jsonl")
        write_agent(self.projects, "abc1", "correctness-reviewer", "2026-10-01T10:05:00Z", "2026-10-01T10:08:00Z",
                    "High | tools/a.sh:42 | Drops the last line. | x | y | z\nLow | b.md:3 | typo here | x | y | z")
        write_agent(self.projects, "abc2", "robustness-reviewer", "2026-10-01T10:05:10Z", "2026-10-01T10:09:00Z",
                    "no findings")
        events = [ev("review.round", "2026-10-01T10:04:00.000Z", round=1, state="start"),
                  ev("review.finding", "2026-10-01T10:20:00.000Z", reviewer="correctness-reviewer",
                     severity="High", verdict="fixed", round=1),
                  ev("review.finding", "2026-10-01T10:20:00.100Z", reviewer="correctness-reviewer",
                     severity="Low", verdict="dismissed", round=1, reason="nit"),
                  ev("review.result", "2026-10-01T10:31:00.000Z", round=1, fixed=1, dismissed=1, deferred=0,
                     reviewers="correctness-reviewer,robustness-reviewer"),
                  ev("review.round", "2026-10-01T10:31:00.100Z", round=1, state="end")]
        with open(self.log, "w") as fh:
            fh.write("\n".join(json.dumps(e) for e in events) + "\n")

    def run_main(self, *extra):
        out = io.StringIO()
        with redirect_stdout(out):
            bf.main(["--branch", BRANCH, "--git-dir", self.repo, "--log", self.log,
                     "--projects", self.projects, *extra])
        return out.getvalue()

    def raw(self):
        with open(self.log) as fh:
            return fh.read()

    def lines(self):
        return [json.loads(l) for l in self.raw().splitlines()]

    def test_round_sha_from_git_history(self):
        new, s = bf.plan_branch(BRANCH, self.lines(), self.projects, self.repo)
        shas = {e["state"]: e["sha"] for e in new if e["event"] == "review.round"}
        self.assertEqual(shas, {"start": self.sha_pre, "end": self.sha_fix})
        self.assertEqual((s["rounds"], s["rounds_sha"]), (2, 2))

    def test_launch_carries_model_and_tokens(self):
        new, _ = bf.plan_branch(BRANCH, self.lines(), self.projects, self.repo)
        launch = next(e for e in new if e["event"] == "review.launch" and e["reviewer"] == "correctness-reviewer")
        self.assertEqual((launch["model"], launch["round"], launch["tokens_out"], launch["tokens_in"], launch["backfill"]),
                         ("claude-sonnet-5-5", 1, 50, 15, 1))
        self.assertNotIn("effort", launch)

    def test_findings_get_text_and_pairing(self):
        new, s = bf.plan_branch(BRANCH, self.lines(), self.projects, self.repo)
        fs = [e for e in new if e["event"] == "review.finding"]
        self.assertEqual([(f["severity"], f["path"], f.get("line")) for f in fs],
                         [("High", "tools/a.sh", 42), ("Low", "b.md", 3)])
        self.assertEqual(fs[0]["matched_ts"], "2026-10-01T10:20:00.000Z")
        self.assertTrue(all("verdict" not in f for f in fs))
        self.assertEqual(s["findings_unmatched"], 0)

    def test_rerun_is_idempotent_and_leaves_existing_lines(self):
        before = self.raw()
        first = self.run_main()
        mid = self.raw()
        self.assertTrue(mid.startswith(before))
        self.assertGreater(len(mid), len(before))
        second = self.run_main()
        self.assertEqual(self.raw(), mid)
        self.assertIn("events written 0", second)
        self.assertNotIn("events written 0", first)

    def test_dry_run_writes_nothing(self):
        before = self.raw()
        self.run_main("--dry-run")
        self.assertEqual(self.raw(), before)

    def test_cloud_session_is_partial_with_unknowns(self):
        empty = os.path.join(self.tmp, "none")
        os.makedirs(empty)
        new, s = bf.plan_branch(BRANCH, self.lines(), empty, self.repo)
        self.assertEqual(s["status"], "partial")
        self.assertEqual(s["sessions_no_transcripts"], 1)
        self.assertEqual({e["event"] for e in new}, {"review.round"})
        self.assertIn("reviewer model", s["unknown"])
        text = bf.format_summary(s, 0, 0)
        self.assertIn("unknown: reviewer model", text)
        self.assertIn("round SHAs 2/2", text)

    def test_unknown_branch_reports_none(self):
        new, s = bf.plan_branch("nope", self.lines(), self.projects, self.repo)
        self.assertEqual((new, s["status"]), ([], "none"))

    def test_transcript_outside_round_window_is_skipped(self):
        write_agent(self.projects, "abc3", "security-reviewer", "2026-10-01T11:00:00Z", "2026-10-01T11:01:00Z", "no findings")
        new, s = bf.plan_branch(BRANCH, self.lines(), self.projects, self.repo)
        self.assertFalse(any(e.get("reviewer") == "security-reviewer" for e in new))
        self.assertTrue(any("ends after no logged round" in n for n in s["notes"]))

    def test_aborted_attempt_gets_launch_but_no_findings(self):
        write_agent(self.projects, "abc0", "correctness-reviewer", "2026-10-01T10:04:30Z", "2026-10-01T10:04:50Z",
                    "Medium | old.md:1 | aborted attempt finding | x | y | z")
        new, s = bf.plan_branch(BRANCH, self.lines(), self.projects, self.repo)
        launches = [e for e in new if e["event"] == "review.launch" and e["reviewer"] == "correctness-reviewer"]
        self.assertEqual(len(launches), 2)
        self.assertFalse(any(e.get("path") == "old.md" for e in new))
        self.assertTrue(any("aborted attempt" in n for n in s["notes"]))

    def test_transcript_before_first_round_is_skipped(self):
        write_agent(self.projects, "abc4", "plan-reviewer", "2026-10-01T09:00:00Z", "2026-10-01T09:02:00Z", "no findings")
        new, _ = bf.plan_branch(BRANCH, self.lines(), self.projects, self.repo)
        self.assertFalse(any(e.get("reviewer") == "plan-reviewer" for e in new))

    def test_live_launch_is_not_duplicated(self):
        events = self.lines() + [ev("review.launch", "2026-10-01T10:05:00.000Z", reviewer="correctness-reviewer",
                                    round=1, source="local", model="sonnet")]
        new, _ = bf.plan_branch(BRANCH, events, self.projects, self.repo)
        self.assertFalse(any(e.get("reviewer") == "correctness-reviewer" for e in new))
        self.assertTrue(any(e.get("reviewer") == "robustness-reviewer" for e in new))

    def test_mixed_local_and_cloud_session_is_flagged(self):
        events = self.lines() + [ev("review.finding", "2026-10-01T10:21:00.000Z", reviewer="x-reviewer",
                                    severity="Low", verdict="fixed", round=1, session_id="22222222-bbbb")]
        _, s = bf.plan_branch(BRANCH, events, self.projects, self.repo)
        self.assertEqual(s["sessions_no_transcripts"], 1)
        self.assertEqual((s["findings_text"], s["findings"]), (2, 3))
        self.assertTrue(any("for 1 of 2 sessions" in u for u in s["unknown"]))

    def test_branch_commits_dated_after_round_do_not_fall_back_to_main(self):
        repo = os.path.join(self.tmp, "rebased")
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        commit(repo, "m", "2026-09-01T10:00:00Z")
        git(repo, "checkout", "-q", "-b", BRANCH)
        commit(repo, "r", "2026-11-01T10:00:00Z")
        _, s = bf.plan_branch(BRANCH, self.lines(), self.projects, repo)
        self.assertEqual(s["rounds_sha"], 0)

    def test_branch_merged_into_main_still_recovers_shas(self):
        repo = os.path.join(self.tmp, "merged")
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        commit(repo, "m", "2026-09-01T10:00:00Z")
        git(repo, "checkout", "-q", "-b", BRANCH)
        commit(repo, "r", "2026-10-01T10:00:00Z")
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--ff-only", BRANCH)
        _, s = bf.plan_branch(BRANCH, self.lines(), self.projects, repo)
        self.assertEqual(s["rounds_sha"], s["rounds"])

    def test_bold_severity_parses(self):
        got = bf.parse_report("**High** | a.sh:3 | breaks | x | y | z")
        self.assertEqual([f["severity"] for f in got], ["High"])


if __name__ == "__main__":
    unittest.main()
