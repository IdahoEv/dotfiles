"""Tests for pr_body: assembly, caps, risk tiers, review report, draft staleness.

    python3 -m unittest tools/lib/pr_body_test.py

Each case builds a throwaway git repo with a base branch and a feature branch.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pr_body  # noqa: E402

TABLE = {"high": ["tools/**", "package.json"], "low": ["docs/**", "*.md"]}


class Classify(unittest.TestCase):
    def test_any_high_path_is_high(self):
        self.assertEqual(pr_body.classify(["docs/a.md", "tools/x.sh"], TABLE), "high")

    def test_all_low_paths_is_low(self):
        self.assertEqual(pr_body.classify(["docs/a.md", "README.md"], TABLE), "low")

    def test_mixed_unmatched_is_medium(self):
        self.assertEqual(pr_body.classify(["docs/a.md", "src/app.py"], TABLE), "medium")

    def test_basename_pattern_matches_nested_manifest(self):
        self.assertEqual(pr_body.classify(["web/package.json"], TABLE), "high")

    def test_empty_diff_is_low(self):
        self.assertEqual(pr_body.classify([], TABLE), "low")

    def test_shipped_table_marks_hooks_high_and_docs_low(self):
        table = pr_body.load_table(None)
        self.assertEqual(pr_body.classify(["dot_claude/hooks/x.sh"], table), "high")
        self.assertEqual(pr_body.classify(["docs/x.md"], table), "low")


class Caps(unittest.TestCase):
    def test_summary_accepts_three_bullets(self):
        self.assertEqual(pr_body.parse_summary("- a\n- b\n- c\n"), ["a", "b", "c"])

    def test_summary_rejects_four_bullets(self):
        with self.assertRaisesRegex(pr_body.CapError, "Summary.*at most 3"):
            pr_body.parse_summary("- a\n- b\n- c\n- d\n")

    def test_summary_rejects_wrapped_bullet(self):
        with self.assertRaisesRegex(pr_body.CapError, "one line"):
            pr_body.parse_summary("- a\n  continued\n")

    def test_summary_rejects_empty(self):
        with self.assertRaisesRegex(pr_body.CapError, "Summary"):
            pr_body.parse_summary("\n")

    def test_judgment_none(self):
        self.assertEqual(pr_body.parse_judgment("none\n"), [])

    def test_judgment_rejects_four_items(self):
        with self.assertRaisesRegex(pr_body.CapError, "Needs your judgment.*at most 3"):
            pr_body.parse_judgment("- a\n- b\n- c\n- d\n")

    def test_judgment_rejects_prose(self):
        with self.assertRaisesRegex(pr_body.CapError, "none"):
            pr_body.parse_judgment("Nothing much.\n")


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.write("README.md", "x\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.root, *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def sections(self, summary="- did x\n", judgment="none\n"):
        return summary, judgment


class Assemble(RepoCase):
    def test_sections_in_fixed_order(self):
        self.write("docs/a.md", "doc\n")
        self.commit("docs")
        body = pr_body.assemble(self.root, "main", "- did x\n", "- pick a or b\n", "12 passed")
        heads = [ln for ln in body.splitlines() if ln.startswith("## ")]
        self.assertEqual(heads, ["## Summary", "## Needs your judgment", "## Risk",
                                 "## Review", "## Tests"])
        self.assertIn("- did x", body)
        self.assertIn("- pick a or b", body)
        self.assertIn("low", body)
        self.assertIn("1 file changed", body)
        self.assertIn("12 passed", body)

    def test_judgment_none_renders_none(self):
        self.write("docs/a.md", "doc\n")
        self.commit("docs")
        body = pr_body.assemble(self.root, "main", "- did x\n", "none\n", None)
        self.assertIn("## Needs your judgment\nnone", body)
        self.assertIn("Not reported", body)

    def test_over_cap_raises(self):
        with self.assertRaises(pr_body.CapError):
            pr_body.assemble(self.root, "main", "- a\n- b\n- c\n- d\n", "none\n", None)

    def test_missing_review_report_says_not_run(self):
        self.write("docs/a.md", "doc\n")
        self.commit("docs")
        body = pr_body.assemble(self.root, "main", "- did x\n", "none\n", None)
        self.assertIn("## Review\nNot run", body)

    def test_review_report_rendered(self):
        self.write("docs/a.md", "doc\n")
        self.commit("docs")
        pr_body.write_review(self.root, rounds=2, fixed=3, dismissed=1, deferred=0)
        body = pr_body.assemble(self.root, "main", "- did x\n", "none\n", None)
        self.assertIn("2 rounds: 3 fixed, 1 dismissed, 0 deferred", body)
        self.assertNotIn("stale", body)

    def test_stale_review_report_is_flagged(self):
        self.write("docs/a.md", "doc\n")
        self.commit("docs")
        pr_body.write_review(self.root, rounds=1, fixed=0, dismissed=0, deferred=0)
        self.write("docs/b.md", "more\n")
        self.commit("later")
        body = pr_body.assemble(self.root, "main", "- did x\n", "none\n", None)
        self.assertIn("stale", body)

    def test_high_risk_from_touched_paths(self):
        self.write("tools/x.sh", "#!/bin/sh\n")
        self.commit("tool")
        body = pr_body.assemble(self.root, "main", "- did x\n", "none\n", None)
        self.assertIn("**high**", body)

    def test_repo_override_table_wins(self):
        self.write(".claude/pr-risk.json", json.dumps({"high": ["docs/**"], "low": []}))
        self.write("docs/a.md", "doc\n")
        self.commit("docs")
        body = pr_body.assemble(self.root, "main", "- did x\n", "none\n", None)
        self.assertIn("**high**", body)


class Draft(RepoCase):
    def setUp(self):
        super().setUp()
        self.write("docs/a.md", "doc\n")
        self.commit("docs")

    def test_load_returns_saved_sections_when_fresh(self):
        pr_body.save_draft(self.root, "main", "- did x\n", "none\n")
        self.assertEqual(pr_body.load_draft(self.root, "main"), ("- did x\n", "none\n"))

    def test_load_missing_is_none(self):
        self.assertIsNone(pr_body.load_draft(self.root, "main"))

    def test_new_commit_makes_draft_stale(self):
        pr_body.save_draft(self.root, "main", "- did x\n", "none\n")
        self.write("docs/a.md", "changed\n")
        self.commit("edit")
        self.assertIsNone(pr_body.load_draft(self.root, "main"))

    def test_touched_set_change_makes_draft_stale(self):
        pr_body.save_draft(self.root, "main", "- did x\n", "none\n")
        fp = pr_body.fingerprint(self.root, "main")
        self.write("docs/b.md", "new\n")
        self.commit("add")
        self.assertNotEqual(fp, pr_body.fingerprint(self.root, "main"))

    def test_save_enforces_caps(self):
        with self.assertRaises(pr_body.CapError):
            pr_body.save_draft(self.root, "main", "- a\n- b\n- c\n- d\n", "none\n")


class Cli(RepoCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(HERE, "pr_body.py"), *args],
                              cwd=self.root, capture_output=True, text=True)

    def test_assemble_rejects_over_cap_with_exit_2(self):
        self.write("s.txt", "- a\n- b\n- c\n- d\n")
        self.write("j.txt", "none\n")
        r = self.run_cli("assemble", "--base", "main", "--summary-file", "s.txt",
                         "--judgment-file", "j.txt")
        self.assertEqual(r.returncode, 2)
        self.assertIn("at most 3", r.stderr)

    def test_draft_load_exit_1_when_missing(self):
        r = self.run_cli("draft", "load", "--base", "main",
                         "--summary-file", "s.out", "--judgment-file", "j.out")
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
