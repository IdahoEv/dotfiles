"""Tests for prune-worktrees.sh and the pure pieces of lib/prune_worktrees.py.

Fixtures are throwaway repos with a bare local origin; `gh` and `claude` are
PATH stubs whose answers come from files, so no network and no real sessions.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prune_worktrees as pw  # noqa: E402

PRUNE = os.path.join(os.path.dirname(HERE), "prune-worktrees.sh")

GH_STUB = """#!/bin/sh
if [ "$1 $2" = "pr list" ]; then
  while [ $# -gt 0 ]; do [ "$1" = "--head" ] && b="$2"; shift; done
  f="$GH_PR_DIR/$(echo "$b" | tr / _).json"
  [ -f "$f" ] && cat "$f"
  exit 0
fi
exit 1
"""

CLAUDE_STUB = """#!/bin/sh
[ -n "${CLAUDE_STUB_RC:-}" ] && exit "$CLAUDE_STUB_RC"
if [ -f "${CLAUDE_AGENTS_JSON:-}" ]; then cat "$CLAUDE_AGENTS_JSON"; else echo '[]'; fi
"""

_STRIP = ("PROJECT_OVERLAYS_DIR", "GIT_TOOLS_PROJECTS_DIR", "CHEZMOI_SOURCE_DIR",
          "XDG_STATE_HOME", "WF_TELEMETRY", "WF_TELEMETRY_LOG",
          "CLAUDE_CODE_SESSION_ID", "CLAUDE_JOB_DIR")


class Base(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="prune-test.")))
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.pr_dir = self.root / "prs"
        self.pr_dir.mkdir()
        self.agents_json = self.root / "agents.json"
        self._stub("gh", GH_STUB)
        self._stub("claude", CLAUDE_STUB)
        self.env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("GT_LABEL", "GH_", "CLAUDE_")) and k not in _STRIP
        }
        self.env.update(
            HOME=str(self.home),
            PATH=f"{self.bin}:{os.path.expanduser('~/.pyenv/shims')}:/usr/bin:/bin",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
            GH_PR_DIR=str(self.pr_dir), CLAUDE_AGENTS_JSON=str(self.agents_json),
        )
        self._layout()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _stub(self, name, body):
        p = self.bin / name
        p.write_text(body)
        p.chmod(0o755)

    # ---- fixtures ----------------------------------------------------------

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], env=self.env,
                              capture_output=True, check=True).stdout.decode().strip()

    def _layout(self):
        self.origin = self.root / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(self.origin)],
                       env=self.env, check=True)
        self.repo = self.root / "repo-x"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.repo)],
                       env=self.env, check=True, capture_output=True)
        self.commit(self.repo, "init")
        self.git(self.repo, "push", "-q", "origin", "main")
        self.git(self.repo, "symbolic-ref", "refs/remotes/origin/HEAD",
                 "refs/remotes/origin/main")

    def commit(self, wt, name):
        (Path(wt) / f"{name}.txt").write_text(name)
        self.git(wt, "add", "-A")
        self.git(wt, "commit", "-qm", name)

    def worktree(self, branch, pushed=True):
        wt = self.root / branch
        self.git(self.repo, "worktree", "add", "-q", "-b", branch, str(wt), "main")
        self.commit(wt, branch)
        if pushed:
            self.git(wt, "push", "-q", "-u", "origin", branch)
        return wt

    def merge_into_main(self, branch, squash=False):
        """Land <branch> on origin/main; return the commit the PR would report."""
        self.git(self.repo, "fetch", "-q", "origin")
        if squash:
            self.git(self.repo, "merge", "-q", "--squash", branch)
            self.git(self.repo, "commit", "-qm", f"squash {branch}")
        else:
            self.git(self.repo, "merge", "-q", "--no-ff", "-m", f"merge {branch}", branch)
        self.git(self.repo, "push", "-q", "origin", "main")
        return self.git(self.repo, "rev-parse", "HEAD")

    def set_pr(self, branch, state, merge_commit="", head=None, number=1):
        head = head or self.git(self.repo, "rev-parse", f"refs/heads/{branch}")
        data = [{"number": number, "state": state, "mergedAt": None,
                 "mergeCommit": {"oid": merge_commit} if merge_commit else None,
                 "headRefOid": head, "baseRefName": "main"}]
        (self.pr_dir / f"{branch}.json").write_text(json.dumps(data))

    def merged_branch(self, name, squash=False, pushed=True):
        wt = self.worktree(name, pushed=pushed)
        head = self.git(wt, "rev-parse", "HEAD")
        mc = self.merge_into_main(name, squash=squash)
        self.set_pr(name, "MERGED", mc, head=head)
        return wt

    def set_sessions(self, *cwds):
        self.agents_json.write_text(json.dumps([{"cwd": str(c), "state": "idle"}
                                                for c in cwds]))

    # ---- running ------------------------------------------------------------

    def run_prune(self, *args, cwd=None):
        return subprocess.run([PRUNE, "--repo", str(self.repo), *args],
                              cwd=str(cwd or self.repo), env=self.env,
                              capture_output=True, check=False)

    def out(self, *args):
        r = self.run_prune(*args)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        return r.stdout.decode()

    def out_from(self, cwd):
        return self.run_prune(cwd=cwd).stdout.decode()

    def branches(self):
        return self.git(self.repo, "branch", "--format=%(refname:short)").split()


class Report(Base):

    def test_merge_commit_pr_is_removable(self):
        wt = self.merged_branch("feature-a")
        out = self.out()
        self.assertIn("DRY RUN", out)
        line = next(l for l in out.splitlines() if l.startswith("REMOVE"))
        self.assertIn("feature-a", line)
        self.assertIn(str(wt), line)
        self.assertIn("PR #1 merged", line)
        self.assertTrue(wt.is_dir())

    def test_squash_pr_is_removable(self):
        self.merged_branch("feature-b", squash=True)
        line = next(l for l in self.out().splitlines() if l.startswith("REMOVE"))
        self.assertIn("squash/rebase-merged", line)

    def test_unmerged_pr_is_skipped(self):
        self.worktree("feature-c")
        self.set_pr("feature-c", "OPEN")
        self.assertRegex(self.out(), r"SKIP .*feature-c.*PR not merged")

    def test_no_pr_is_skipped_even_if_ancestor_of_base(self):
        wt = self.root / "fresh"
        self.git(self.repo, "worktree", "add", "-q", "-b", "fresh", str(wt), "main")
        self.assertRegex(self.out(), r"SKIP .*fresh.*no PR found")

    def test_dirty_is_skipped(self):
        wt = self.merged_branch("feature-d")
        (wt / "scratch.txt").write_text("x")
        self.assertRegex(self.out(), r"SKIP .*feature-d.*uncommitted changes")

    def test_unpushed_commit_is_skipped(self):
        wt = self.merged_branch("feature-e")
        self.commit(wt, "late-work")
        self.assertRegex(self.out(), r"SKIP .*feature-e.*unpushed")

    def test_primary_worktree_never_listed_as_removable(self):
        self.set_pr("main", "MERGED", self.git(self.repo, "rev-parse", "HEAD"))
        out = self.out()
        self.assertRegex(out, r"SKIP .*main.*primary worktree")
        self.assertNotIn("REMOVE", out)

    def test_base_branch_worktree_is_skipped(self):
        wt = self.root / "base-copy"
        self.git(self.repo, "worktree", "add", "-q", "--detach", str(wt))
        self.git(wt, "switch", "-q", "-C", "main2")
        self.assertNotIn("REMOVE", self.out())

    def test_deploy_clone_is_skipped(self):
        deploy = self.home / ".local" / "share" / "chezmoi"
        deploy.parent.mkdir(parents=True)
        self.git(self.repo, "worktree", "add", "-q", "-b", "deploy-b", str(deploy), "main")
        self.set_pr("deploy-b", "MERGED", self.git(self.repo, "rev-parse", "main"))
        self.assertRegex(self.out(), r"SKIP .*deploy-b.*chezmoi deploy clone")

    def test_active_session_inside_worktree_is_skipped(self):
        wt = self.merged_branch("feature-f")
        self.set_sessions(wt / "subdir")
        self.assertRegex(self.out(), r"SKIP .*feature-f.*active Claude session")

    def test_session_in_other_dir_does_not_block(self):
        self.merged_branch("feature-g")
        self.set_sessions(self.root / "elsewhere")
        self.assertIn("REMOVE", self.out())

    def test_session_check_failure_skips_everything(self):
        self.merged_branch("feature-h")
        self.env["CLAUDE_STUB_RC"] = "1"
        out = self.out()
        self.assertRegex(out, r"SKIP .*feature-h.*session check unavailable")
        self.assertNotIn("REMOVE", out)

    def test_missing_claude_skips_everything(self):
        self.merged_branch("feature-i")
        (self.bin / "claude").unlink()
        self.assertRegex(self.out(), r"SKIP .*feature-i.*session check unavailable")

    def test_other_repo_arg_does_not_remove_invocation_worktree(self):
        wt = self.merged_branch("feature-a")
        for flag in ([], ["--yes"]):
            r = subprocess.run([PRUNE, "--repo", str(self.repo), *flag], cwd=str(wt),
                               env=self.env, capture_output=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr.decode())
            self.assertTrue(wt.is_dir())
        self.assertRegex(self.out_from(wt),
                         r"SKIP .*feature-a.*worktree the tool is running from")

    def test_prunable_worktree_is_reported(self):
        wt = self.merged_branch("feature-p")
        shutil.rmtree(wt)
        self.assertRegex(self.out(), r"SKIP .*feature-p.*stale registration")

    def test_malformed_session_list_skips_everything(self):
        self.merged_branch("feature-m")
        for payload in ('{"cwd": "/x"}', '["x"]', '[{"cwd": 5}]'):
            with self.subTest(payload):
                self.agents_json.write_text(payload)
                out = self.out()
                self.assertRegex(out, r"SKIP .*feature-m.*session check unavailable")

    def test_locked_worktree_is_skipped(self):
        wt = self.merged_branch("feature-j")
        self.git(self.repo, "worktree", "lock", str(wt))
        self.assertRegex(self.out(), r"SKIP .*feature-j.*locked")

    def test_merged_branch_without_worktree_is_listed(self):
        wt = self.merged_branch("feature-k")
        self.git(self.repo, "worktree", "remove", str(wt))
        self.assertRegex(self.out(), r"REMOVE .*feature-k\t\(no worktree\)")

    def test_deploy_clone_repo_lists_no_branch_candidates(self):
        wt = self.merged_branch("feature-m")
        self.git(self.repo, "worktree", "remove", str(wt))
        self.env["CHEZMOI_SOURCE_DIR"] = str(self.repo)
        self.assertNotIn("feature-m", self.out())

    def test_remote_branch_listed_not_deleted_without_flag(self):
        self.merged_branch("feature-l")
        out = self.out()
        self.assertIn("origin/feature-l exists", out)
        self.assertIn("--delete-remote", out)


class Removal(Base):

    def test_dry_run_changes_nothing(self):
        wt = self.merged_branch("feature-a")
        self.out()
        self.assertTrue(wt.is_dir())
        self.assertIn("feature-a", self.branches())

    def test_yes_removes_worktree_and_branch(self):
        wt = self.merged_branch("feature-a")
        out = self.out("--yes")
        self.assertRegex(out, r"REMOVED .*feature-a")
        self.assertFalse(wt.exists())
        self.assertNotIn("feature-a", self.branches())

    def test_yes_removes_squash_merged_branch_after_pr_proof(self):
        wt = self.merged_branch("feature-b", squash=True)
        self.out("--yes")
        self.assertFalse(wt.exists())
        self.assertNotIn("feature-b", self.branches())

    def test_yes_keeps_remote_without_flag(self):
        self.merged_branch("feature-a")
        self.out("--yes")
        remote = self.git(self.repo, "ls-remote", "--heads", "origin", "feature-a")
        self.assertIn("feature-a", remote)

    def test_delete_remote_flag_deletes_remote_branch(self):
        self.merged_branch("feature-a")
        self.out("--yes", "--delete-remote")
        self.assertEqual(self.git(self.repo, "ls-remote", "--heads", "origin", "feature-a"), "")

    def test_delete_remote_requires_yes(self):
        r = self.run_prune("--delete-remote")
        self.assertEqual(r.returncode, 1)

    def test_yes_leaves_skipped_worktrees_alone(self):
        dirty = self.merged_branch("feature-d")
        (dirty / "scratch.txt").write_text("x")
        open_wt = self.worktree("feature-c")
        self.set_pr("feature-c", "OPEN")
        self.out("--yes")
        self.assertTrue(dirty.is_dir())
        self.assertTrue(open_wt.is_dir())

    def test_running_from_a_candidate_worktree_keeps_it(self):
        wt = self.merged_branch("feature-a")
        r = subprocess.run([PRUNE, "--yes"], cwd=str(wt), env=self.env,
                           capture_output=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertTrue(wt.is_dir())

    def test_delete_remote_keeps_branch_whose_remote_tip_moved(self):
        wt = self.merged_branch("feature-a")
        other = self.root / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(other)],
                       env=self.env, check=True, capture_output=True)
        self.git(other, "checkout", "-q", "feature-a")
        self.commit(other, "later-work")
        self.git(other, "push", "-q", "origin", "feature-a")
        c = pw.Candidate(path=str(wt), branch="feature-a", verdict="ready",
                         remote_exists=True)
        status, msg = pw.remove_candidate(str(self.repo), c, True)
        self.assertEqual(status, "failed")
        self.assertIn("remote delete failed", msg)
        self.assertIn("feature-a", self.git(self.repo, "ls-remote", "--heads", "origin"))
        self.assertNotIn("feature-a", self.branches())

    def test_delete_remote_with_unknown_remote_state_removes_nothing(self):
        wt = self.merged_branch("feature-a")
        c = pw.Candidate(path=str(wt), branch="feature-a", verdict="ready",
                         remote_exists=None)
        status, msg = pw.remove_candidate(str(self.repo), c, True)
        self.assertEqual(status, "failed")
        self.assertIn("lookup failed", msg)
        self.assertTrue(wt.is_dir())
        self.assertIn("feature-a", self.branches())

    def test_remote_lookup_distinguishes_missing_from_failure(self):
        self.merged_branch("feature-a")
        self.assertIs(pw.remote_branch_exists(str(self.repo), "feature-a"), True)
        self.assertIs(pw.remote_branch_exists(str(self.repo), "nope"), False)
        self.git(self.repo, "remote", "set-url", "origin", str(self.root / "gone.git"))
        self.assertIsNone(pw.remote_branch_exists(str(self.repo), "feature-a"))

    def squash_without_upstream(self, name="feature-s"):
        """Squash-merged, never pushed: git -d refuses it."""
        return self.merged_branch(name, squash=True, pushed=False)

    def test_squash_without_upstream_keeps_branch_and_prints_hint(self):
        wt = self.squash_without_upstream()
        out = self.out("--yes")
        self.assertRegex(out, r"PARTIAL .*feature-s.*git branch -D feature-s")
        self.assertFalse(wt.exists())
        self.assertIn("feature-s", self.branches())

    def test_force_delete_flag_deletes_refused_branch(self):
        wt = self.squash_without_upstream()
        out = self.out("--yes", "--force-delete")
        self.assertRegex(out, r"REMOVED .*feature-s")
        self.assertFalse(wt.exists())
        self.assertNotIn("feature-s", self.branches())

    def test_force_delete_from_conf_key(self):
        self.squash_without_upstream()
        (self.repo / ".start-ticket.conf").write_text("prune_force_delete=true\n")
        self.out("--yes")
        self.assertNotIn("feature-s", self.branches())

    def test_conf_key_false_keeps_branch(self):
        self.squash_without_upstream()
        (self.repo / ".start-ticket.conf").write_text("prune_force_delete=false\n")
        self.out("--yes")
        self.assertIn("feature-s", self.branches())

    def test_dry_run_reports_force_delete_mode(self):
        self.assertIn("force-delete: off", self.out())
        self.assertIn("force-delete: on", self.out("--force-delete"))

    def test_force_delete_is_pinned_to_the_verified_tip(self):
        wt = self.squash_without_upstream()
        stale_tip = self.git(self.repo, "rev-parse", "feature-s")
        self.git(wt, "commit", "-q", "--allow-empty", "-m", "late")
        c = pw.Candidate(path=str(wt), branch="feature-s", verdict="ready",
                         tip=stale_tip)
        status, msg = pw.remove_candidate(str(self.repo), c, False, True)
        self.assertEqual(status, "failed")
        self.assertIn("feature-s", self.branches())

    def test_force_delete_clears_branch_config(self):
        self.squash_without_upstream()
        self.git(self.repo, "config", "branch.feature-s.note", "x")
        self.out("--yes", "--force-delete")
        self.assertEqual(
            subprocess.run(["git", "-C", str(self.repo), "config", "--get-regexp",
                            "branch.feature-s"], env=self.env,
                           capture_output=True).stdout, b"")

    def test_delete_error_other_than_unmerged_never_forces(self):
        self.merged_branch("feature-a")  # still checked out, so -d fails differently
        c = pw.Candidate(path="", branch="feature-a", verdict="ready",
                         tip=self.git(self.repo, "rev-parse", "feature-a"))
        status, _ = pw.remove_candidate(str(self.repo), c, False, True)
        self.assertEqual(status, "failed")
        self.assertIn("feature-a", self.branches())

    def test_remove_candidate_refuses_without_proof(self):
        wt = self.worktree("feature-c")
        c = pw.Candidate(path=str(wt), branch="feature-c", verdict="not-merged")
        status, _ = pw.remove_candidate(str(self.repo), c, False)
        self.assertEqual(status, "failed")
        self.assertTrue(wt.is_dir())


class Help(Base):

    def test_help_documents_flags(self):
        out = self.out("--help")
        for flag in ("--yes", "--delete-remote", "--force-delete", "--repo",
                     "DRY RUN", "prune_force_delete"):
            self.assertIn(flag, out)


class Classify(unittest.TestCase):

    def ready(self, **kw):
        base = dict(path="/p", branch="b", verdict="ready", how="PR #1 merged")
        return pw.Candidate(**{**base, **kw})

    def test_ready_clean_candidate_is_removed(self):
        self.assertEqual(pw.classify(self.ready()), ("remove", "PR #1 merged"))

    def test_each_blocker_skips(self):
        cases = {
            "protected": dict(protected="primary worktree"),
            "session": dict(session="active"),
            "locked": dict(locked=True),
            "detached": dict(detached=True),
            "dirty": dict(dirty=True),
            "ahead": dict(ahead_of_upstream=2),
            "verdict": dict(verdict="not-merged"),
        }
        for name, kw in cases.items():
            with self.subTest(name):
                self.assertEqual(pw.classify(self.ready(**kw))[0], "skip")

    def test_protected_reason_wins_over_everything(self):
        c = self.ready(protected="primary worktree", dirty=True, session="active")
        self.assertEqual(pw.classify(c), ("skip", "primary worktree"))

    def test_parse_worktrees_marks_first_primary_and_flags(self):
        text = ("worktree /r\nHEAD abc\nbranch refs/heads/main\n\n"
                "worktree /r2\nHEAD def\nbranch refs/heads/feat\nlocked reason\n\n"
                "worktree /r3\nHEAD ghi\ndetached\n\n")
        wts = pw.parse_worktrees(text)
        self.assertEqual([w.path for w in wts], ["/r", "/r2", "/r3"])
        self.assertTrue(wts[0].primary)
        self.assertFalse(wts[1].primary)
        self.assertTrue(wts[1].locked)
        self.assertEqual(wts[1].branch, "feat")
        self.assertTrue(wts[2].detached)

    def test_parse_worktrees_skips_bare_container_for_primary(self):
        text = ("worktree /c\nbare\n\n"
                "worktree /c/main\nHEAD a\nbranch refs/heads/main\n\n"
                "worktree /c/feat\nHEAD b\nbranch refs/heads/feat\n\n")
        wts = pw.parse_worktrees(text)
        self.assertEqual([w.primary for w in wts], [False, True, False])

    def test_recheck_rejects_worktree_whose_branch_changed(self):
        c = pw.Candidate(path="/p", branch="old", verdict="ready")
        wt = pw.Worktree(path="/p", branch="new")
        orig = pw.list_worktrees
        pw.list_worktrees = lambda repo: [wt]
        try:
            fresh = pw.recheck("/r", c)
        finally:
            pw.list_worktrees = orig
        self.assertEqual(pw.classify(fresh)[0], "skip")


if __name__ == "__main__":
    unittest.main()
