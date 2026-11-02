"""Tests for sibling-worktrees.sh — the TAB-separated records /open-pr parses.

Written against the bash implementation and kept green through the port to
tools/lib/sibling_worktrees.py: the entry-point filename, stdout bytes, and
exit codes are the contract. Fixtures are throwaway repos under a dev-root
mirroring the worktree-manager layout; no network, no gh.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SIBLING = os.path.join(TOOLS, "sibling-worktrees.sh")

_STRIP = ("PROJECT_OVERLAYS_DIR", "GIT_TOOLS_PROJECTS_DIR", "CHEZMOI_SOURCE_DIR",
          "XDG_STATE_HOME", "WF_TELEMETRY", "WF_TELEMETRY_LOG",
          "CLAUDE_CODE_SESSION_ID", "CLAUDE_JOB_DIR")


class Base(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="sib-test.")))
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("GT_LABEL", "GH_")) and k not in _STRIP
        }
        self.env.update(
            HOME=str(self.home),
            PATH=f"{os.path.expanduser('~/.pyenv/shims')}:/usr/bin:/bin",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
        )
        self._layout()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- fixtures ----------------------------------------------------------

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], env=self.env,
                              capture_output=True, check=True).stdout.decode().strip()

    def run_git(self, *args):
        subprocess.run(["git", *args], env=self.env,
                       capture_output=True, check=True)

    def _worktree(self, repo, name, branch):
        wt = repo / name
        self.git(repo, "worktree", "add", "-q", "-b", branch, str(wt), "main")
        return wt

    def _layout(self):
        dev = self.root / "dev"
        dev.mkdir()
        # repoA — the repo we stand in (its own 7-ticket worktree must not match)
        self.repoA = dev / "repoA"
        self.run_git("init", "-q", "-b", "main", str(self.repoA))
        self.git(self.repoA, "commit", "-q", "--allow-empty", "-m", "init")
        self.a7 = self._worktree(self.repoA, "a7", "7-first-ticket")
        # repoB — full clone with origin/main; one worktree per state
        origin = self.root / "originB.git"
        self.run_git("init", "--bare", "-q", "-b", "main", str(origin))
        self.repoB = dev / "repoB"
        self.run_git("clone", "-q", str(origin), str(self.repoB))
        (self.repoB / "README.md").write_text("x\n")
        self.git(self.repoB, "add", "-A")
        self.git(self.repoB, "commit", "-qm", "init")
        self.git(self.repoB, "push", "-q", "origin", "main")
        self.git(self.repoB, "symbolic-ref", "refs/remotes/origin/HEAD",
                 "refs/remotes/origin/main")
        self.b7 = self._worktree(self.repoB, "b7", "7-first-ticket")
        (self.b7 / "dirty.txt").write_text("d\n")
        self.b8 = self._worktree(self.repoB, "b8", "8-clean-branch")
        self.b9 = self._worktree(self.repoB, "b9", "9-second-ticket")
        self.git(self.b9, "commit", "-q", "--allow-empty", "-m", "work")
        self.b10 = self._worktree(self.repoB, "b10", "10-fourth-ticket")
        self.git(self.b10, "commit", "-q", "--allow-empty", "-m", "work")
        (self.b10 / "dirty.txt").write_text("d\n")
        # repoC — a plain directory: scanned, skipped
        (dev / "repoC").mkdir()
        # repoD — git repo with no origin: no base ref, so ahead by design
        self.repoD = dev / "repoD"
        self.run_git("init", "-q", "-b", "main", str(self.repoD))
        self.git(self.repoD, "commit", "-q", "--allow-empty", "-m", "init")
        self.d7 = self._worktree(self.repoD, "d7", "7-first-ticket")
        self.dsc = self._worktree(self.repoD, "dsc", "sc-1/x-sc-2/y")

    # ---- running ------------------------------------------------------------

    def run_sib(self, *args, cwd=None):
        return subprocess.run([SIBLING, *args], cwd=str(cwd or self.a7),
                              env=self.env, capture_output=True, check=False)

    def line(self, repo_name, wt, branch, state):
        return f"{repo_name}\t{wt}\t{branch}\t{state}\n"


class Scan(Base):

    def test_scan_sorted_and_self_excluded(self):
        r = self.run_sib()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            r.stdout.decode(),
            self.line("repoB", str(self.b7), "7-first-ticket", "dirty")
            + self.line("repoD", str(self.d7), "7-first-ticket", "ahead"),
        )
        self.assertNotIn("repoA", r.stdout.decode())

    def test_ahead_and_dirty_ahead_states(self):
        r = self.run_sib("--ticket", "9")
        self.assertEqual(r.stdout.decode(),
                         self.line("repoB", str(self.b9), "9-second-ticket", "ahead"))
        r = self.run_sib("--ticket", "10")
        self.assertEqual(r.stdout.decode(),
                         self.line("repoB", str(self.b10), "10-fourth-ticket", "dirty+ahead"))

    def test_clean_omitted_unless_flagged(self):
        r = self.run_sib("--ticket", "8")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"")
        r = self.run_sib("--ticket", "8", "--include-clean")
        self.assertEqual(r.stdout.decode(),
                         self.line("repoB", str(self.b8), "8-clean-branch", "clean"))

    def test_no_matches_is_empty_rc0(self):
        r = self.run_sib("--ticket", "99")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"")

    def test_root_flag(self):
        r = self.run_sib("--ticket", "7", "--root", str(self.root / "dev"))
        self.assertEqual(
            r.stdout.decode(),
            self.line("repoB", str(self.b7), "7-first-ticket", "dirty")
            + self.line("repoD", str(self.d7), "7-first-ticket", "ahead"),
        )

    def test_hidden_dot_dirs_are_not_scanned(self):
        # bash's "$root"/*/ glob skipped dotfiles; a hidden repo under the
        # dev root must not gain a shipped session.
        hidden = self.root / "dev" / ".hidden-repo"
        self.run_git("init", "-q", "-b", "main", str(hidden))
        self.git(hidden, "commit", "-q", "--allow-empty", "-m", "init")
        self._worktree(hidden, "h7", "7-first-ticket")
        r = self.run_sib("--ticket", "7")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(".hidden-repo", r.stdout.decode())


class TicketResolution(Base):

    def test_ticket_from_current_branch(self):
        r = self.run_sib()
        self.assertIn(self.line("repoB", str(self.b7), "7-first-ticket", "dirty"),
                      r.stdout.decode())

    # Standing in a worktree inside a family dir (the layout the root heuristic
    # assumes); the family main checkout would put the scan root one level too high.
    def test_branch_flag_resolves_ticket(self):
        r = self.run_sib("--branch", "7-first-ticket", cwd=self.b9)
        # standing in repoB → repoB excluded; repoA's and repoD's worktrees match
        self.assertEqual(
            r.stdout.decode(),
            self.line("repoA", str(self.a7), "7-first-ticket", "ahead")
            + self.line("repoD", str(self.d7), "7-first-ticket", "ahead"),
        )

    def test_last_sc_id_in_branch_wins(self):
        r = self.run_sib("--branch", "sc-1/x-sc-2/y", cwd=self.b9)
        self.assertEqual(r.stdout.decode(),
                         self.line("repoD", str(self.dsc), "sc-1/x-sc-2/y", "ahead"))

    def test_ticket_flag(self):
        r = self.run_sib("--ticket", "7", cwd=self.b9)
        self.assertEqual(
            r.stdout.decode(),
            self.line("repoA", str(self.a7), "7-first-ticket", "ahead")
            + self.line("repoD", str(self.d7), "7-first-ticket", "ahead"),
        )


class ReposCsv(Base):

    def test_family_dir_entry(self):
        r = self.run_sib("--ticket", "7", "--repos", str(self.repoB))
        self.assertEqual(r.stdout.decode(),
                         self.line("repoB", str(self.b7), "7-first-ticket", "dirty"))

    def test_worktree_path_entry_resolves_to_family(self):
        # The record's repo name is the basename of the given entry.
        r = self.run_sib("--ticket", "7", "--repos", str(self.b7))
        self.assertEqual(r.stdout.decode(),
                         self.line("b7", str(self.b7), "7-first-ticket", "dirty"))

    def test_non_directory_entry_is_rc1(self):
        r = self.run_sib("--ticket", "7", "--repos", str(self.root / "nope"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a directory", r.stderr.decode())


class Errors(Base):

    def test_not_a_repo(self):
        r = self.run_sib(cwd=self.home)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not inside a git repo", r.stderr.decode())

    def test_detached_head_needs_ticket(self):
        self.git(self.a7, "checkout", "-q", "--detach")
        r = self.run_sib()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not on a branch", r.stderr.decode())

    def test_unparseable_branch(self):
        r = self.run_sib(cwd=self.repoB)
        self.assertEqual(r.returncode, 1)
        self.assertIn("can't parse a ticket id", r.stderr.decode())

    def test_ticket_must_be_positive_integer(self):
        r = self.run_sib("--ticket", "abc")
        self.assertEqual(r.returncode, 1)
        self.assertIn("positive integer", r.stderr.decode())

    def test_empty_flag_value_is_usage_error(self):
        # bash's ${2:?} rejected an empty value like a missing one; falling
        # through would silently parse the ticket from the current branch.
        for flag in ("--ticket", "--branch", "--root", "--repos"):
            r = self.run_sib(flag, "")
            self.assertEqual(r.returncode, 1, flag)
            self.assertIn(f"{flag} needs a value", r.stderr.decode())


if __name__ == "__main__":
    unittest.main()
