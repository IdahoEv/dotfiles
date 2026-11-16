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

            # Insert 20 lines at top so line 4 shifts to line 24
            f.write_text("".join(f"pad{i}\n" for i in range(20)) + "a\nb\nc\nd\ne\n")
            _git(repo, "commit", "-q", "-am", "r2")
            sha2 = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

            local = [{"path": "mod.py", "line": 4, "round": 1, "sha": "", "claim": "mod.py: d is wrong"}]
            bot = {"path": "mod.py", "line": 24, "sha": sha2, "claim": "mod.py: d has wrong behavior"}
            self.assertIsNotNone(gaps.match_finding(bot, local, {1: sha1}, repo_dir=str(repo)))


class TestMissClassification(unittest.TestCase):
    def test_code_not_in_diff_when_modified_after_last_round_sha(self):
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
            bot = {"path": "calc.py", "line": 5, "sha": sha2, "claim": "calc.py: div does not guard zero denominator"}
            cls, _ = gaps.classify_miss(bot, run_info, {"candidates": {}, "overlay_config": {}}, repo_dir=str(repo))
            self.assertEqual(cls, "code not in the diff the reviewer saw")

    def test_reviewer_not_selected_and_ran_and_missed(self):
        cfg = {
            "candidates": {
                "correctness-reviewer": {"name": "correctness-reviewer", "use_when": "non-trivial logic"},
                "security-reviewer": {"name": "security-reviewer", "use_when": "auth, injection, untrusted input"},
            },
            "overlay_config": {},
        }
        run_info = {"round_shas": {1: "abc"}, "ran_reviewers": {"correctness-reviewer"}, "launches": [], "local_findings": []}

        sec_bot = {"path": "auth.py", "line": 10, "sha": "abc", "claim": "auth.py: SQL injection via unsanitized query"}
        cls1, _ = gaps.classify_miss(sec_bot, run_info, cfg)
        self.assertEqual(cls1, "reviewer not selected")

        logic_bot = {"path": "math.py", "line": 10, "sha": "abc", "claim": "math.py: off-by-one condition returns wrong result"}
        cls2, _ = gaps.classify_miss(logic_bot, run_info, cfg)
        self.assertEqual(cls2, "reviewer ran and missed")

    def test_outside_reviewer_scope_from_overlay_config(self):
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
            (ov / "review-gaps.json").write_text(json.dumps({
                "outside_scope_patterns": [r"\.tscn$"],
            }))

            with mock.patch.dict(os.environ, {"PROJECT_OVERLAYS_DIR": str(overlays)}):
                cfg = gaps.load_project_config(str(root))
                self.assertIn("custom-shader-reviewer", cfg["candidates"])

                run_info = {"round_shas": {1: "abc"}, "ran_reviewers": {"correctness-reviewer"}, "launches": [], "local_findings": []}
                scene_bot = {"path": "scenes/main.tscn", "line": 12, "sha": "abc", "claim": "main.tscn: missing node path"}
                cls, _ = gaps.classify_miss(scene_bot, run_info, cfg)
                self.assertEqual(cls, "outside reviewer scope")


class TestEndToEndReportAndProposals(unittest.TestCase):
    def test_no_gh_cli_writes_report_with_proposals(self):
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
            self.assertIn("reviewer ran and missed", text)
            self.assertIn("## Proposals", text)
            self.assertIn("### Prompt Changes", text)
            self.assertIn("### New Focus Agents", text)
            self.assertIn("### Multi-Model & Effort-Level Experiments", text)
            self.assertIn("correctness-reviewer", text)
            self.assertNotIn("style nit", text)

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


if __name__ == "__main__":
    unittest.main()
