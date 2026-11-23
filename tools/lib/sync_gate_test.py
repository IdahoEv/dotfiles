"""Tests for sync-gate.sh and the pure verdict ladder in lib/sync_gate.py."""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sync_gate as sg  # noqa: E402
from prune_worktrees_test import Base  # noqa: E402

GATE = os.path.join(os.path.dirname(HERE), "sync-gate.sh")

GH_STUB = """#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr view")
    b="$3"
    f="$GH_PR_DIR/view-$(echo "$b" | tr / _)"
    if [ -f "$f.err" ]; then cat "$f.err" >&2; exit 1; fi
    [ -f "$f.json" ] && cat "$f.json" && exit 0
    echo "no pull requests found for branch \\"$b\\"" >&2; exit 1 ;;
esac
exit 1
"""


def facts(**kw):
    base = dict(dirty=[], head="aaa", pr_found=True, gh_ok=True, pr_number="5",
                pr_state="OPEN", is_draft=False, mergeable="MERGEABLE",
                pr_head="aaa", head_vs_pr="equal", base="main")
    base.update(kw)
    return sg.Facts(**base)


class Verdict(unittest.TestCase):
    def v(self, **kw):
        return sg.choose_verdict(facts(**kw))[0]

    def test_ready(self):
        self.assertEqual(self.v(), "ready")

    def test_each_refusal_has_its_own_verdict(self):
        cases = {
            "dirty": dict(dirty=[" M a.txt"]),
            "unknown": dict(gh_ok=False),
            "no-pr": dict(pr_found=False),
            "already-merged": dict(pr_state="MERGED"),
            "closed": dict(pr_state="CLOSED"),
            "draft": dict(is_draft=True),
            "unpushed": dict(head_vs_pr="ahead", pr_head="bbb"),
            "behind-pr": dict(head_vs_pr="behind", pr_head="bbb"),
            "diverged": dict(head_vs_pr="diverged", pr_head="bbb"),
            "conflict": dict(mergeable="CONFLICTING"),
            "mergeable-unknown": dict(mergeable="UNKNOWN"),
        }
        for want, kw in cases.items():
            self.assertEqual(self.v(**kw), want)
        self.assertEqual(len(set(cases)), len(cases))

    def test_dirty_outranks_pr_state(self):
        self.assertEqual(self.v(dirty=["?? x"], pr_state="MERGED"), "dirty")

    def test_reasons_are_single_distinct_lines(self):
        seen = set()
        for kw in (dict(dirty=["?? x"]), dict(gh_ok=False), dict(pr_found=False),
                   dict(pr_state="MERGED"), dict(pr_state="CLOSED"), dict(is_draft=True),
                   dict(head_vs_pr="ahead"), dict(head_vs_pr="behind"),
                   dict(head_vs_pr="diverged"), dict(mergeable="CONFLICTING"),
                   dict(mergeable="UNKNOWN")):
            reason = sg.choose_verdict(facts(**kw))[1]
            self.assertNotIn("\n", reason)
            seen.add(reason)
        self.assertEqual(len(seen), 11)

    def test_conflict_reason_points_at_sync(self):
        self.assertIn("/sync", sg.choose_verdict(facts(mergeable="CONFLICTING"))[1])

    def test_indicator_state_matches_gate(self):
        cases = {
            "clean": (dict(), "ready"),
            "dirty": (dict(dirty=[" M a.txt"]), "dirty"),
            "ahead": (dict(head_vs_pr="ahead", pr_head="bbb"), "unpushed"),
            "behind": (dict(head_vs_pr="behind", pr_head="bbb"), "behind-pr"),
            "diverged": (dict(head_vs_pr="diverged", pr_head="bbb"), "diverged"),
        }
        for state, (kw, verdict) in cases.items():
            f = facts(**kw)
            self.assertEqual(sg.indicator_state(f), state)
            self.assertEqual(sg.choose_verdict(f)[0], verdict)

    def test_every_indicator_state_has_a_local_verdict(self):
        self.assertEqual(set(sg.LOCAL_VERDICTS), set(sg.INDICATOR_STATES))


