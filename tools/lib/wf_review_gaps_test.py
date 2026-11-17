import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wf_review_gaps as gaps  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_git_repo(root):
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "remote", "add", "origin", "git@github.com:example/sample-app.git")


class TestMatchingAndDiffMapping(unittest.TestCase):
    def test_dedupes_local_findings_and_matches_similar_claim(self):
        events = [
            {
                "event": "review.finding", "source": "local", "reviewer": "correctness-reviewer",
                "finding_id": "r1-1", "round": 1, "path": "src/app.py", "line": 42,
                "claim": "src/app.py: parse_items crashes on empty input list",
            },
            {
                "event": "review.finding", "source": "local", "reviewer": "robustness-reviewer",
                "finding_id": "r1-1", "round": 1, "path": "src/app.py", "line": 42,
                "claim": "src/app.py: parse_items crashes on empty input list",
            },
        ]
        deduped = gaps._dedupe_local_findings(events)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["reviewers"], ["correctness-reviewer", "robustness-reviewer"])

        bot_match = {"path": "src/app.py", "line": 45, "sha": "", "claim": "src/app.py: parse_items fails when input list is empty"}
        self.assertIsNotNone(gaps.match_finding(bot_match, deduped, {}))

        bot_miss = {"path": "src/app.py", "line": 120, "sha": "", "claim": "src/app.py: timeout is never enforced"}
        self.assertIsNone(gaps.match_finding(bot_miss, deduped, {}))

    def test_line_mapping_across_shas_in_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_git_repo(repo)
            f = repo / "mod.py"
            f.write_text("a\nb\nc\nd\ne\n")
            _git(repo, "add", "mod.py")
            _git(repo, "commit", "-q", "-m", "r1")
            sha1 = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

            f.write_text("".join(f"pad{i}\n" for i in range(20)) + "a\nb\nc\nd\ne\n")
            _git(repo, "commit", "-q", "-am", "r2")
            sha2 = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

            local = [{"path": "mod.py", "line": 4, "round": 1, "sha": "", "claim": "mod.py: d is wrong"}]
            bot = {"path": "mod.py", "line": 24, "sha": sha2, "claim": "mod.py: d has wrong behavior"}
            self.assertIsNotNone(gaps.match_finding(bot, local, {1: sha1}, repo_dir=str(repo)))

    def test_pure_insertion_hunk_does_not_shift_preceding_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_git_repo(repo)
            f = repo / "mod.py"
            f.write_text("l1\nl2\nl3\nl4\nl5\n")
            _git(repo, "add", "mod.py")
            _git(repo, "commit", "-q", "-m", "r1")
            sha1 = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

            inserted = "".join(f"ins{i}\n" for i in range(20))
            f.write_text("l1\nl2\nl3\nl4\n" + inserted + "l5\n")
            _git(repo, "commit", "-q", "-am", "r2")
            sha2 = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

            self.assertEqual(gaps._map_line_via_diff(str(repo), sha1, sha2, "mod.py", 4), 4)
            self.assertEqual(gaps._map_line_via_diff(str(repo), sha1, sha2, "mod.py", 5), 25)


