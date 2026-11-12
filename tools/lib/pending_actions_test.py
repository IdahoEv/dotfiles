"""Tests for pending-actions.sh: rows keyed by (issue, action), idempotent upserts."""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(os.path.dirname(HERE), "pending-actions.sh")

HEADER = "| issue | action | detail | command |\n| --- | --- | --- | --- |\n"


def run(*args):
    return subprocess.run([CLI, *args], capture_output=True, text=True)


class PendingActionsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "pending.md")

    def read(self):
        with open(self.path) as f:
            return f.read()

    def upsert(self, issue, action, detail="d", command=None):
        args = ["upsert", self.path, "--issue", str(issue), "--action", action, "--detail", detail]
        if command is not None:
            args += ["--command", command]
        return run(*args)

    def test_creates_file_with_header(self):
        self.assertEqual(self.upsert(12, "close-duplicate", "dup of #3").returncode, 0)
        self.assertEqual(self.read(), HEADER + "| 12 | close-duplicate | dup of #3 |  |\n")

    def test_same_input_twice_is_byte_identical(self):
        self.upsert(12, "comment", "x", "gh issue comment 12")
        first = self.read()
        self.upsert(12, "comment", "x", "gh issue comment 12")
        self.assertEqual(self.read(), first)

    def test_same_key_replaces_in_place(self):
        self.upsert(1, "comment", "old")
        self.upsert(2, "comment", "other")
        self.upsert(1, "comment", "new")
        self.assertEqual(
            self.read(),
            HEADER + "| 1 | comment | new |  |\n| 2 | comment | other |  |\n",
        )

    def test_same_issue_different_action_is_separate_row(self):
        self.upsert(1, "comment")
        self.upsert(1, "relabel")
        self.assertEqual(self.read().count("| 1 |"), 2)

    def test_pipe_in_detail_is_escaped_and_roundtrips(self):
        self.upsert(1, "comment", "a | b")
        self.assertIn(r"a \| b", self.read())
        before = self.read()
        self.upsert(1, "comment", "a | b")
        self.assertEqual(self.read(), before)

    def test_has_reports_presence_by_exit_code(self):
        self.upsert(1, "comment")
        self.assertEqual(run("has", self.path, "--issue", "1", "--action", "comment").returncode, 0)
        self.assertEqual(run("has", self.path, "--issue", "1", "--action", "relabel").returncode, 1)

    def test_has_on_missing_file_is_absent(self):
        self.assertEqual(run("has", self.path, "--issue", "1", "--action", "x").returncode, 1)

    def test_list_prints_rows_as_tab_separated(self):
        self.upsert(1, "comment", "a | b", "cmd")
        self.assertEqual(run("list", self.path).stdout, "1\tcomment\ta | b\tcmd\n")

    def test_prose_around_table_is_preserved(self):
        with open(self.path, "w") as f:
            f.write("# Pending\n\nNotes.\n\n" + HEADER + "| 5 | comment | k |  |\n\nTrailer.\n")
        self.upsert(6, "relabel", "n")
        self.upsert(5, "comment", "k2")
        self.assertEqual(
            self.read(),
            "# Pending\n\nNotes.\n\n" + HEADER
            + "| 5 | comment | k2 |  |\n| 6 | relabel | n |  |\n\nTrailer.\n",
        )

    def test_row_goes_under_empty_table_not_after_trailing_prose(self):
        with open(self.path, "w") as f:
            f.write("# P\n\n" + HEADER + "\nTrailer.\n")
        self.upsert(1, "comment", "d")
        self.assertEqual(self.read(), "# P\n\n" + HEADER + "| 1 | comment | d |  |\n\nTrailer.\n")

    def test_trailing_backslash_roundtrips(self):
        self.upsert(1, "comment", "see C:\\dir\\", "cmd")
        self.assertEqual(run("list", self.path).stdout, "1\tcomment\tsee C:\\dir\\\tcmd\n")
        before = self.read()
        self.upsert(1, "comment", "see C:\\dir\\", "cmd")
        self.assertEqual(self.read(), before)

    def test_leading_zero_issue_is_same_key(self):
        self.upsert(1, "comment", "a")
        self.upsert("01", "comment", "b")
        self.assertEqual(run("list", self.path).stdout, "1\tcomment\tb\t\n")
        self.assertEqual(run("has", self.path, "--issue", "001", "--action", "comment").returncode, 0)

    def test_rejects_unicode_digit_issue(self):
        self.assertNotEqual(self.upsert("\u00b2", "comment").returncode, 0)

    def test_failed_write_leaves_original_intact(self):
        self.upsert(1, "comment", "keep")
        before = self.read()
        os.chmod(self.dir.name, 0o500)
        self.addCleanup(os.chmod, self.dir.name, 0o700)
        if os.access(self.dir.name, os.W_OK):
            self.skipTest("directory permissions not enforced")
        self.assertNotEqual(self.upsert(2, "comment", "x").returncode, 0)
        self.assertEqual(self.read(), before)

    def test_unicode_line_separators_in_detail_roundtrip(self):
        detail = "a\u2028b\x0cc"
        self.upsert(1, "comment", detail)
        before = self.read()
        self.upsert(1, "comment", detail)
        self.assertEqual(self.read(), before)
        self.assertEqual(run("list", self.path).stdout, f"1\tcomment\t{detail}\t\n")

    def test_symlinked_file_is_updated_through_the_link(self):
        target = os.path.join(self.dir.name, "real.md")
        os.symlink(target, self.path)
        self.upsert(1, "comment", "x")
        self.assertTrue(os.path.islink(self.path))
        with open(target) as f:
            self.assertIn("| 1 | comment | x |", f.read())

    def test_rejects_non_numeric_issue(self):
        self.assertNotEqual(self.upsert("abc", "comment").returncode, 0)

    def test_rejects_newline_in_field(self):
        self.assertNotEqual(self.upsert(1, "comment", "a\nb").returncode, 0)

    def test_rejects_tab_in_field(self):
        self.assertNotEqual(self.upsert(1, "comment", "a\tb").returncode, 0)

    def test_numeric_rows_in_other_tables_are_ignored_and_preserved(self):
        other = "| id | name |\n| --- | --- |\n| 1 | keep |\n\n"
        with open(self.path, "w") as f:
            f.write(other + HEADER)
        self.upsert(1, "comment", "d")
        self.assertEqual(self.read(), other + HEADER + "| 1 | comment | d |  |\n")
        self.assertEqual(run("list", self.path).stdout, "1\tcomment\td\t\n")

    def test_concurrent_upserts_all_survive(self):
        procs = [
            subprocess.Popen([CLI, "upsert", self.path, "--issue", str(i), "--action", "comment", "--detail", "d"])
            for i in range(1, 13)
        ]
        for p in procs:
            self.assertEqual(p.wait(), 0)
        self.assertEqual(len(run("list", self.path).stdout.splitlines()), 12)


if __name__ == "__main__":
    unittest.main()
