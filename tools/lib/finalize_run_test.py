"""Tests for finalize-run.sh and the pure pieces of lib/finalize_run.py.

Fixtures reuse prune_worktrees_test's throwaway repos with a bare local
origin; `gh` and `claude` are PATH stubs whose answers come from files.
"""

import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import finalize_run as fr  # noqa: E402
from prune_worktrees_test import Base  # noqa: E402

RUN = os.path.join(os.path.dirname(HERE), "finalize-run.sh")

GH_STUB = """#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr list")
    while [ $# -gt 0 ]; do [ "$1" = "--head" ] && b="$2"; shift; done
    f="$GH_PR_DIR/$(echo "$b" | tr / _).json"
    [ -f "$f" ] && cat "$f"
    exit 0 ;;
  "pr view") cat "$GH_PR_DIR/body.txt"; exit 0 ;;
  "issue view") cat "$GH_PR_DIR/issue-$3.json"; exit $? ;;
  "issue close") exit 0 ;;
esac
exit 1
"""

CLAUDE_STUB = """#!/bin/sh
echo "$*" >> "$CLAUDE_LOG"
exit 0
"""


class ReloadAction(unittest.TestCase):
    def test_mapping(self):
        cases = {
            "dot_claude/skills/x/SKILL.md": "/reload-skills",
            "dot_claude/commands/finalize.md": "/reload-skills",
            "dot_claude/agents/a.md": "/reload-skills",
            "dot_claude/hooks/h.sh": "/reload-skills",
            "dot_claude/modify_private_settings.json.tmpl": "/reload-skills",
            "dot_claude/CLAUDE.md.tmpl": "restart sessions",
            "dot_claude/other.txt": "unmapped, no action",
            "tools/finalize-run.sh": "new shells pick it up",
            "dot_zshrc.tmpl": "restart shells",
            "dot_shell_modules/x": "restart shells",
            "docs/a.md": "unmapped, no action",
        }
        for path, action in cases.items():
            self.assertEqual(fr.reload_action(path), action, path)

    def test_table_names_files(self):
        self.assertEqual(fr.reload_table(["tools/a.sh", ""]),
                         ["  tools/a.sh → new shells pick it up"])


