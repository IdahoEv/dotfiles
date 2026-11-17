"""Tests for merge-run.sh and the pure method resolution in lib/merge_run.py."""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import merge_run as mr  # noqa: E402
from prune_worktrees_test import Base  # noqa: E402

RUN = os.path.join(os.path.dirname(HERE), "merge-run.sh")

GH_STUB = """#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr view")
    if [ "$3" = "5" ]; then
      if [ -f "$GH_PR_DIR/merged" ]; then echo '{"state":"MERGED"}'; else echo '{"state":"OPEN"}'; fi
      exit 0
    fi
    f="$GH_PR_DIR/view-$(echo "$3" | tr / _)"
    [ -f "$f.json" ] && cat "$f.json" && exit 0
    echo "no pull requests found for branch \\"$3\\"" >&2; exit 1 ;;
  "pr merge")
    [ -f "$GH_PR_DIR/merge-fail" ] && { echo "merge blocked" >&2; exit 1; }
    [ -f "$GH_PR_DIR/queue" ] || touch "$GH_PR_DIR/merged"
    exit 0 ;;
  "repo view")
    [ -f "$GH_PR_DIR/repo.json" ] && cat "$GH_PR_DIR/repo.json" && exit 0
    exit 1 ;;
  "api -X")
    if [ -f "$GH_PR_DIR/api.err" ]; then cat "$GH_PR_DIR/api.err" >&2; exit 1; fi
    exit 0 ;;
  "api repos/"*)
    [ -f "$GH_PR_DIR/ref.err" ] && { cat "$GH_PR_DIR/ref.err" >&2; exit 1; }
    cat "$GH_PR_DIR/ref-sha"; exit 0 ;;
esac
exit 1
"""

ALL = dict(mergeCommitAllowed=True, squashMergeAllowed=True, rebaseMergeAllowed=True)


def allowed(**kw):
    base = dict(mergeCommitAllowed=False, squashMergeAllowed=False, rebaseMergeAllowed=False)
    base.update(kw)
    return base


class ResolveMethod(unittest.TestCase):
    def test_configured_wins_when_allowed(self):
        self.assertEqual(mr.resolve_method("squash", ALL), ("squash", ""))

    def test_configured_but_disallowed_is_refused(self):
        m, why = mr.resolve_method("squash", allowed(mergeCommitAllowed=True))
        self.assertEqual((m, why), ("", "merge-method-not-allowed"))

    def test_unset_prefers_plain_merge(self):
        self.assertEqual(mr.resolve_method(None, ALL), ("merge", ""))

    def test_unset_takes_the_single_allowed_method(self):
        self.assertEqual(mr.resolve_method(None, allowed(rebaseMergeAllowed=True)),
                         ("rebase", ""))

    def test_unset_without_merge_and_several_allowed_is_ambiguous(self):
        m, why = mr.resolve_method(None, allowed(squashMergeAllowed=True,
                                                 rebaseMergeAllowed=True))
        self.assertEqual((m, why), ("", "merge-method-ambiguous"))

    def test_configured_with_unreadable_repo_is_trusted(self):
        self.assertEqual(mr.resolve_method("squash", None), ("squash", ""))

    def test_unset_with_unreadable_repo_is_unknown(self):
        self.assertEqual(mr.resolve_method(None, None), ("", "merge-method-unknown"))


