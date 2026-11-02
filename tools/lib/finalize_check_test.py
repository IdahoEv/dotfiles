"""Tests for finalize-check.sh — the key=value report /finalize parses.

Written against the bash implementation and kept green through the port to
tools/lib/finalize_check.py: the entry-point filename, stdout bytes, and
exit codes are the contract. Fixtures are throwaway repos with a local bare
origin; `gh` is a PATH stub whose JSON comes from $GH_PR_JSON, so every PR
state is reachable without network.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
FINALIZE = os.path.join(TOOLS, "finalize-check.sh")

KEYS = [
    "branch", "ticket_id", "chain_ids", "ticket_scheme", "base", "base_source",
    "pr_number", "pr_state", "pr_merge_commit", "pr_head_oid", "pr_count",
    "pr_open_other", "head_oid", "head_matches", "merged",
    "merge_commit_landed", "base_fetch", "shallow", "tracking_refspec",
    "base_worktree", "worktree", "verdict", "agent_phase", "dotfiles_repo",
    "deploy_root", "deploy_branch", "deploy_dirty_files", "deploy_pull_rebase",
]

# Unfetchable by construction: no fixture ever contains it.
FAKE_SHA = "0123456789abcdef0123456789abcdef01234567"

GH_STUB = """#!/usr/bin/env bash
[ -n "${GH_STUB_RC:-}" ] && exit "$GH_STUB_RC"
case "$1 $2" in
  "pr list") [ -f "${GH_PR_JSON:-}" ] && cat "${GH_PR_JSON}" ;;
  *) exit 0 ;;