class Cli(Base):
    def setUp(self):
        super().setUp()
        self.gh_log = self.root / "gh.log"
        self._stub("gh", GH_STUB)
        self.env.update(GH_LOG=str(self.gh_log), SYNC_GATE_RETRY_DELAY="0")

    def view(self, branch, *, state="OPEN", draft=False, mergeable="MERGEABLE",
             head=None, number=5):
        head = head or self.git(self.repo, "rev-parse", f"refs/heads/{branch}")
        (self.pr_dir / f"view-{branch}.json").write_text(json.dumps({
            "number": number, "state": state, "isDraft": draft, "mergeable": mergeable,
            "headRefOid": head, "baseRefName": "main"}))

    def gate(self, wt):
        r = subprocess.run([GATE, "--dir", str(wt)], cwd=wt, env=self.env,
                           capture_output=True, text=True)
        out = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
        return r.returncode, out

    def test_ready(self):
        wt = self.worktree("7-feature")
        self.view("7-feature")
        rc, out = self.gate(wt)
        self.assertEqual((rc, out["verdict"]), (0, "ready"))
        self.assertEqual(out["pr_number"], "5")

    def test_dirty(self):
        wt = self.worktree("7-feature")
        self.view("7-feature")
        (wt / "scratch.txt").write_text("x")
        rc, out = self.gate(wt)
        self.assertEqual((rc, out["verdict"]), (2, "dirty"))

    def test_unpushed_commit(self):
        wt = self.worktree("7-feature")
        self.view("7-feature")
        self.commit(wt, "more")
        rc, out = self.gate(wt)
        self.assertEqual((rc, out["verdict"]), (2, "unpushed"))

    def test_pr_has_commits_local_lacks(self):
        wt = self.worktree("7-feature")
        self.commit(wt, "more")
        self.git(wt, "push", "-q", "origin", "7-feature")
        newer = self.git(wt, "rev-parse", "HEAD")
        self.git(wt, "reset", "-q", "--hard", "HEAD~1")
        self.view("7-feature", head=newer)
        rc, out = self.gate(wt)
        self.assertEqual((rc, out["verdict"]), (2, "behind-pr"))

    def test_pr_head_unknown_locally_is_behind(self):
        wt = self.worktree("7-feature")
        self.view("7-feature", head="f" * 40)
        rc, out = self.gate(wt)
        self.assertEqual((rc, out["verdict"]), (2, "behind-pr"))

    def test_no_pr(self):
        wt = self.worktree("7-feature")
        rc, out = self.gate(wt)
        self.assertEqual((rc, out["verdict"]), (2, "no-pr"))

    def test_gh_failure_is_unknown_not_no_pr(self):
        wt = self.worktree("7-feature")
        (self.pr_dir / "view-7-feature.err").write_text("HTTP 502")
        rc, out = self.gate(wt)
        self.assertEqual((rc, out["verdict"]), (2, "unknown"))

    def test_gh_not_executable_is_unknown(self):
        import sync_gate
        from unittest import mock
        with mock.patch.object(sync_gate, "run_cmd", side_effect=FileNotFoundError("gh")):
            self.assertEqual(sync_gate._view(".", "b"), ("error", {}))

    def test_states_and_conflict(self):
        wt = self.worktree("7-feature")
        for kw, want in ((dict(state="MERGED"), "already-merged"),
                         (dict(state="CLOSED"), "closed"),
                         (dict(draft=True), "draft"),
                         (dict(mergeable="CONFLICTING"), "conflict")):
            self.view("7-feature", **kw)
            self.assertEqual(self.gate(wt)[1]["verdict"], want)

    def test_unknown_mergeable_is_retried_then_refused(self):
        wt = self.worktree("7-feature")
        self.view("7-feature", mergeable="UNKNOWN")
        rc, out = self.gate(wt)
        self.assertEqual((rc, out["verdict"]), (2, "mergeable-unknown"))
        self.assertGreater(self.gh_log.read_text().count("pr view"), 1)

    def test_gate_writes_nothing(self):
        wt = self.worktree("7-feature")
        self.view("7-feature")
        before = self.git(wt, "status", "--porcelain")
        self.gate(wt)
        self.assertEqual(self.git(wt, "status", "--porcelain"), before)
        self.assertTrue(all(l.startswith("pr view")
                            for l in self.gh_log.read_text().splitlines()))

    def test_detached_head_is_a_usage_error(self):
        wt = self.worktree("7-feature")
        self.git(wt, "checkout", "-q", "--detach")
        r = subprocess.run([GATE, "--dir", str(wt)], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