class Run(Base):
    def setUp(self):
        super().setUp()
        self.gh_log = self.root / "gh.log"
        self._stub("gh", GH_STUB)
        self.env.update(GH_LOG=str(self.gh_log), SYNC_GATE_RETRY_DELAY="0")
        (self.pr_dir / "repo.json").write_text(json.dumps(ALL))

    def view(self, branch, *, state="OPEN", draft=False, mergeable="MERGEABLE"):
        head = self.git(self.repo, "rev-parse", f"refs/heads/{branch}")
        (self.pr_dir / "ref-sha").write_text(head)
        (self.pr_dir / f"view-{branch}.json").write_text(json.dumps({
            "number": 5, "state": state, "isDraft": draft, "mergeable": mergeable,
            "headRefOid": head, "baseRefName": "main"}))

    def merge(self, wt):
        return subprocess.run([RUN, "--dir", str(wt)], cwd=wt, env=self.env,
                              capture_output=True, text=True)

    def calls(self):
        return self.gh_log.read_text() if self.gh_log.exists() else ""

    def ready(self, name="7-feature"):
        wt = self.worktree(name)
        self.view(name)
        return wt

    def test_success_merges_and_deletes_remote_branch(self):
        wt = self.ready()
        r = self.merge(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("pr merge 5 --merge --match-head-commit ", self.calls())
        self.assertIn("api -X DELETE", self.calls())
        self.assertIn("refs/heads/7-feature", self.calls())
        self.assertNotIn("--delete-branch", self.calls())
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertIn("Merged #5", r.stdout)
        self.assertTrue(wt.exists())

    def test_detached_head_is_a_usage_error_even_with_branch_flag(self):
        wt = self.ready()
        self.git(wt, "checkout", "-q", "--detach")
        r = subprocess.run([RUN, "--dir", str(wt), "--branch", "7-feature"], cwd=wt,
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("detached HEAD", r.stderr)
        self.assertNotIn("pr merge", self.calls())

    def test_configured_method_is_used(self):
        wt = self.ready()
        (self.repo / ".start-ticket.conf").write_text("merge_method=squash\n")
        r = self.merge(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("pr merge 5 --squash", self.calls())

    def test_invalid_configured_method_is_a_usage_error(self):
        wt = self.ready()
        (self.repo / ".start-ticket.conf").write_text("merge_method=yolo\n")
        r = self.merge(wt)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("pr merge", self.calls())

    def test_every_gate_refusal_stops_without_writing(self):
        wt = self.ready()
        (wt / "scratch.txt").write_text("x")
        r = self.merge(wt)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("stopped=dirty", r.stdout)
        self.assertIn("reason=", r.stdout)
        self.assertNotIn("pr merge", self.calls())
        self.assertNotIn("api -X", self.calls())
        self.assertTrue((wt / "scratch.txt").exists())

    def test_conflict_points_at_sync(self):
        wt = self.worktree("7-feature")
        self.view("7-feature", mergeable="CONFLICTING")
        r = self.merge(wt)
        self.assertEqual(r.returncode, 2)
        self.assertIn("stopped=conflict", r.stdout)
        self.assertIn("/sync", r.stdout)
        self.assertNotIn("pr merge", self.calls())

    def test_ambiguous_method_stops_before_merging(self):
        wt = self.ready()
        (self.pr_dir / "repo.json").write_text(json.dumps(
            allowed(squashMergeAllowed=True, rebaseMergeAllowed=True)))
        r = self.merge(wt)
        self.assertEqual(r.returncode, 2)
        self.assertIn("stopped=merge-method-ambiguous", r.stdout)
        self.assertNotIn("pr merge", self.calls())

    def test_merge_failure_stops_and_keeps_branch(self):
        wt = self.ready()
        (self.pr_dir / "merge-fail").write_text("")
        r = self.merge(wt)
        self.assertEqual(r.returncode, 2)
        self.assertIn("stopped=merge-failed", r.stdout)
        self.assertNotIn("api -X", self.calls())

    def test_queued_merge_keeps_remote_branch(self):
        wt = self.ready()
        (self.pr_dir / "queue").write_text("")
        r = self.merge(wt)
        self.assertEqual(r.returncode, 2)
        self.assertIn("stopped=not-merged", r.stdout)
        self.assertNotIn("api -X", self.calls())

    def test_branch_already_deleted_by_provider_is_fine(self):
        wt = self.ready()
        (self.pr_dir / "api.err").write_text("HTTP 422: Reference does not exist")
        r = self.merge(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_moved_remote_branch_is_not_deleted(self):
        wt = self.ready()
        (self.pr_dir / "ref-sha").write_text("0" * 40)
        r = self.merge(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("api -X", self.calls())
        self.assertIn("warning=remote-branch-not-deleted", r.stdout)

    def test_remote_branch_already_gone_skips_delete(self):
        wt = self.ready()
        (self.pr_dir / "ref.err").write_text("gh: Not Found (HTTP 404)")
        r = self.merge(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("api -X", self.calls())
        self.assertNotIn("warning=", r.stdout)

    def test_branch_delete_failure_warns_but_reports_merged(self):
        wt = self.ready()
        (self.pr_dir / "api.err").write_text("HTTP 403: forbidden")
        r = self.merge(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Merged #5", r.stdout)
        self.assertIn("warning=remote-branch-not-deleted", r.stdout)


if __name__ == "__main__":
    unittest.main()