esac
"""

_STRIP = ("PROJECT_OVERLAYS_DIR", "GIT_TOOLS_PROJECTS_DIR", "CHEZMOI_SOURCE_DIR",
          "XDG_STATE_HOME", "WF_TELEMETRY", "WF_TELEMETRY_LOG",
          "CLAUDE_CODE_SESSION_ID", "CLAUDE_JOB_DIR")


class Base(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="fcheck-test.")))
        self.home = self.root / "home"
        self.home.mkdir()
        bin_ = self.root / "bin"
        bin_.mkdir()
        (bin_ / "gh").write_text(GH_STUB)
        os.chmod(bin_ / "gh", 0o755)
        self.bin = str(bin_)
        self.env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("GT_LABEL", "GH_")) and k not in _STRIP
        }
        self.env.update(
            HOME=str(self.home),
            PATH=f"{self.bin}:{os.path.expanduser('~/.pyenv/shims')}:/usr/bin:/bin",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
        )
        self.pr_json = self.root / "pr.json"
        self.env["GH_PR_JSON"] = str(self.pr_json)
        self.set_pr()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- fixtures ----------------------------------------------------------

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], env=self.env,
                              capture_output=True, check=True).stdout.decode().strip()

    def run_git(self, *args):
        subprocess.run(["git", *args], env=self.env,
                       capture_output=True, check=True)

    def set_pr(self, *prs):
        self.pr_json.write_text(json.dumps(list(prs)))

    @staticmethod
    def pr(number, state, head, base="main", merge=None):
        return {"number": number, "state": state, "mergedAt": None,
                "mergeCommit": ({"oid": merge} if merge else None),
                "headRefOid": head, "baseRefName": base}

    def repo_with_wt(self, branch="7-first-ticket"):
        """Bare origin + clone (main, pushed) + worktree on <branch> with one commit."""
        origin = self.root / "origin.git"
        self.run_git("init", "--bare", "-q", "-b", "main", str(origin))
        repo = self.root / "repo"
        self.run_git("clone", "-q", str(origin), str(repo))
        (repo / "README.md").write_text("x\n")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-qm", "init")
        self.git(repo, "push", "-q", "origin", "main")
        self.git(repo, "symbolic-ref", "refs/remotes/origin/HEAD",
                 "refs/remotes/origin/main")
        wt = self.root / "wt"
        self.git(repo, "worktree", "add", "-q", "-b", branch, str(wt), "main")
        (wt / "work.txt").write_text("w\n")
        self.git(wt, "add", "-A")
        self.git(wt, "commit", "-qm", "work")
        return repo, wt

    def merge_branch(self, repo, branch="7-first-ticket"):
        """Merge <branch> into main, push; returns the merge commit sha."""
        self.git(repo, "merge", "--no-ff", "-m", f"merge {branch}", branch)
        merge_sha = self.git(repo, "rev-parse", "HEAD")
        self.git(repo, "push", "-q", "origin", "main")
        return merge_sha

    # ---- running ------------------------------------------------------------

    def run_check(self, *args, cwd=None, env=None):
        e = dict(self.env)
        e.update(env or {})
        return subprocess.run([FINALIZE, *args], cwd=str(cwd or self.root),
                              env=e, capture_output=True, check=False)

    def facts(self, r):
        lines = r.stdout.decode().splitlines()
        pairs = [line.split("=", 1) for line in lines]
        self.assertEqual([k for k, _ in pairs], KEYS)
        return {k: v for k, v in pairs}


class PrQuery(Base):

    def test_no_pr(self):
        repo, wt = self.repo_with_wt()
        r = self.run_check("--dir", str(wt))
        f = self.facts(r)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(f["pr_state"], "none")
        self.assertEqual(f["pr_count"], "0")
        self.assertEqual(f["pr_number"], "")
        self.assertEqual(f["base"], "main")
        self.assertEqual(f["base_source"], "default")
        self.assertEqual(f["base_worktree"], str(repo))
        self.assertEqual(f["merged"], "no")
        self.assertEqual(f["verdict"], "no-pr")

    def test_gh_failure_is_unknown_not_no_pr(self):
        repo, wt = self.repo_with_wt()
        r = self.run_check("--dir", str(wt), env={"GH_STUB_RC": "1"})
        f = self.facts(r)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(f["pr_state"], "unknown")
        self.assertEqual(f["verdict"], "unknown")

    def test_no_gh_binary_is_unknown(self):
        repo, wt = self.repo_with_wt()
        no_gh = f"{os.path.expanduser('~/.pyenv/shims')}:/usr/bin:/bin"
        r = self.run_check("--dir", str(wt), env={"PATH": no_gh})
        f = self.facts(r)
        self.assertEqual(f["pr_state"], "unknown")
        self.assertEqual(f["verdict"], "unknown")

    def test_garbage_json_is_unknown(self):
        repo, wt = self.repo_with_wt()
        self.pr_json.write_text("proxy interstitial, not JSON")
        r = self.run_check("--dir", str(wt))
        f = self.facts(r)
        self.assertEqual(f["pr_count"], "0")
        self.assertEqual(f["pr_state"], "unknown")
        self.assertEqual(f["verdict"], "unknown")

    def test_merged_pr_wins_over_higher_numbered_closed(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        merge_sha = self.merge_branch(repo)
        self.set_pr(self.pr(5, "CLOSED", head=tip),
                    self.pr(3, "MERGED", head=tip, merge=merge_sha))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["pr_number"], "3")
        self.assertEqual(f["pr_count"], "2")
        self.assertEqual(f["pr_state"], "MERGED")
        self.assertEqual(f["pr_open_other"], "")
        self.assertEqual(f["verdict"], "ready")

    def test_open_other_pr_forces_not_merged(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        merge_sha = self.merge_branch(repo)
        self.set_pr(self.pr(3, "MERGED", head=tip, merge=merge_sha),
                    self.pr(5, "OPEN", head=tip))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["pr_number"], "3")
        self.assertEqual(f["pr_open_other"], "5")
        self.assertEqual(f["verdict"], "not-merged")
        self.assertEqual(f["agent_phase"], "REVIEW")


class Verdicts(Base):

    def test_open_pr_not_merged(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        self.set_pr(self.pr(3, "OPEN", head=tip))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["base_source"], "pr")
        self.assertEqual(f["head_matches"], "same")
        self.assertEqual(f["merged"], "no")
        self.assertEqual(f["merge_commit_landed"], "unknown")
        self.assertEqual(f["verdict"], "not-merged")
        self.assertEqual(f["agent_phase"], "REVIEW")

    def test_merged_ready_full_report(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        merge_sha = self.merge_branch(repo)
        self.set_pr(self.pr(3, "MERGED", head=tip, merge=merge_sha))
        r = self.run_check("--dir", str(wt))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.facts(r), {
            "branch": "7-first-ticket", "ticket_id": "7", "chain_ids": "7",
            "ticket_scheme": "github", "base": "main", "base_source": "pr",
            "pr_number": "3", "pr_state": "MERGED",
            "pr_merge_commit": merge_sha, "pr_head_oid": tip,
            "pr_count": "1", "pr_open_other": "",
            "head_oid": tip, "head_matches": "same", "merged": "yes",
            "merge_commit_landed": "yes", "base_fetch": "ok", "shallow": "no",
            "tracking_refspec": "ok", "base_worktree": str(repo),
            "worktree": str(wt), "verdict": "ready", "agent_phase": "MERGED",
            "dotfiles_repo": "no", "deploy_root": "", "deploy_branch": "",
            "deploy_dirty_files": "", "deploy_pull_rebase": "",
        })

    def test_squash_merged_provable_is_ready(self):
        repo, wt = self.repo_with_wt()
        (wt / "more.txt").write_text("m\n")
        self.git(wt, "add", "-A")
        self.git(wt, "commit", "-qm", "more")
        tip = self.git(wt, "rev-parse", "HEAD")
        # Squash merge: both branch commits land as one commit on main, so the
        # branch ref itself is not an ancestor.
        self.git(repo, "merge", "--squash", "7-first-ticket")
        self.git(repo, "commit", "-qm", "squash")
        squash_sha = self.git(repo, "rev-parse", "HEAD")
        self.git(repo, "push", "-q", "origin", "main")
        self.set_pr(self.pr(3, "MERGED", head=tip, merge=squash_sha))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["merged"], "no")
        self.assertEqual(f["merge_commit_landed"], "yes")
        self.assertEqual(f["verdict"], "ready")
        self.assertEqual(f["agent_phase"], "MERGED")

    def test_squash_merged_unproven(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        self.set_pr(self.pr(3, "MERGED", head=tip, merge=FAKE_SHA))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["merged"], "no")
        self.assertEqual(f["merge_commit_landed"], "unknown")
        self.assertEqual(f["base_fetch"], "ok")
        self.assertEqual(f["verdict"], "squash-merged")
        self.assertEqual(f["agent_phase"], "")

    def test_not_on_base(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        # Merge commit present locally, provably absent from origin/main.
        self.set_pr(self.pr(3, "MERGED", head=tip, merge=tip))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["merged"], "no")
        self.assertEqual(f["merge_commit_landed"], "no")
        self.assertEqual(f["base_fetch"], "ok")
        self.assertEqual(f["shallow"], "no")
        self.assertEqual(f["base_source"], "pr")
        self.assertEqual(f["verdict"], "not-on-base")
        self.assertEqual(f["agent_phase"], "")

    def test_not_on_base_needs_fresh_base(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        self.git(repo, "merge", "--no-ff", "-m", "merge", "7-first-ticket")
        # Same facts as not-on-base, but origin is unreachable: the base ref
        # could not be refreshed, so `no` is not proof.
        self.git(wt, "remote", "set-url", "origin", "ssh://git@localhost:1/acme/widgets")
        self.set_pr(self.pr(3, "MERGED", head=tip, merge=tip))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["base_fetch"], "failed")
        self.assertEqual(f["base_source"], "pr")
        self.assertEqual(f["verdict"], "squash-merged")

    def test_not_on_base_excluded_when_shallow(self):
        origin = self.root / "origin.git"
        self.run_git("init", "--bare", "-q", "-b", "main", str(origin))
        seed = self.root / "seed"
        self.run_git("clone", "-q", str(origin), str(seed))
        (seed / "README.md").write_text("x\n")
        self.git(seed, "add", "-A")
        self.git(seed, "commit", "-qm", "init")
        self.git(seed, "push", "-q", "origin", "main")
        # file:// forces the transport so --depth is honored (local paths ignore it)
        srepo = self.root / "srepo"
        self.run_git("clone", "-q", "--depth", "1", f"file://{origin}", str(srepo))
        self.git(srepo, "checkout", "-q", "-b", "7-first-ticket")
        self.git(srepo, "commit", "-q", "--allow-empty", "-m", "work")
        tip = self.git(srepo, "rev-parse", "HEAD")
        self.set_pr(self.pr(3, "MERGED", head=tip, merge=tip))
        f = self.facts(self.run_check("--dir", str(srepo)))
        self.assertEqual(f["shallow"], "yes")
        self.assertEqual(f["base_fetch"], "ok")
        self.assertEqual(f["verdict"], "squash-merged")

    def test_pr_base_gone_falls_back_to_default(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        # base "gone" matches no ref on origin → ls-remote rc 2 → default used
        self.set_pr(self.pr(3, "MERGED", head=tip, merge=tip, base="gone"))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["base"], "main")
        self.assertEqual(f["base_source"], "default_pr_base_gone")
        self.assertEqual(f["verdict"], "squash-merged")

    def test_pr_base_used_when_set(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        self.git(repo, "push", "-q", "origin", "main:refs/heads/release/1.0")
        self.set_pr(self.pr(3, "OPEN", head=tip, base="release/1.0"))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["base"], "release/1.0")
        self.assertEqual(f["base_source"], "pr")
        self.assertEqual(f["base_fetch"], "ok")
        self.assertEqual(f["merged"], "no")
        self.assertEqual(f["base_worktree"], "")
        self.assertEqual(f["verdict"], "not-merged")


class HeadMatches(Base):

    def test_ahead_is_local_commits(self):
        repo, wt = self.repo_with_wt()
        first = self.git(wt, "rev-parse", "HEAD")
        (wt / "more.txt").write_text("m\n")
        self.git(wt, "add", "-A")
        self.git(wt, "commit", "-qm", "more")
        tip = self.git(wt, "rev-parse", "HEAD")
        merge_sha = self.merge_branch(repo)
        self.set_pr(self.pr(3, "MERGED", head=first, merge=merge_sha))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["head_matches"], "ahead")
        self.assertEqual(f["verdict"], "local-commits")

    def test_diverged_is_local_commits(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        merge_sha = self.merge_branch(repo)
        self.git(wt, "reset", "-q", "--hard", "HEAD~1")
        self.git(wt, "commit", "-q", "--allow-empty", "-m", "different")
        self.set_pr(self.pr(3, "MERGED", head=tip, merge=merge_sha))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["head_matches"], "diverged")
        self.assertEqual(f["verdict"], "local-commits")

    def test_behind_is_ready_with_fetch_retry(self):
        repo, wt = self.repo_with_wt()
        first = self.git(wt, "rev-parse", "HEAD")
        merge_sha = self.merge_branch(repo)
        # A newer branch tip exists only on origin; the local branch is stale.
        tmp = self.root / "tmp"
        self.git(repo, "worktree", "add", "-q", "--detach", str(tmp), first)
        self.git(tmp, "commit", "-q", "--allow-empty", "-m", "elsewhere")
        newer = self.git(tmp, "rev-parse", "HEAD")
        self.git(tmp, "push", "-q", "origin", f"{newer}:refs/heads/7-first-ticket")
        self.git(repo, "worktree", "remove", "--force", str(tmp))
        self.set_pr(self.pr(3, "MERGED", head=newer, merge=merge_sha))
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["head_matches"], "behind")
        self.assertEqual(f["merged"], "yes")
        self.assertEqual(f["verdict"], "ready")

    def test_unfetchable_pr_head_is_unknown(self):
        repo, wt = self.repo_with_wt()
        tip = self.git(wt, "rev-parse", "HEAD")
        merge_sha = self.merge_branch(repo)
        self.set_pr(self.pr(3, "MERGED", head=FAKE_SHA, merge=merge_sha))
        r = self.run_check("--dir", str(wt))
        f = self.facts(r)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(f["head_matches"], "unknown")
        self.assertEqual(f["merged"], "yes")
        self.assertEqual(f["verdict"], "unknown")


class PreconditionsAndFacts(Base):

    def test_branch_flag_for_branch_without_local_ref(self):
        repo, wt = self.repo_with_wt()
        r = self.run_check("--dir", str(wt), "--branch", "9-ghost")
        f = self.facts(r)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(f["branch"], "9-ghost")
        self.assertEqual(f["ticket_id"], "9")
        self.assertEqual(f["head_oid"], "")
        self.assertEqual(f["verdict"], "unknown")

    def test_chain_ids_list_every_ticket(self):
        repo, wt = self.repo_with_wt()
        gitdir = self.git(wt, "rev-parse", "--absolute-git-dir")
        Path(gitdir, "chain").write_text("7\n8\n9\n")
        f = self.facts(self.run_check("--dir", str(wt)))
        self.assertEqual(f["ticket_id"], "7")
        self.assertEqual(f["chain_ids"], "7,8,9")

    def test_tracking_refspec_missing_warns_but_answers(self):
        repo, wt = self.repo_with_wt()
        self.git(wt, "config", "--unset", "remote.origin.fetch")
        r = self.run_check("--dir", str(wt))
        f = self.facts(r)
        self.assertEqual(f["tracking_refspec"], "missing")
        self.assertEqual(f["base_fetch"], "ok")
        self.assertEqual(f["verdict"], "no-pr")
        self.assertIn("remote.origin.fetch is unset", r.stderr.decode())

    def test_dotfiles_dev_reports_deploy_clone(self):
        repo, wt = self.repo_with_wt()
        (wt / ".chezmoiignore").write_text("")
        (wt / "dot_claude").mkdir()
        deploy = self.root / "deploy"
        self.run_git("init", "-q", "-b", "main", str(deploy))
        (deploy / "README.md").write_text("x\n")
        self.git(deploy, "add", "-A")
        self.git(deploy, "commit", "-qm", "init")
        (deploy / "local.txt").write_text("dirty\n")
        self.git(deploy, "config", "pull.rebase", "true")
        f = self.facts(self.run_check("--dir", str(wt),
                                      env={"CHEZMOI_SOURCE_DIR": str(deploy)}))
        self.assertEqual(f["dotfiles_repo"], "dev")
        self.assertEqual(f["deploy_root"], os.path.realpath(deploy))
        self.assertEqual(f["deploy_branch"], "main")
        self.assertEqual(f["deploy_dirty_files"], "1")
        self.assertEqual(f["deploy_pull_rebase"], "true")

    def test_dotfiles_deploy_clone_identifies_itself(self):
        repo, wt = self.repo_with_wt()
        (wt / "local.txt").write_text("dirty\n")
        f = self.facts(self.run_check("--dir", str(wt),
                                      env={"CHEZMOI_SOURCE_DIR": str(wt)}))
        self.assertEqual(f["dotfiles_repo"], "deploy")
        self.assertEqual(f["deploy_root"], os.path.realpath(wt))
        self.assertEqual(f["deploy_branch"], "7-first-ticket")
        self.assertEqual(f["deploy_dirty_files"], "1")
        self.assertEqual(f["deploy_pull_rebase"], "false")

    def test_telemetry_event_for_shortcut_branch(self):
        repo, wt = self.repo_with_wt(branch="sc-5/foo")
        r = self.run_check("--dir", str(wt))
        self.assertEqual(r.returncode, 0)
        log = self.home / ".local" / "state" / "workflow-telemetry" / "events.jsonl"
        events = [json.loads(line) for line in log.read_text().splitlines()]
        checks = [e for e in events if e.get("event") == "finalize.check"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["run_id"], "sc-5")
        self.assertEqual(checks[0]["ticket"], "5")
        self.assertEqual(checks[0]["branch"], "sc-5/foo")
        self.assertEqual(checks[0]["verdict"], "no-pr")

    def test_exit_1_on_preconditions(self):
        repo, wt = self.repo_with_wt()
        notrepo = self.root / "notrepo"
        notrepo.mkdir()
        r = self.run_check("--dir", str(notrepo))
        self.assertEqual(r.returncode, 1)
        self.assertIn("not inside a git repo", r.stderr.decode())

        r = self.run_check("--dir", str(wt), "--bogus")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown arg", r.stderr.decode())

        self.git(wt, "checkout", "-q", "--detach")
        r = self.run_check("--dir", str(wt))
        self.assertEqual(r.returncode, 1)
        self.assertIn("not on a branch", r.stderr.decode())


if __name__ == "__main__":
    unittest.main()