class TestDiffCoverageAndOverlay(unittest.TestCase):
    def test_diff_coverage_detects_post_review_commit_vs_in_reviewed_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_git_repo(repo)
            f = repo / "calc.py"
            f.write_text("def add(a, b):\n    return a + b\n")
            _git(repo, "add", "calc.py")
            _git(repo, "commit", "-q", "-m", "local round 1")
            sha1 = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

            f.write_text("def add(a, b):\n    return a + b\n\ndef div(a, b):\n    return a / b\n")
            _git(repo, "commit", "-q", "-am", "post-review commit")
            sha2 = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

            run_info = {"round_shas": {1: sha1}, "ran_reviewers": {"correctness-reviewer"}, "launches": [], "local_findings": []}

            post_bot = {"path": "calc.py", "line": 5, "sha": sha2, "claim": "calc.py: div does not guard zero denominator"}
            status1, _ = gaps.check_diff_coverage(post_bot, run_info, repo_dir=str(repo))
            self.assertEqual(status1, "code not in the diff the reviewer saw")

            in_bot = {"path": "calc.py", "line": 2, "sha": sha1, "claim": "calc.py: add overflow"}
            status2, _ = gaps.check_diff_coverage(in_bot, run_info, repo_dir=str(repo))
            self.assertEqual(status2, "in reviewed diff")

            unknown_bot = {"path": "calc.py", "line": 2, "sha": "deadbeef" * 5, "claim": "calc.py: unknown sha"}
            status3, _ = gaps.check_diff_coverage(unknown_bot, run_info, repo_dir=str(repo))
            self.assertEqual(status3, "in reviewed diff (SHA unverified)")

    def test_analyze_prs_isolates_repos_on_shared_branch_and_mismatched_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_git_repo(repo)
            (repo / "a.py").write_text("x = 1\n")
            _git(repo, "add", "a.py")
            _git(repo, "commit", "-q", "-m", "init")
            sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

            events = [
                {"v": 1, "event": "review.round", "run_id": "other/repo#1", "repo": "other/repo",
                 "branch": "fix-tests", "round": 1, "state": "start", "sha": sha},
                {"v": 1, "event": "review.finding", "run_id": "other/repo#1", "repo": "other/repo",
                 "branch": "fix-tests", "source": "local", "reviewer": "correctness-reviewer",
                 "round": 1, "path": "a.py", "line": 1, "claim": "a.py: wrong"},
            ]
            records = [{
                "repo": "another/repo", "number": 50, "branch": "fix-tests", "run_id": None,
                "bot_findings": [{"comment_id": 1, "path": "a.py", "line": 1, "sha": sha,
                                  "severity": "High", "verdict": "fixed", "validity": "valid", "claim": "a.py: wrong"}],
            }]
            out = gaps.analyze_prs(records, events, {"candidates": {}}, repo_dir=str(repo))
            self.assertIsNone(out["prs"][0]["run_id"])
            self.assertEqual(out["prs"][0]["local_finding_count"], 0)
            self.assertEqual(out["prs"][0]["missed"][0]["diff_status"], "no local review recorded")

            # Mismatched --dir (example/sample-app) vs PR repo (other/repo) must not use local git SHAs
            out2 = gaps.analyze_prs(
                [{**records[0], "repo": "other/repo", "run_id": "other/repo#1"}],
                events, {"candidates": {}}, repo_dir=str(repo),
            )
            self.assertEqual(len(out2["prs"][0]["matched"]), 1)
            records_miss = [{
                "repo": "other/repo", "number": 50, "branch": "fix-tests", "run_id": "other/repo#1",
                "bot_findings": [{"comment_id": 2, "path": "a.py", "line": 50, "sha": sha,
                                  "severity": "High", "verdict": "fixed", "validity": "valid", "claim": "a.py: missing timeout"}],
            }]
            out3 = gaps.analyze_prs(records_miss, events, {"candidates": {}}, repo_dir=str(repo))
            self.assertEqual(out3["prs"][0]["missed"][0]["diff_status"], "in reviewed diff (SHA unverified)")

    def test_loads_overlay_candidates_via_project_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            overlays = Path(tmp) / "overlays"
            root.mkdir()
            _init_git_repo(root)
            ov = overlays / "example" / "sample-app"
            (ov / "claude" / "agents").mkdir(parents=True)
            (ov / "claude" / "agents" / "custom-shader-reviewer.md").write_text(
                "---\nname: custom-shader-reviewer\nuse_when: shader files (.gdshader)\n---\nCheck shaders.\n"
            )
            with mock.patch.dict(os.environ, {"PROJECT_OVERLAYS_DIR": str(overlays)}):
                cfg = gaps.load_project_config(str(root))
                self.assertIn("custom-shader-reviewer", cfg["candidates"])
                self.assertEqual(cfg["candidates"]["custom-shader-reviewer"]["tier"], "overlay")