class Run(Base):
    def setUp(self):
        super().setUp()
        self.gh_log = self.root / "gh.log"
        self.claude_log = self.root / "claude.log"
        self._stub("gh", GH_STUB)
        self._stub("claude", CLAUDE_STUB)
        jq = shutil.which("jq")
        if jq:
            os.symlink(jq, self.bin / "jq")
        self.env.update(GH_LOG=str(self.gh_log), CLAUDE_LOG=str(self.claude_log),
                        FINALIZE_DISPOSE_DELAY="0")
        (self.pr_dir / "body.txt").write_text("Summary\n\nCloses #7\n")
        self.set_issue(7, "OPEN")

    def set_issue(self, n, state):
        (self.pr_dir / f"issue-{n}.json").write_text(f'{{"state":"{state}"}}')

    def finalize(self, wt, *args, env=None):
        return subprocess.run([RUN, "--dir", str(wt), *args], cwd=wt,
                              env={**self.env, **(env or {})},
                              capture_output=True, text=True)

    def gh_calls(self):
        return self.gh_log.read_text() if self.gh_log.exists() else ""

    def branches(self):
        return self.git(self.repo, "branch", "--list").split()

    def test_clean_merge_closes_ticket_and_removes_checkout(self):
        wt = self.merged_branch("7-feature")
        r = self.finalize(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Finalized #7", r.stdout)
        self.assertIn("ticket closed", r.stdout)
        self.assertIn("main pulled", r.stdout)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertIn("issue close 7 --comment Landed in", self.gh_calls())
        self.assertFalse(wt.exists())
        self.assertNotIn("7-feature", self.branches())

    def test_already_closed_ticket_is_not_closed_again(self):
        wt = self.merged_branch("7-feature")
        self.set_issue(7, "CLOSED")
        r = self.finalize(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("issue close", self.gh_calls())

    def test_unmerged_stops_and_touches_nothing(self):
        wt = self.worktree("7-feature")
        self.set_pr("7-feature", "OPEN")
        r = self.finalize(wt)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("stopped=not-merged", r.stdout)
        self.assertTrue(wt.exists())
        self.assertNotIn("issue close", self.gh_calls())

    def test_dirty_worktree_hands_back(self):
        wt = self.merged_branch("7-feature")
        (wt / "scratch.txt").write_text("wip")
        r = self.finalize(wt)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("handoff=dirty", r.stdout)
        self.assertIn("scratch.txt", r.stdout)
        self.assertTrue(wt.exists())
        self.assertIn("7-feature", self.branches())

    def test_unclaimed_open_ticket_hands_back_without_closing(self):
        wt = self.merged_branch("7-feature")
        (self.pr_dir / "body.txt").write_text("Summary only\n")
        r = self.finalize(wt)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("handoff=unclaimed-ticket", r.stdout)
        self.assertNotIn("issue close", self.gh_calls())
        self.assertTrue(wt.exists())

    def test_unproven_squash_merge_hands_back(self):
        wt = self.merged_branch("7-feature", squash=True)
        self.set_pr("7-feature", "MERGED", merge_commit="")
        r = self.finalize(wt)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("handoff=squash-merged", r.stdout)
        self.assertTrue(wt.exists())

    def test_shortcut_hands_back_then_finishes_with_ticket_closed(self):
        wt = self.merged_branch("sc-123-feature")
        r = self.finalize(wt)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("handoff=shortcut", r.stdout)
        self.assertTrue(wt.exists())
        r = self.finalize(wt, "--ticket-closed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Finalized sc-123", r.stdout)
        self.assertFalse(wt.exists())

    def test_locked_worktree_outside_own_session_hands_back(self):
        wt = self.merged_branch("7-feature")
        self.git(self.repo, "worktree", "lock", str(wt))
        r = self.finalize(wt)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("handoff=locked", r.stdout)
        self.assertTrue(wt.exists())

    def test_locked_own_session_is_disposed_via_claude_rm(self):
        wt = self.merged_branch("7-feature")
        self.git(self.repo, "worktree", "lock", str(wt))
        job = self.root / "jobs" / "abc123"
        job.mkdir(parents=True)
        r = self.finalize(wt, env={"CLAUDE_JOB_DIR": str(job)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for _ in range(50):
            if "7-feature" not in self.branches():
                break
            time.sleep(0.1)
        self.assertEqual(self.claude_log.read_text().strip(), "rm abc123")
        self.assertNotIn("7-feature", self.branches())

    def wait_for_claude_log(self):
        for _ in range(50):
            if self.claude_log.exists():
                break
            time.sleep(0.1)
        return self.claude_log.read_text().strip() if self.claude_log.exists() else ""

    def test_unlocked_own_session_removes_checkout_then_disposes(self):
        wt = self.merged_branch("7-feature")
        job = self.root / "jobs" / "abc123"
        job.mkdir(parents=True)
        r = self.finalize(wt, env={"CLAUDE_JOB_DIR": str(job)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(wt.exists())
        self.assertNotIn("7-feature", self.branches())
        self.assertEqual(self.wait_for_claude_log(), "rm abc123")

    def test_without_job_dir_claude_rm_is_not_called(self):
        wt = self.merged_branch("7-feature")
        r = self.finalize(wt)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        time.sleep(0.5)
        self.assertFalse(self.claude_log.exists())

    def test_chain_handoff_reports_tickets_already_closed(self):
        wt = self.merged_branch("7-feature")
        git_dir = self.git(wt, "rev-parse", "--absolute-git-dir")
        Path(git_dir, "chain").write_text("7\n8\n")
        (self.pr_dir / "body.txt").write_text("Closes #7\n")
        self.set_issue(8, "OPEN")
        r = self.finalize(wt)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("handoff=unclaimed-ticket", r.stdout)
        self.assertIn("done=#7 closed", r.stdout)
        self.assertIn("issue close 7", self.gh_calls())
        self.assertNotIn("issue close 8", self.gh_calls())


if __name__ == "__main__":
    unittest.main()
