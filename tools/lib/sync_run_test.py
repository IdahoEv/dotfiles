"""Tests for sync-run.sh. Fixtures are throwaway repos with a bare local origin."""

import os
import subprocess
import unittest
from pathlib import Path

from prune_worktrees_test import Base

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(os.path.dirname(HERE), "sync-run.sh")


class Sync(Base):
    def sync(self, wt, *args):
        r = subprocess.run([RUN, "--dir", str(wt), *args], cwd=wt, env=self.env,
                           capture_output=True, text=True)
        out = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
        return r, out

    def advance_main(self, name="upstream", content=None):
        (self.repo / f"{name}.txt").write_text(content or name)
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-qm", name)
        self.git(self.repo, "push", "-q", "origin", "main")

    def remote_head(self, branch):
        return self.git(self.origin, "rev-parse", f"refs/heads/{branch}")

    def parents(self, wt):
        return self.git(wt, "rev-list", "--parents", "-n1", "HEAD").split()[1:]

    def conflicting_branch(self):
        wt = self.worktree("feat", pushed=False)
        (wt / "shared.txt").write_text("branch side\n")
        self.git(wt, "add", "-A")
        self.git(wt, "commit", "-qm", "branch shared")
        self.git(wt, "push", "-q", "-u", "origin", "feat")
        self.advance_main("shared", "main side\n")
        return wt

    def test_up_to_date_prints_one_line_and_pushes_nothing(self):
        wt = self.worktree("feat")
        before = self.remote_head("feat")
        r, _ = self.sync(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertIn("up to date", r.stdout)
        self.assertEqual(self.remote_head("feat"), before)

    def test_clean_merge_is_committed_and_pushed(self):
        wt = self.worktree("feat")
        self.advance_main()
        r, _ = self.sync(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.parents(wt)), 2)
        self.assertEqual(self.remote_head("feat"), self.git(wt, "rev-parse", "HEAD"))
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertTrue((wt / "upstream.txt").exists())

    def test_branch_without_upstream_is_pushed_with_tracking(self):
        wt = self.worktree("feat", pushed=False)
        self.advance_main()
        r, _ = self.sync(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.remote_head("feat"), self.git(wt, "rev-parse", "HEAD"))

    def test_conflict_hands_back_with_files_and_pushes_nothing(self):
        wt = self.conflicting_branch()
        before = self.remote_head("feat")
        r, out = self.sync(wt)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(out["handoff"], "conflict")
        self.assertEqual(out["files"], "shared.txt")
        self.assertEqual(out["base"], "origin/main")
        self.assertTrue((wt / ".git").exists())
        self.assertTrue(self.git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD"))
        self.assertEqual(self.remote_head("feat"), before)

    def test_finish_commits_the_resolution_and_pushes(self):
        wt = self.conflicting_branch()
        self.sync(wt)
        (wt / "shared.txt").write_text("resolved\n")
        self.git(wt, "add", "shared.txt")
        r, _ = self.sync(wt, "--finish")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.parents(wt)), 2)
        self.assertEqual(self.remote_head("feat"), self.git(wt, "rev-parse", "HEAD"))

    def test_finish_with_unresolved_paths_hands_back_and_pushes_nothing(self):
        wt = self.conflicting_branch()
        before = self.remote_head("feat")
        self.sync(wt)
        r, out = self.sync(wt, "--finish")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(out["handoff"], "unresolved")
        self.assertIn("shared.txt", out["files"])
        self.assertEqual(self.remote_head("feat"), before)

    def test_rerun_during_merge_in_progress_is_refused(self):
        wt = self.conflicting_branch()
        self.sync(wt)
        r, _ = self.sync(wt)
        self.assertEqual(r.returncode, 1)

    def test_dirty_tree_is_refused(self):
        wt = self.worktree("feat")
        self.advance_main()
        (wt / "scratch.txt").write_text("wip")
        r, _ = self.sync(wt)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("uncommitted", r.stderr)
        self.assertNotIn("upstream.txt", os.listdir(wt))

    def test_detached_head_is_refused(self):
        wt = self.worktree("feat")
        self.git(wt, "checkout", "-q", "--detach")
        r, _ = self.sync(wt)
        self.assertEqual(r.returncode, 1)
        self.assertIn("detached", r.stderr)

    def test_base_branch_is_refused(self):
        self.advance_main()
        r, _ = self.sync(self.repo)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("base branch", r.stderr)

    def test_rejected_push_hands_back(self):
        wt = self.worktree("feat")
        other = self.root / "other-clone"
        self.git(self.root, "clone", "-q", str(self.origin), str(other))
        self.git(other, "checkout", "-q", "feat")
        self.commit(other, "elsewhere")
        self.git(other, "push", "-q", "origin", "feat")
        self.advance_main()
        r, out = self.sync(wt)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(out["handoff"], "push-failed")

    def test_rebase_method_rewrites_and_force_pushes_with_lease(self):
        wt = self.worktree("feat")
        (self.repo / ".start-ticket.conf").write_text("sync_method=rebase\n")
        self.advance_main()
        r, _ = self.sync(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.parents(wt)), 1)
        self.assertEqual(self.remote_head("feat"), self.git(wt, "rev-parse", "HEAD"))
        self.assertIn("rebase", r.stdout)

    def test_rebase_conflict_hands_back_then_finishes(self):
        wt = self.conflicting_branch()
        (self.repo / ".start-ticket.conf").write_text("sync_method=rebase\n")
        r, out = self.sync(wt)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(out["handoff"], "conflict")
        self.assertEqual(out["method"], "rebase")
        (wt / "shared.txt").write_text("resolved\n")
        self.git(wt, "add", "shared.txt")
        r, _ = self.sync(wt, "--finish")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.parents(wt)), 1)
        self.assertEqual(self.remote_head("feat"), self.git(wt, "rev-parse", "HEAD"))

    def test_invalid_sync_method_is_a_usage_error(self):
        wt = self.worktree("feat")
        (self.repo / ".start-ticket.conf").write_text("sync_method=yolo\n")
        r, _ = self.sync(wt)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