class TestEndToEndReport(unittest.TestCase):
    def test_no_gh_cli_writes_llm_ready_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log_path = tmp_path / "events.jsonl"
            out_path = tmp_path / "report.md"

            events = [
                {"v": 1, "ts": "2026-11-12T10:00:00Z", "event": "pr.open", "run_id": "ex/r#1", "repo": "ex/r", "branch": "Is1-a", "pr_number": 10},
                {"v": 1, "ts": "2026-11-12T10:01:00Z", "event": "review.launch", "run_id": "ex/r#1", "repo": "ex/r", "branch": "Is1-a",
                 "reviewer": "correctness-reviewer", "round": 1, "model": "sonnet", "effort": "medium", "source": "local"},
                {"v": 1, "ts": "2026-11-12T10:02:00Z", "event": "review.round", "run_id": "ex/r#1", "repo": "ex/r", "branch": "Is1-a",
                 "round": 1, "state": "start", "sha": "1111111"},
                {"v": 1, "ts": "2026-11-12T10:03:00Z", "event": "review.finding", "run_id": "ex/r#1", "repo": "ex/r", "branch": "Is1-a",
                 "source": "local", "reviewer": "correctness-reviewer", "round": 1, "finding_id": "r1-1",
                 "path": "src/foo.py", "line": 5, "claim": "src/foo.py: unrelated issue on line 5"},
                {"v": 1, "ts": "2026-11-12T10:05:00Z", "event": "review.finding", "run_id": "ex/r#1", "repo": "ex/r", "branch": "Is1-a",
                 "source": "bot", "reviewer": "copilot", "severity": "High", "verdict": "fixed", "validity": "valid",
                 "path": "src/foo.py", "line": 20, "sha": "1111111", "comment_id": 99,
                 "claim": "src/foo.py: null check missing before dereference"},
                {"v": 1, "ts": "2026-11-12T10:05:00Z", "event": "review.finding", "run_id": "ex/r#1", "repo": "ex/r", "branch": "Is1-a",
                 "source": "bot", "reviewer": "copilot", "severity": "Low", "verdict": "dismissed", "validity": "rejected",
                 "path": "src/foo.py", "line": 30, "sha": "1111111", "comment_id": 100,
                 "claim": "src/foo.py: style nit"},
            ]
            log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

            rc = gaps.main(["--no-gh", "--repo", "EX/R", "--log", str(log_path), "--out", str(out_path), "--dir", str(tmp_path)])
            self.assertEqual(rc, 0)
            text = out_path.read_text()
            self.assertIn("Copilot-valid findings:** 1 (matched locally: 0, missed: 1, miss rate: 100.0%)", text)
            self.assertIn("correctness-reviewer", text)
            self.assertIn("L5 (correctness-reviewer): src/foo.py: unrelated issue on line 5", text)
            self.assertIn("## LLM Interpretation & Proposals Guide", text)
            self.assertNotIn("style nit", text)
            self.assertNotIn("Broaden `use_when:`", text)

    def test_gh_mode_fetches_and_joins_pr(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log_path = tmp_path / "events.jsonl"
            log_path.write_text(json.dumps({
                "v": 1, "ts": "2026-11-12T10:00:00Z", "event": "review.launch",
                "run_id": "ex/r#7", "repo": "ex/r", "branch": "Is7-feat",
                "reviewer": "correctness-reviewer", "round": 1, "model": "sonnet", "source": "local",
            }) + "\n")

            pr_meta = {"number": 70, "title": "Feat", "url": "https://github.com/ex/r/pull/70", "state": "MERGED", "headRefName": "Is7-feat"}
            pr_data = {
                "number": 70, "branch": "Is7-feat",
                "comments": [{
                    "id": 501, "user": {"login": "copilot-pull-request-reviewer[bot]"},
                    "path": "app.py", "line": 10, "commit_id": "aaa", "created_at": "2026-11-12T11:00:00Z",
                    "body": "Missing bounds check on index",
                }],
                "reviews": [], "threads": [], "commit_files": [],
            }
            with mock.patch.object(gaps, "_fetch_pr_meta", return_value=pr_meta), \
                 mock.patch.object(gaps.wf_backfill, "fetch_pr_bot_data", return_value=pr_data), \
                 mock.patch("sys.stdout"):
                rc = gaps.main(["--pr", "70", "--repo", "ex/r", "--log", str(log_path), "--json", "--dir", str(tmp_path)])
            self.assertEqual(rc, 0)

    def test_extract_copilot_findings_review_body_and_logged_override(self):
        pr_data = {
            "number": 71, "branch": "Is71-x",
            "comments": [{
                "id": 601, "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "path": "app.py", "line": 10, "commit_id": "aaa", "created_at": "2026-11-12T11:00:00Z",
                "body": "Style nit only",
            }],
            "reviews": [{
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "submitted_at": "2026-11-12T11:00:00Z", "commit_id": "aaa",
                "body": (
                    "<details><summary>Suppressed comments (1)</summary>\n\n"
                    "- **app.py:22** — Missing null guard\n"
                    "</details>"
                ),
            }],
            "threads": [], "commit_files": [],
        }
        logged_bot = [{
            "event": "review.finding", "source": "bot", "comment_id": 601,
            "path": "app.py", "line": 10, "sha": "aaa",
            "verdict": "dismissed", "validity": "rejected", "reason": "false positive",
        }]
        extracted = gaps._extract_copilot_findings(pr_data, logged_bot)
        self.assertEqual(len(extracted), 2)
        self.assertEqual(extracted[0]["validity"], "rejected")
        self.assertEqual(extracted[1]["comment_id"], None)
        self.assertEqual(extracted[1]["line"], 22)

    def test_collect_pr_records_uses_dir_remote_and_skips_failed_pr(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_git_repo(repo)
            args = gaps.argparse.Namespace(no_gh=False, repo=None, pr=[10, 11], since=None, dir=str(repo))

            def fake_meta(num, slug):
                self.assertEqual(slug, "example/sample-app")
                if num == 10:
                    raise SystemExit("gh error")
                return {"number": 11, "title": "OK", "url": "u", "state": "MERGED", "headRefName": "b"}

            with mock.patch.object(gaps, "_fetch_pr_meta", side_effect=fake_meta), \
                 mock.patch.object(gaps.wf_backfill, "fetch_pr_bot_data", return_value={"branch": "b", "comments": [], "reviews": [], "threads": [], "commit_files": []}):
                recs = gaps._collect_pr_records(args, [])
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0]["number"], 11)

    def test_render_markdown_collapses_newlines_in_table_cells(self):
        analysis = {
            "prs": [{
                "repo": "ex/r", "pr": 1, "branch": "b", "run_id": "r1",
                "local_finding_count": 1, "ran_reviewers": ["correctness-reviewer"],
                "launches": [], "bot_total": 1, "bot_valid": 1, "bot_rejected": 0,
                "matched": [],
                "missed": [{
                    "bot": {"path": "a.py", "line": 5, "severity": "High", "validity": "valid", "claim": "line1\nline2 | pipe"},
                    "diff_status": "in reviewed diff", "diff_evidence": "covered",
                    "same_file_local": [{"line": 2, "reviewers": ["correctness-reviewer"], "claim": "foo\nbar"}],
                }],
            }],
            "model_stats": [],
            "candidates": [{"name": "r", "tier": "global", "model": "sonnet", "use_when": "first\nsecond | third"}],
            "overlay_dir": "",
        }
        md = gaps.render_markdown(analysis)
        for row in [ln for ln in md.splitlines() if ln.startswith("|")]:
            self.assertNotIn("\n", row)
        self.assertIn("line1 line2 \\| pipe", md)
        self.assertIn("first second \\| third", md)

    def test_since_queries_closed_prs_including_unmerged(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_git_repo(repo)
            args = gaps.argparse.Namespace(no_gh=False, repo=None, pr=None, since="2026-11-10", dir=str(repo))

            def fake_gh(cmd):
                self.assertEqual(cmd[:5], ["pr", "list", "--repo", "example/sample-app", "--state"])
                self.assertEqual(cmd[5], "closed")
                return [
                    {"number": 20, "closedAt": "2026-11-11T00:00:00Z"},
                    {"number": 19, "closedAt": "2026-11-09T23:59:59Z"},
                ]

            with mock.patch.object(gaps.wf_backfill, "_gh_json", side_effect=fake_gh), \
                 mock.patch.object(gaps, "_fetch_pr_meta", return_value={"number": 20, "title": "Closed", "url": "u", "state": "CLOSED", "headRefName": "b"}), \
                 mock.patch.object(gaps.wf_backfill, "fetch_pr_bot_data", return_value={"branch": "b", "comments": [], "reviews": [], "threads": [], "commit_files": []}):
                recs = gaps._collect_pr_records(args, [])
            self.assertEqual([r["number"] for r in recs], [20])

    def test_load_project_config_scans_supplied_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            main_repo = Path(tmp) / "main"
            wt = Path(tmp) / "wt"
            main_repo.mkdir()
            _init_git_repo(main_repo)
            (main_repo / "README.md").write_text("hi\n")
            _git(main_repo, "add", "README.md")
            _git(main_repo, "commit", "-q", "-m", "init")
            _git(main_repo, "worktree", "add", "-q", "-b", "feat", str(wt))

            agents_dir = wt / ".claude" / "agents" / "pr-reviewers"
            agents_dir.mkdir(parents=True)
            (agents_dir / "pr-reviewer-wt.md").write_text(
                "---\nname: pr-reviewer-wt\nuse_when: always\n---\nCheck.\n"
            )
            lenses_dir = wt / ".claude" / "agents" / "project-lenses"
            lenses_dir.mkdir(parents=True)
            (lenses_dir / "project-lens-arch.md").write_text(
                "---\nname: project-lens-arch\nuse_when: periodic\n---\nLens.\n"
            )
            with mock.patch.dict(os.environ, {"PROJECT_OVERLAYS_DIR": str(Path(tmp) / "overlays")}):
                cfg = gaps.load_project_config(str(wt))
            self.assertIn("pr-reviewer-wt", cfg["candidates"])
            self.assertNotIn("project-lens-arch", cfg["candidates"])

    def test_analyze_prs_skips_originless_dir_for_diff_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test")
            f = repo / "a.py"
            f.write_text("x = 1\n")
            _git(repo, "add", "a.py")
            _git(repo, "commit", "-q", "-m", "c1")
            sha1 = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            f.write_text("x = 2\n")
            _git(repo, "commit", "-q", "-am", "c2")
            sha2 = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

            events = [
                {"v": 1, "event": "review.round", "run_id": "other/repo#1", "repo": "other/repo",
                 "branch": "b", "round": 1, "state": "start", "sha": sha1},
            ]
            records = [{
                "repo": "other/repo", "number": 50, "branch": "b", "run_id": "other/repo#1",
                "bot_findings": [{"comment_id": 1, "path": "a.py", "line": 1, "sha": sha2,
                                  "severity": "High", "verdict": "fixed", "validity": "valid", "claim": "a.py: wrong"}],
            }]
            out = gaps.analyze_prs(records, events, {"candidates": {}}, repo_dir=str(repo))
            self.assertEqual(out["prs"][0]["missed"][0]["diff_status"], "in reviewed diff (SHA unverified)")


if __name__ == "__main__":
    unittest.main()
