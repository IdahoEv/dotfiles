#!/usr/bin/env python3
"""Tests for the /tighten scanner, proposal applier, and worktree helper."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def script(name: str) -> Path:
    for candidate in (HERE / f"executable_{name}", HERE / name):
        if candidate.exists():
            return candidate
    raise SystemExit(f"missing script: {name} in {HERE}")


SCANNER = script("tighten-scan.py")
PROPOSALS = script("tighten-proposals.py")
WORKTREE = script("tighten-worktree.sh")
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
}


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = load("tighten_lib", "tighten_lib.py")


def run(script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args],
                          cwd=str(cwd) if cwd else None, capture_output=True, text=True)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, **GIT_ENV})


def new_repo(path: Path, files: dict[str, str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    for name, body in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")


class WordCountTests(unittest.TestCase):
    def test_punctuation_and_underscores_split(self):
        self.assertEqual(lib.count_words("don't snake_case #123"), 5)


class MarkdownTests(unittest.TestCase):
    def test_prose_skips_fences_tables_and_frontmatter(self):
        text = (
            "---\ntitle: x\n---\n"
            "# Heading\n"
            "One two.\n\n"
            "```python\nprint('three four')\n```\n\n"
            "| a | b |\n| - | - |\n| 1 | 2 |\n\n"
            "[link text](https://example.com) and `inline_code`.\n"
        )
        prose, total, headings = lib.markdown_prose(text)
        self.assertEqual(headings, 1)
        self.assertEqual(prose, 1 + 2 + 3)
        self.assertGreater(total, prose)

    def test_indented_code_after_blank_is_not_prose(self):
        prose, _total, _headings = lib.markdown_prose("Intro.\n\n    indented code\n")
        self.assertEqual(prose, 1)

    def test_nested_list_continuation_is_prose(self):
        prose, _total, _headings = lib.markdown_prose("- item\n    continued text\n")
        self.assertEqual(prose, 3)


class CodeTests(unittest.TestCase):
    def test_python_docstring_and_comments(self):
        text = (
            '#!/usr/bin/env python3\n'
            '"""Module summary."""\n'
            'x = "# not a comment"\n'
            '# First line of a long comment.\n'
            '# Second line.\n'
            'def f():\n'
            '    """Function summary."""\n'
            '    return x\n'
        )
        blocks, code_lines, license_header, parsed = lib.scan_python(text)
        self.assertTrue(parsed)
        self.assertFalse(license_header)
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("Module summary", joined)
        self.assertIn("Function summary", joined)
        self.assertIn("First line", joined)
        self.assertNotIn("not a comment", joined)
        self.assertEqual(code_lines, 3)

    def test_python_license_docstring_is_dropped(self):
        text = '"""Copyright 2020 Example. Licensed under MIT."""\n\nx = 1\n'
        blocks, _code_lines, license_header, _parsed = lib.scan_python(text)
        self.assertTrue(license_header)
        self.assertEqual(blocks, [])

    def test_python_parse_error_flags(self):
        blocks, _code_lines, _license, parsed = lib.scan_python("def broken(:\n    pass\n")
        self.assertFalse(parsed)

    def test_javascript_url_inside_string_is_not_comment(self):
        blocks, _lines = lib.scan_generic('const url = "http://x"; // real\n', lib.CODE_SPECS[".js"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("real", joined)
        self.assertNotIn("http", joined)

    def test_javascript_template_literal_is_not_a_comment(self):
        blocks, _lines = lib.scan_generic(
            "const u = `http://example.com/x`; // note\n", lib.CODE_SPECS[".js"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("note", joined)
        self.assertNotIn("example.com", joined)

    def test_hash_inside_a_word_is_not_a_comment(self):
        blocks, _lines = lib.scan_generic("name: ci#fragment\n", lib.CODE_SPECS[".yml"])
        self.assertEqual(blocks, [])
        blocks, _lines = lib.scan_generic("echo $#\n", lib.CODE_SPECS[".sh"])
        self.assertEqual(blocks, [])

    def test_heredoc_body_is_not_a_comment(self):
        text = "cat <<EOF\n# data, not a comment\nEOF\n# real comment\n"
        blocks, _lines = lib.scan_generic(text, lib.CODE_SPECS[".sh"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("real comment", joined)
        self.assertNotIn("data, not a comment", joined)

    def test_terraform_heredoc_body_is_not_a_comment(self):
        text = 'user_data = <<EOF\n#cloud-config\nEOF\n# real comment\n'
        blocks, _lines = lib.scan_generic(text, lib.CODE_SPECS[".tf"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("real comment", joined)
        self.assertNotIn("cloud-config", joined)

    def test_nix_indented_string_body_is_not_a_comment(self):
        text = "s = ''\n  # not a nix comment\n''\n# real comment\n"
        blocks, _lines = lib.scan_generic(text, lib.CODE_SPECS[".nix"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("real comment", joined)
        self.assertNotIn("not a nix comment", joined)

    def test_sql_dollar_quoted_body_is_not_a_comment(self):
        text = "CREATE FUNCTION f() AS $$ -- internal note\nSELECT 1;\n$$;\n-- real comment\n"
        blocks, _lines = lib.scan_generic(text, lib.CODE_SPECS[".sql"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("real comment", joined)
        self.assertNotIn("internal note", joined)

    def test_two_heredocs_on_one_line_track_both_bodies(self):
        text = "cat <<A <<B\n# body A\nA\n# body B\nB\n# real comment\n"
        blocks, _lines = lib.scan_generic(text, lib.CODE_SPECS[".sh"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("real comment", joined)
        self.assertNotIn("body B", joined)

    def test_trailing_space_does_not_end_a_heredoc(self):
        text = "cat <<EOF\nbody\nEOF \n# still heredoc\nEOF\n# real comment\n"
        blocks, _lines = lib.scan_generic(text, lib.CODE_SPECS[".sh"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("real comment", joined)
        self.assertNotIn("still heredoc", joined)

    def test_tab_indented_code_is_not_prose(self):
        prose, _total, _headings = lib.markdown_prose("# Guide\n\nInstall:\n\n\tmake install\n")
        self.assertEqual(prose, 2)

    def test_ruby_squiggly_heredoc_body_is_not_a_comment(self):
        text = "sql = <<~SQL\n  # data line\nSQL\n# real comment\n"
        blocks, _lines = lib.scan_generic(text, lib.CODE_SPECS[".rb"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("real comment", joined)
        self.assertNotIn("data line", joined)

    def test_comment_ranges_align_when_a_form_feed_splits_lines(self):
        text = "const a = 1;\n\x0cconst b = 2;\n// real comment\n"
        ranges, parsed = lib.comment_ranges(text, "x.js")
        self.assertTrue(parsed)
        self.assertEqual([text[a:b] for a, b in ranges], ["// real comment"])

    def test_yaml_block_scalar_body_is_not_a_comment(self):
        text = "script: |\n  # data\n# real comment\n"
        blocks, _lines = lib.scan_generic(text, lib.CODE_SPECS[".yml"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("real comment", joined)
        self.assertNotIn("data", joined)

    def test_rust_lifetime_does_not_hide_a_trailing_comment(self):
        blocks, _lines = lib.scan_generic(
            "fn f<'a>(x: &'a str) -> &'a str { x } // note here\n", lib.CODE_SPECS[".rs"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("note here", joined)

    def test_lowercase_hyphenated_word_is_not_a_ticket(self):
        self.assertEqual(lib.ref_counts("# Works on python-3 only."), (0, 0))
        self.assertEqual(lib.ref_counts("# Fixed in ABC-123.")[1], 1)

    def test_sql_dashes_inside_string_are_not_comment(self):
        blocks, _lines = lib.scan_generic("select '--x'; -- real\n", lib.CODE_SPECS[".sql"])
        joined = "\n".join(piece for block in blocks for _line, piece in block)
        self.assertIn("real", joined)
        self.assertNotIn("x", joined)

    def test_block_comment_marks_protected_directive(self):
        self.assertEqual(lib.block_kind("# type: ignore"), "directive")
        self.assertEqual(lib.block_kind(">>> f()"), "doctest")


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        new_repo(self.repo, {
            "src/verbose.py": "# One two three four.\n# Five six.\n\ndef f():\n    return 1\n",
            "src/plain.js": 'const u = "http://x"; // note\n',
            "README.md": "# Title\n\nIntro text.\n\n```\ncode block\n```\n",
            "CLAUDE.md": "# Prompt file\n",
            ".claude/skills/x/SKILL.md": "# Prompt file\n",
            "dot_claude/skills/x/SKILL.md": "# Prompt file\n",
            "Makefile": "# build everything\nall:\n\techo hi\n",
            "CHANGELOG.md": "# Changes\n",
            "node_modules/pkg/index.js": "// vendored\n",
            "src/model_pb2.py": "# generated\n",
            "src/generated.py": "# Code generated by tool. DO NOT EDIT.\n",
        })
        (self.repo / "untracked.py").write_text("# untracked comment\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_skips_vendored_generated_prompt_and_untracked(self):
        result = run(SCANNER, "--root", str(self.repo), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        paths = {entry["path"] for entry in report["files"]}
        self.assertIn("src/verbose.py", paths)
        self.assertIn("README.md", paths)
        self.assertNotIn("untracked.py", paths)
        self.assertNotIn("CLAUDE.md", paths)
        self.assertNotIn(".claude/skills/x/SKILL.md", paths)
        self.assertNotIn("dot_claude/skills/x/SKILL.md", paths)
        self.assertIn("Makefile", paths)
        self.assertNotIn("CHANGELOG.md", paths)
        self.assertNotIn("node_modules/pkg/index.js", paths)
        self.assertNotIn("src/model_pb2.py", paths)
        self.assertNotIn("src/generated.py", paths)
        self.assertGreaterEqual(report["skipped"]["vendored"], 1)
        self.assertGreaterEqual(report["skipped"]["generated"], 2)
        self.assertGreaterEqual(report["skipped"]["prompt"], 1)
        self.assertGreaterEqual(report["skipped"]["excluded"], 1)

    def test_include_untracked(self):
        result = run(SCANNER, "--root", str(self.repo), "--json", "--include-untracked")
        report = json.loads(result.stdout)
        paths = {entry["path"] for entry in report["files"]}
        self.assertIn("untracked.py", paths)

    def test_commands_from_package_json(self):
        new_repo(Path(self.tmp.name) / "node", {"package.json": json.dumps(
            {"scripts": {"build": "tsc", "test": "jest"}})})
        result = run(SCANNER, "--root", str(Path(self.tmp.name) / "node"), "--commands")
        self.assertIn("build=npm run build", result.stdout)
        self.assertIn("test=npm test", result.stdout)
        self.assertIn("source=package.json", result.stdout)

    def test_path_scoped_scan(self):
        result = run(SCANNER, "README.md", "--root", str(self.repo), "--json", cwd=self.repo)
        report = json.loads(result.stdout)
        self.assertEqual([entry["path"] for entry in report["files"]], ["README.md"])

    def test_subdirectory_root_scans_its_files(self):
        result = run(SCANNER, "--root", str(self.repo / "src"), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        paths = {entry["path"] for entry in report["files"]}
        self.assertIn("verbose.py", paths)

    def test_directory_argument_does_not_unskip_prompt_files(self):
        result = run(SCANNER, ".", "--root", str(self.repo), "--json", cwd=self.repo)
        report = json.loads(result.stdout)
        paths = {entry["path"] for entry in report["files"]}
        self.assertNotIn("CLAUDE.md", paths)
        self.assertNotIn(".claude/skills/x/SKILL.md", paths)

    def test_explicit_named_prompt_file_is_scanned(self):
        result = run(SCANNER, "CLAUDE.md", "--root", str(self.repo), "--json", cwd=self.repo)
        report = json.loads(result.stdout)
        self.assertEqual([entry["path"] for entry in report["files"]], ["CLAUDE.md"])

    def test_relative_path_resolves_under_root_when_it_exists(self):
        result = run(SCANNER, "src", "--root", str(self.repo), "--json", cwd=self.tmp.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        paths = {entry["path"] for entry in report["files"]}
        self.assertIn("src/verbose.py", paths)

    def test_relative_path_resolves_against_cwd(self):
        (self.repo / "src" / "target.py").write_text("# one two three four\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "add target")
        result = run(SCANNER, "target.py", "--root", str(self.repo), "--json",
                     cwd=self.repo / "src")
        report = json.loads(result.stdout)
        self.assertEqual([entry["path"] for entry in report["files"]], ["src/target.py"])
        self.assertEqual(report["files"][0]["comment_words"], 4)

    def test_generated_phrase_in_prose_does_not_skip_a_doc(self):
        new_repo(Path(self.tmp.name) / "gen", {
            "README.md": "# Guide\n\nThe pages are generated by Sphinx.\n",
            "a.py": "# note\n"})
        result = run(SCANNER, "--root", str(Path(self.tmp.name) / "gen"), "--json")
        report = json.loads(result.stdout)
        self.assertIn("README.md", {entry["path"] for entry in report["files"]})

    def test_mdx_is_reported_as_uneditable(self):
        new_repo(Path(self.tmp.name) / "mdx", {
            "doc.mdx": "# Title\n\n" + "word " * 120 + "\n"})
        result = run(SCANNER, "--root", str(Path(self.tmp.name) / "mdx"), "--json")
        report = json.loads(result.stdout)
        entry = [item for item in report["files"] if item["path"] == "doc.mdx"][0]
        self.assertTrue(entry["parse_error"])
        self.assertFalse(entry["signal"])

    def test_path_outside_root_is_refused(self):
        outside = Path(self.tmp.name) / "outside.py"
        outside.write_text("# note\n", encoding="utf-8")
        result = run(SCANNER, str(outside), "--root", str(self.repo))
        self.assertEqual(result.returncode, 1)
        self.assertIn("outside root", result.stderr)


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        new_repo(self.repo, {
            "a.py": "# Fetches the user record from the store.\n# Used by the handler, which retries.\ndef f():\n    return 1\n",
            "README.md": "# Title\n\nIntro text.\n\n```\ncode\n```\n",
            "doc.md": "---\ntitle: demo\n---\n\n# Title\n\nBody.\n",
            "doc.rst": "Title\n=====\n\n.. code-block:: python\n\n    print('hi')\n",
            "doc.mdx": "# Title\n\n<Chart data={series} />\n",
            ".github/workflows/ci.yml": "# Build the thing.\nname: ci\n",
        })
        self.file = self.repo / "a.py"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, proposals: list[dict], name: str = "p.json") -> Path:
        path = self.repo / name
        path.write_text(json.dumps(proposals), encoding="utf-8")
        return path

    def run_check(self, proposals: list[dict]) -> dict:
        result = run(PROPOSALS, "check", str(self.write(proposals)),
                     "--root", str(self.repo), "--json")
        return json.loads(result.stdout)

    def test_apply_comment_cut(self):
        proposals = [{
            "file": "a.py", "start_line": 1,
            "old": "# Fetches the user record from the store.\n# Used by the handler, which retries.\n",
            "new": "# Fetches the user; the handler retries.\n",
        }]
        result = run(PROPOSALS, "apply", str(self.write(proposals)), "--root", str(self.repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("applied=1", result.stdout)
        self.assertIn("# Fetches the user; the handler retries.", self.file.read_text())

    def test_stage_adds_only_changed_files(self):
        proposals = [{"file": "a.py", "old": "# Fetches the user record from the store.", "new": "# Fetches."}]
        result = run(PROPOSALS, "apply", str(self.write(proposals)), "--root", str(self.repo), "--stage")
        self.assertEqual(result.returncode, 0, result.stderr)
        staged = subprocess.run(["git", "-C", str(self.repo), "diff", "--cached", "--name-only"],
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(staged.strip(), "a.py")

    def test_not_found_is_rejected(self):
        self.assertEqual(self.run_check([{"file": "a.py", "old": "missing", "new": ""}])
                         ["rejected"][0]["reason"], "not_found")

    def test_word_growth_is_rejected(self):
        self.assertEqual(self.run_check([{"file": "a.py", "old": "# Fetches", "new": "# Fetches more words"}])
                         ["rejected"][0]["reason"], "word_growth")

    def test_protected_directive_is_rejected(self):
        self.file.write_text("# type: ignore\ndef f():\n    return 1\n")
        self.assertEqual(self.run_check([{"file": "a.py", "old": "# type: ignore", "new": ""}])
                         ["rejected"][0]["reason"], "protected_directive")

    def test_code_touch_is_rejected(self):
        self.assertEqual(self.run_check([{"file": "a.py", "old": "return 1", "new": ""}])
                         ["rejected"][0]["reason"], "not_in_comment")

    def test_doc_fence_is_rejected(self):
        self.assertEqual(self.run_check([{"file": "README.md", "old": "```\ncode\n```", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_code_on_a_comment_line_is_rejected(self):
        self.file.write_text("def f():\n    return compute()  # expensive\n")
        self.assertEqual(self.run_check([{
            "file": "a.py", "old": "    return compute()  # expensive\n", "new": ""}])
            ["rejected"][0]["reason"], "code_touch")

    def test_mixed_line_endings_are_rejected(self):
        self.file.write_bytes(b"# one two three\r\nx = 1\n# four five\r\n")
        self.assertEqual(self.run_check([{"file": "a.py", "old": "# one two three", "new": "# one"}])
                         ["rejected"][0]["reason"], "mixed_line_endings")

    def test_lone_cr_file_is_rejected(self):
        self.file.write_bytes(b"# one two three\rx = 1\r# four five\r")
        self.assertEqual(self.run_check([{"file": "a.py", "old": "# one two three", "new": "# one"}])
                         ["rejected"][0]["reason"], "mixed_line_endings")

    def test_fenced_code_body_is_rejected(self):
        self.assertEqual(self.run_check([{"file": "README.md", "old": "code", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_frontmatter_is_rejected(self):
        self.assertEqual(self.run_check([{"file": "doc.md", "old": "title: demo", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_rst_directive_body_is_rejected(self):
        self.assertEqual(self.run_check([{"file": "doc.rst", "old": "    print('hi')", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_mdx_is_never_edited(self):
        self.assertEqual(self.run_check([{"file": "doc.mdx", "old": "<Chart data={series} />",
                                          "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_change_inside_a_template_literal_is_rejected(self):
        (self.repo / "x.js").write_text("const u = `http://example.com/x`; // note\n", encoding="utf-8")
        reason = self.run_check([{
            "file": "x.js", "old": "//example.com/x`; // note", "new": "// note"}])
        self.assertIn(reason["rejected"][0]["reason"], ("not_in_comment", "code_touch"))

    def test_dir_filter_does_not_apply_a_nested_directory(self):
        new_repo(Path(self.tmp.name) / "nested", {
            "src/a.py": "# One two three four.\ndef f():\n    return 1\n",
            "src/models/b.py": "# Five six seven eight.\ndef g():\n    return 2\n",
        })
        nested = Path(self.tmp.name) / "nested"
        proposals = [
            {"file": "src/a.py", "old": "# One two three four.", "new": "# One."},
            {"file": "src/models/b.py", "old": "# Five six seven eight.", "new": "# Five."},
        ]
        result = run(PROPOSALS, "apply", str(self.write(proposals, "nested.json")),
                     "--root", str(nested), "--dir", "src")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("applied=1", result.stdout)
        self.assertIn("# Five six seven eight.", (nested / "src/models/b.py").read_text())

    def test_code_in_replacement_is_rejected(self):
        self.assertEqual(self.run_check([{
            "file": "a.py", "old": "# Fetches the user record from the store.\n",
            "new": "# Fetches.\nretries = 3\n"}])["rejected"][0]["reason"], "code_in_replacement")

    def test_unclosed_block_comment_in_replacement_is_rejected(self):
        (self.repo / "a.js").write_text(
            "/* Old long explanatory comment. */\nconst x = 1;\n", encoding="utf-8")
        self.assertEqual(self.run_check([{
            "file": "a.js", "old": "/* Old long explanatory comment. */",
            "new": "/* Old comment"}])["rejected"][0]["reason"], "code_in_replacement")

    def test_leading_blank_line_is_rejected(self):
        self.assertEqual(self.run_check([{
            "file": "a.py", "old": "\n# Fetches the user record from the store.\n",
            "new": ""}])["rejected"][0]["reason"], "leading_blank_line")

    def test_prompt_and_vendored_paths_are_rejected(self):
        (self.repo / "CLAUDE.md").write_text("# Prompt\n\nAlways explain in detail.\n")
        self.assertEqual(self.run_check([{"file": "CLAUDE.md",
                                          "old": "Always explain in detail.", "new": "Explain."}])
                         ["rejected"][0]["reason"], "skipped_path")
        (self.repo / "node_modules" / "pkg").mkdir(parents=True)
        (self.repo / "node_modules" / "pkg" / "x.js").write_text("// note here\n")
        self.assertEqual(self.run_check([{"file": "node_modules/pkg/x.js", "old": "// note here",
                                          "new": ""}])["rejected"][0]["reason"], "skipped_path")

    def test_pipe_table_row_is_rejected(self):
        (self.repo / "tbl.md").write_text(
            "# T\n\n| name | value |\n| --- | --- |\n| beta | two |\n", encoding="utf-8")
        self.assertEqual(self.run_check([{"file": "tbl.md", "old": "| beta | two |", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_final_line_without_newline_is_protected(self):
        (self.repo / "nonl.md").write_text(
            "Title\n=====\n\nRun::\n\n    print('hi')", encoding="utf-8")
        self.assertEqual(self.run_check([{"file": "nonl.md", "old": "    print('hi')", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_partial_indent_line_is_rejected(self):
        self.assertEqual(self.run_check([{
            "file": "a.py", "old": "# Fetches the user record from the store.\n    ",
            "new": "# Fetches.\n  "}])["rejected"][0]["reason"], "partial_line")

    def test_tab_indented_code_block_is_rejected(self):
        (self.repo / "tab.md").write_text("# G\n\nInstall:\n\n\tmake install\n", encoding="utf-8")
        self.assertEqual(self.run_check([{"file": "tab.md", "old": "\tmake install\n", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_html_tag_and_inline_code_are_protected(self):
        (self.repo / "html.md").write_text(
            "# T\n\n<img src=\"logo.png\">\n\nRun `npm run build:prod` first.\n", encoding="utf-8")
        self.assertEqual(self.run_check([{"file": "html.md", "old": "<img src=\"logo.png\">",
                                          "new": ""}])["rejected"][0]["reason"], "doc_structural")
        self.assertEqual(self.run_check([{"file": "html.md", "old": "npm run build:prod",
                                          "new": "npm run build"}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_trailing_newline_mismatch_is_rejected(self):
        self.assertEqual(self.run_check([{
            "file": "a.py", "old": "# Fetches the user record from the store.\n",
            "new": "# Fetches."}])["rejected"][0]["reason"], "trailing_newline_mismatch")

    def test_multiline_template_literal_lines_are_not_comments(self):
        (self.repo / "t.js").write_text(
            "const q = `\n  // keep this data\n  SELECT 1;\n`;\n", encoding="utf-8")
        self.assertEqual(self.run_check([{"file": "t.js", "old": "  // keep this data",
                                          "new": "  // keep"}])["rejected"][0]["reason"],
                         "not_in_comment")

    def test_docstring_indent_must_be_preserved(self):
        self.file.write_text('def f():\n    """Old summary of the method."""\n    return 1\n')
        kept = self.run_check([{
            "file": "a.py", "old": '    """Old summary of the method."""',
            "new": '    """New summary."""'}])
        self.assertEqual(len(kept["accepted"]), 1)
        dedented = self.run_check([{
            "file": "a.py", "old": '    """Old summary of the method."""',
            "new": '"""New summary."""'}])
        self.assertEqual(dedented["rejected"][0]["reason"], "indent_mismatch")

    def test_html_comment_terminator_cannot_be_removed(self):
        (self.repo / "h.md").write_text(
            "# T\n\n<!-- hidden note -->\n\nBody.\n", encoding="utf-8")
        self.assertEqual(self.run_check([{
            "file": "h.md", "old": " hidden note -->", "new": " note"}])
            ["rejected"][0]["reason"] in ("doc_structural", "indent_mismatch"), True)

    def test_license_header_is_protected(self):
        self.file.write_text(
            "# This file is part of Project Foo.\n"
            "# See the LICENSE file in the repository root for terms.\n"
            "x = 1\n")
        self.assertEqual(self.run_check([{
            "file": "a.py",
            "old": "# This file is part of Project Foo.\n"
                   "# See the LICENSE file in the repository root for terms.\n",
            "new": ""}])["rejected"][0]["reason"], "license_text")

    def test_setext_heading_and_rst_adornment_are_protected(self):
        (self.repo / "s.md").write_text("Title\n=====\n\nBody.\n", encoding="utf-8")
        self.assertEqual(self.run_check([{"file": "s.md", "old": "Title\n", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")
        (self.repo / "r.rst").write_text("Install\n=======\n\nRun it.\n", encoding="utf-8")
        self.assertEqual(self.run_check([{"file": "r.rst", "old": "Install\n=======\n", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_pipeless_table_row_is_protected(self):
        (self.repo / "t.md").write_text(
            "# T\n\nname | value\n--- | ---\nalpha | one\n", encoding="utf-8")
        self.assertEqual(self.run_check([{"file": "t.md", "old": "alpha | one\n", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_docstring_replacement_is_allowed(self):
        self.file.write_text('"""Old summary here."""\n\ndef f():\n    return 1\n')
        self.assertEqual(len(self.run_check([{
            "file": "a.py", "old": '"""Old summary here."""', "new": '"""New."""'}])
            ["accepted"]), 1)

    def test_indented_code_block_is_rejected(self):
        (self.repo / "guide.md").write_text(
            "# Guide\n\nInstall it:\n\n    $ make install\n    $ make test\n", encoding="utf-8")
        self.assertEqual(self.run_check([{"file": "guide.md", "old": "    $ make install\n",
                                          "new": ""}])["rejected"][0]["reason"], "doc_structural")

    def test_multiline_html_comment_is_rejected(self):
        (self.repo / "note.md").write_text(
            "# Note\n\n<!--\nhidden words here\n-->\n\nBody.\n", encoding="utf-8")
        self.assertEqual(self.run_check([{"file": "note.md", "old": "hidden words here", "new": ""}])
                         ["rejected"][0]["reason"], "doc_structural")

    def test_subdirectory_root_accepts_relative_proposals(self):
        new_repo(Path(self.tmp.name) / "sub", {
            "src/a.py": "# One two three four.\ndef f():\n    return 1\n"})
        sub = Path(self.tmp.name) / "sub"
        proposals = [{"file": "a.py", "old": "# One two three four.", "new": "# One."}]
        result = run(PROPOSALS, "check", str(self.write(proposals, "sub.json")),
                     "--root", str(sub / "src"), "--json")
        self.assertEqual(len(json.loads(result.stdout)["accepted"]), 1)

    def test_directory_symlink_escape_is_rejected(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "x.py").write_text("# One two three.\n", encoding="utf-8")
        os.symlink(outside, self.repo / "link")
        self.assertEqual(self.run_check([{"file": "link/x.py", "old": "# One two three.",
                                          "new": "# One."}])["rejected"][0]["reason"],
                         "not_a_file_in_root")

    def test_dir_filter_matches_dot_directories(self):
        proposals = [{"file": ".github/workflows/ci.yml",
                      "old": "# Build the thing.", "new": "# Build."}]
        result = run(PROPOSALS, "apply", str(self.write(proposals)), "--root", str(self.repo),
                     "--dir", ".github/workflows")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Build.", (self.repo / ".github/workflows/ci.yml").read_text())

    def test_reset_hard_rolls_back_a_staged_batch(self):
        proposals = [{"file": "a.py", "old": "# Fetches the user record from the store.",
                      "new": "# Fetches."}]
        before = self.file.read_text()
        applied = run(PROPOSALS, "apply", str(self.write(proposals)), "--root", str(self.repo),
                      "--stage")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        git(self.repo, "reset", "--hard", "HEAD")
        self.assertEqual(self.file.read_text(), before)

    def test_ambiguous_needs_start_line(self):
        self.file.write_text("# same text\nx = 1\n" + "y = 2\n" * 8 + "# same text\nz = 3\n")
        ambiguous = self.run_check([{"file": "a.py", "old": "# same text", "new": ""}])
        self.assertEqual(ambiguous["rejected"][0]["reason"], "ambiguous")
        accepted = self.run_check([{"file": "a.py", "start_line": 11, "old": "# same text", "new": ""}])
        self.assertEqual(len(accepted["accepted"]), 1)

    def test_dry_run_writes_nothing(self):
        before = self.file.read_text()
        proposals = [{"file": "a.py", "old": "# Fetches the user record from the store.", "new": "# Fetches the user."}]
        result = run(PROPOSALS, "apply", str(self.write(proposals)), "--root", str(self.repo), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.file.read_text(), before)

    def test_crlf_preserved(self):
        self.file.write_bytes(b"# one two three\r\ndef f():\r\n    return 1\r\n")
        proposals = [{"file": "a.py", "old": "# one two three", "new": "# one two"}]
        result = run(PROPOSALS, "apply", str(self.write(proposals)), "--root", str(self.repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        body = self.file.read_bytes()
        self.assertIn(b"# one two\r\n", body)
        self.assertNotIn(b"\n\n", body)

    def test_write_accepted_drops_rejected(self):
        proposals = [
            {"file": "a.py", "old": "# Fetches the user record from the store.", "new": "# Fetches."},
            {"file": "a.py", "old": "missing", "new": ""},
        ]
        accepted_path = self.repo / "accepted.json"
        result = run(PROPOSALS, "check", str(self.write(proposals)), "--root", str(self.repo),
                     "--json", "--write-accepted", str(accepted_path))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(json.loads(accepted_path.read_text())["proposals"]), 1)
        applied = run(PROPOSALS, "apply", str(accepted_path), "--root", str(self.repo))
        self.assertEqual(applied.returncode, 0, applied.stderr)

    def test_apply_refuses_when_any_proposal_rejected(self):
        proposals = [
            {"file": "a.py", "old": "# Fetches the user record from the store.", "new": "# Fetches."},
            {"file": "a.py", "old": "missing", "new": ""},
        ]
        result = run(PROPOSALS, "apply", str(self.write(proposals)), "--root", str(self.repo))
        self.assertEqual(result.returncode, 3)
        self.assertIn("refusing", result.stderr)


class WorktreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        new_repo(self.repo, {"a.py": "x = 1\n"})
        self.head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                                   capture_output=True, text=True, check=True).stdout.strip()

    def tearDown(self):
        for path in Path(self.tmp.name).glob("repo-tighten-*"):
            subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", "--force",
                            str(path)], capture_output=True)
        self.tmp.cleanup()

    def test_plain_worktree(self):
        result = subprocess.run(["bash", str(WORKTREE), str(self.repo), "tighten/test", "--base", self.head],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines())
        self.assertEqual(values["mode"], "plain")
        self.assertEqual(values["reused"], "no")
        self.assertEqual(values["head"], self.head)
        self.assertTrue(Path(values["worktree"], "a.py").is_file())
        shutil_remove(Path(values["worktree"]))

    def test_reuses_existing_worktree(self):
        first = subprocess.run(["bash", str(WORKTREE), str(self.repo), "tighten/test"],
                               capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = subprocess.run(["bash", str(WORKTREE), str(self.repo), "tighten/test"],
                                capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("reused=yes", second.stdout)
        values = dict(line.split("=", 1) for line in second.stdout.splitlines())
        shutil_remove(Path(values["worktree"]))


def shutil_remove(path: Path) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
