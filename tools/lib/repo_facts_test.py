"""Tests for repo_facts: the value matrix of the retired lib/repo-facts.test.sh
plus the git-dependent facts the shell suite never covered.

    python3 -m unittest tools/lib/repo_facts_test.py

Temp git repos and a gh PATH shim stand in for real checkouts; HOME is
redirected into the temp dir so machine-wide config is fixture data. The
bash-3.2 strict-mode and locale cases of the shell suite tested the bash
implementation; under the facade those functions delegate to this module, so
their value-level equivalents live here.
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repo_facts  # noqa: E402

CLI = os.path.join(os.path.dirname(HERE), "repo-facts.sh")
KNOBS = ("GT_LABEL_NOISE", "GT_LABEL_WORDS", "GT_LABEL_SLUG_WORDS",
         "GT_LABEL_MAX_CHARS", "GT_LABEL_OVERRIDE", "GT_LABEL_SLUG_OVERRIDE",
         "PROJECT_OVERLAYS_DIR", "GIT_TOOLS_PROJECTS_DIR")

B_TITLE = "[Core] Decide billing data deletion & retention policy (account deletion)"


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="repo-facts-test-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self._saved = {k: os.environ.get(k) for k in KNOBS}
        self._saved["HOME"] = os.environ["HOME"]
        self._saved["PATH"] = os.environ["PATH"]
        for k in KNOBS:
            os.environ.pop(k, None)
        os.environ["HOME"] = self.home
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def write(self, relpath, text):
        path = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text(text)
        return path

    def git(self, dir_, *args):
        r = subprocess.run(["git", "-C", dir_, *args], capture_output=True,
                           text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def origin_pair(self, name="widgets"):
        """A local bare origin plus a clone with a pushed main branch."""
        origin = os.path.join(self.root, f"{name}.git")
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", origin],
                       check=True, capture_output=True)
        clone = os.path.join(self.root, name)
        subprocess.run(["git", "clone", "-q", origin, clone], check=True,
                       capture_output=True)
        self.git(clone, "config", "user.email", "t@example.com")
        self.git(clone, "config", "user.name", "T")
        self.write(f"{name}/README.md", "x\n")
        self.git(clone, "add", "-A")
        self.git(clone, "commit", "-qm", "init")
        self.git(clone, "push", "-q", "origin", "main")
        return origin, clone

    def fake_remote_repo(self):
        """A repo whose origin is unreachable (ssh to port 1: instant refuse)
        but parseable, so overlay/conf facts work without network."""
        repo = os.path.join(self.root, "fakerepo")
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True,
                       capture_output=True)
        self.git(repo, "remote", "add", "origin", "ssh://git@localhost:1/acme/widgets")
        return repo

    def overlay_fixture(self):
        os.environ["PROJECT_OVERLAYS_DIR"] = os.path.join(self.root, "overlays")
        self.write("overlays/acme/widgets/start-ticket.conf",
                   "provider=overlay\nother=overlay\nskipper=ov\n")
        self.write("overlays/acme/widgets/governor.md", "overlay governor\n")
        self.write("overlays/acme/widgets/claude/kickoff-preamble.md", "p\n")
        self.write("overlays/acme/widgets/claude/agents/alpha.md", "a\n")
        self.write("overlays/acme/widgets/claude/agents/beta.md", "b\n")
        self.write("overlays/acme/widgets/claude/commands/charlie.md", "c\n")
        self.write("overlays/acme/widgets/claude/skills/echo.md", "e\n")
        self.write("overlays/acme/widgets/claude/skills/delta/SKILL.md", "d\n")

    def no_gh_path(self):
        os.environ["PATH"] = "/usr/bin:/bin"  # git, no gh

    def gh_stub_path(self, branch="trunk"):
        stub = os.path.join(self.root, "stubbin")
        os.makedirs(stub, exist_ok=True)
        Path(os.path.join(stub, "gh")).write_text(f"#!/bin/sh\necho {branch}\n")
        os.chmod(os.path.join(stub, "gh"), 0o755)
        os.environ["PATH"] = f"{stub}:/usr/bin:/bin"


class DistillTitle(Base):
    def test_noise_env_and_plain(self):
        self.assertEqual(repo_facts.distill_title(B_TITLE),
                         "Data Deletion Retention Policy")
        os.environ["GT_LABEL_NOISE"] = "billing"
        self.assertEqual(repo_facts.distill_title(B_TITLE),
                         "Data Deletion Retention Policy")

    def test_repeated_leading_tags(self):
        self.assertEqual(repo_facts.distill_title(
            "[A] [ops] Build the collector adapter contract"),
            "Collector Adapter Contract")

    def test_inline_bracket_is_not_a_tag(self):
        self.assertEqual(repo_facts.distill_title("Fix [a] thing", 9), "Thing")

    def test_acronyms_keep_case(self):
        self.assertEqual(repo_facts.distill_title("Enable dd-trace APM log correlation"),
                         "Trace APM Log Correlation")

    def test_degenerate_titles(self):
        for title in ("", "[X/Y]", "the and of"):
            self.assertEqual(repo_facts.distill_title(title), "")

    def test_glob_argument(self):
        self.assertEqual(repo_facts.distill_title("Fix the * bug"), "Bug")

    def test_maxw_zero_clamped(self):
        self.assertEqual(repo_facts.distill_title("Fix the thing", 0), "Thing")

    def test_words_env_zero_clamped(self):
        os.environ["GT_LABEL_WORDS"] = "0"
        self.assertEqual(repo_facts.distill_title("Fix the thing"), "Thing")

    def test_negative_maxw_clamped(self):
        self.assertEqual(repo_facts.distill_title("Fix the thing", -3), "Thing")

    def test_non_numeric_maxw_clamped(self):
        self.assertEqual(repo_facts.distill_title("Fix the thing", "abc"), "Thing")

    def test_words_env_narrows(self):
        os.environ["GT_LABEL_WORDS"] = "2"
        self.assertEqual(repo_facts.distill_title("Enable dd-trace APM log correlation"),
                         "Log Correlation")

    def test_ascii_separate_is_byte_level(self):
        # Each byte of a multibyte char is its own separator, like LC_ALL=C tr:
        # this is what keeps branch names identical across caller locales.
        self.assertEqual(repo_facts._ascii_separate("Café"), "Caf  ")
        self.assertEqual(repo_facts._ascii_separate("a_b.c-d"), "a b c d")


class SanitizeLabel(Base):
    def test_path_traversal_flattened(self):
        self.assertEqual(repo_facts.sanitize_label("../../etc/passwd"), "etc passwd")

    def test_metacharacters_flattened(self):
        self.assertEqual(repo_facts.sanitize_label("feat/evil; rm -rf ~"),
                         "feat evil rm rf")

    def test_leading_dashes_cannot_survive(self):
        self.assertEqual(repo_facts.sanitize_label("   -rf --force /tmp   "),
                         "rf force tmp")

    def test_single_overlong_word_rejected(self):
        self.assertEqual(repo_facts.sanitize_label("Supercalifragilistic" * 4), "")

    def test_cap_trims_on_word_boundaries(self):
        self.assertEqual(repo_facts.sanitize_label(" ".join(["abcdefghij"] * 10)),
                         " ".join(["abcdefghij"] * 4))

    def test_non_numeric_cap_still_caps(self):
        os.environ["GT_LABEL_MAX_CHARS"] = "48x"
        forty = " ".join(["word"] * 40)
        self.assertEqual(repo_facts.sanitize_label(forty), " ".join(["word"] * 9))

    def test_sane_cap_honored(self):
        os.environ["GT_LABEL_MAX_CHARS"] = "20"
        self.assertEqual(repo_facts.sanitize_label(" ".join(["word"] * 40)),
                         " ".join(["word"] * 4))


class LabelSlugSplit(Base):
    """The core invariant: an override moves the display label, never the slug
    (a branch name is matched against later; a label is not)."""

    SPLIT = "Investigate why the exporter drops rows with no synced_at"

    def test_override_moves_the_label(self):
        os.environ["GT_LABEL_OVERRIDE"] = "Exporter Drops Rows"
        self.assertEqual(repo_facts.label_from_title(self.SPLIT), "Exporter Drops Rows")

    def test_override_does_not_move_the_slug(self):
        os.environ["GT_LABEL_OVERRIDE"] = "Exporter Drops Rows"
        self.assertEqual(repo_facts.slug_title(self.SPLIT),
                         "exporter-drops-rows-no-synced")

    def test_slug_override_is_the_escape_hatch(self):
        os.environ["GT_LABEL_SLUG_OVERRIDE"] = "Exporter Drops Rows"
        self.assertEqual(repo_facts.slug_title(self.SPLIT), "exporter-drops-rows")

    def test_unusable_slug_override_falls_back(self):
        os.environ["GT_LABEL_SLUG_OVERRIDE"] = "!!!"
        self.assertEqual(repo_facts.slug_title("Build the collector adapter contract"),
                         "collector-adapter-contract")

    def test_unusable_label_override_falls_back(self):
        os.environ["GT_LABEL_OVERRIDE"] = "!!!"
        self.assertEqual(repo_facts.label_from_title("Investigate why the exporter drops rows"),
                         "Why Exporter Drops Rows")

    def test_empty_label_override_falls_back(self):
        os.environ["GT_LABEL_OVERRIDE"] = ""
        self.assertEqual(repo_facts.label_from_title("Build the rewards thing", 2),
                         "Rewards Thing")

    def test_unexported_style_padding_is_trimmed(self):
        # Value-level equivalent of the shell suite's IFS cases: padding and
        # separators must not leak into a label or a git ref.
        os.environ["GT_LABEL_SLUG_OVERRIDE"] = "  Rewards/Structures  "
        self.assertEqual(repo_facts.slug_title("Design unified rewards representation"),
                         "rewards-structures")
        os.environ["GT_LABEL_OVERRIDE"] = "  Rewards/Structures  "
        self.assertEqual(repo_facts.label_from_title("Design unified rewards representation"),
                         "Rewards Structures")

    def test_slug_is_locale_independent(self):
        self.assertEqual(repo_facts.slug_title("Café naïve dash parser"),
                         "caf-na-ve-dash-parser")

    def test_slug_words_env(self):
        os.environ["GT_LABEL_SLUG_WORDS"] = "2"
        self.assertEqual(repo_facts.slug_title("Enable dd-trace APM log correlation"),
                         "log-correlation")


class TicketParsing(Base):
    def test_from_branch_matrix(self):
        cases = {"7-first-ticket": "7", "2-sc-5/foo": "5", "sc-1/x-sc-2/y": "2",
                 "release/2-fix": "", "123-": "123", "main": ""}
        for branch, expected in cases.items():
            self.assertEqual(repo_facts.ticket_from_branch(branch), expected, branch)

    def test_scheme_matrix(self):
        cases = {"sc-5/x": "shortcut", "7-foo": "github", "main": "unknown",
                 "2-sc-5/foo": "shortcut", "release/7-foo": "unknown"}
        for branch, expected in cases.items():
            self.assertEqual(repo_facts.ticket_scheme(branch), expected, branch)


class RepoKey(Base):
    def test_url_matrix(self):
        cases = {
            "git@github.com:acme/widgets.git": "acme/widgets",
            "https://github.com/acme/widgets": "acme/widgets",
            "https://github.com/acme/widgets/": "acme/widgets",
            "ssh://git@localhost:1/acme/widgets": "acme/widgets",
            "https://gitlab.com/group/sub/repo.git": "group/sub/repo",
            "host:1234/x": "1234/x",
            "../r": "",
            "https://github.com/acme/../r": "",
            "https://github.com": "",
            "acme/widgets": "",
        }
        for url, expected in cases.items():
            self.assertEqual(repo_facts.repo_key(url), expected, url)


class Overlays(Base):
    def test_default_root(self):
        self.assertEqual(repo_facts.overlays_root(),
                         os.path.join(self.home, ".config", "project-overlays"))

    def test_project_overlays_dir_wins(self):
        os.environ["PROJECT_OVERLAYS_DIR"] = os.path.join(self.root, "elsewhere")
        self.assertEqual(repo_facts.overlays_root(), os.path.join(self.root, "elsewhere"))

    def test_deprecated_var_warns(self):
        os.environ["GIT_TOOLS_PROJECTS_DIR"] = os.path.join(self.root, "old")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(repo_facts.overlays_root(), os.path.join(self.root, "old"))
        self.assertIn("deprecated", err.getvalue())

    def test_overlay_dir_and_claude_dir(self):
        self.overlay_fixture()
        repo = self.fake_remote_repo()
        ov = os.path.join(self.root, "overlays", "acme", "widgets")
        self.assertEqual(repo_facts.overlay_dir(repo), ov)
        self.assertEqual(repo_facts.overlay_claude_dir(repo), f"{ov}/claude")

    def test_overlay_dir_empty_without_origin_key(self):
        _, clone = self.origin_pair()  # local path URL: unparseable key
        self.assertEqual(repo_facts.overlay_dir(clone), "")

    def test_overlay_claude_files_ordering(self):
        self.overlay_fixture()
        repo = self.fake_remote_repo()
        ov = os.path.join(self.root, "overlays", "acme", "widgets", "claude")
        expected = [f"{ov}/agents/alpha.md", f"{ov}/agents/beta.md",
                    f"{ov}/commands/charlie.md", f"{ov}/skills/echo.md",
                    f"{ov}/skills/delta/SKILL.md"]
        self.assertEqual(repo_facts.overlay_claude_files("", repo), expected)
        self.assertEqual(repo_facts.overlay_claude_files("agents", repo), expected[:2])
        self.assertEqual(repo_facts.overlay_claude_files("skills", repo), expected[3:])

    def test_overlay_claude_files_skips_hidden_names(self):
        # Bash globs never match a leading dot; pathlib globs do, so the port
        # must filter the shell's rule back in or transient editor lockfiles
        # and drafts leak into kickoff docs and `project-config list`.
        os.environ["PROJECT_OVERLAYS_DIR"] = os.path.join(self.root, "overlays")
        ov = "overlays/acme/widgets/claude"
        for path in ("agents/.hidden-agent.md", "agents/.#lock.md",
                     "commands/.draft.md", "skills/.hidden.md",
                     "skills/.draft/SKILL.md"):
            self.write(f"{ov}/{path}", "x\n")
        self.write(f"{ov}/agents/alpha.md", "a\n")
        repo = self.fake_remote_repo()
        expected = [os.path.join(self.root, ov, "agents", "alpha.md")]
        self.assertEqual(repo_facts.overlay_claude_files("", repo), expected)
        self.assertEqual(repo_facts.overlay_claude_files("skills", repo), [])

    def test_overlay_claude_files_missing_dirs(self):
        os.environ["PROJECT_OVERLAYS_DIR"] = os.path.join(self.root, "none")
        repo = self.fake_remote_repo()
        self.assertEqual(repo_facts.overlay_claude_files("agents", repo), [])

    def test_overlay_claude_files_matches_glob_collation(self):
        # Bash sorts each glob expansion with the caller's strcoll, not by
        # codepoint: under a UTF-8 locale "Beta" lands between the lowercase
        # names. The listing order is part of the byte-identical contract.
        os.environ["PROJECT_OVERLAYS_DIR"] = os.path.join(self.root, "overlays")
        for name in ("alpha.md", "Beta.md", "gamma.md"):
            self.write(f"overlays/acme/widgets/claude/agents/{name}", "x\n")
        repo = self.fake_remote_repo()
        agents = os.path.join(self.root, "overlays", "acme", "widgets",
                              "claude", "agents")
        script = f'for k in "{agents}"/*.md; do printf "%s\\n" "$k"; done'
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        self.assertEqual(repo_facts.overlay_claude_files("agents", repo),
                         r.stdout.splitlines())


class GitFacts(Base):
    def test_main_root_from_worktree(self):
        _, clone = self.origin_pair()
        self.git(clone, "branch", "7-first-ticket")
        wt = os.path.join(self.root, "wt")
        self.git(clone, "worktree", "add", "-q", wt, "7-first-ticket")
        # realpath: cd -P canonicalizes macOS's /var symlink to /private/var.
        self.assertEqual(repo_facts.main_root(wt), os.path.realpath(clone))
        self.assertEqual(repo_facts.main_root(clone), os.path.realpath(clone))

    def test_main_root_outside_repo(self):
        self.assertEqual(repo_facts.main_root(self.root), "")

    def test_default_branch_tier1_origin_head(self):
        _, clone = self.origin_pair()
        self.git(clone, "symbolic-ref", "refs/remotes/origin/HEAD",
                 "refs/remotes/origin/main")
        self.assertEqual(repo_facts.default_branch(clone), "main")

    def test_default_branch_tier2_remote_show(self):
        _, clone = self.origin_pair()
        self.git(clone, "update-ref", "-d", "refs/remotes/origin/HEAD")
        self.assertEqual(repo_facts.default_branch(clone), "main")

    def test_default_branch_tier3_gh(self):
        repo = self.fake_remote_repo()
        self.gh_stub_path("trunk")
        self.assertEqual(repo_facts.default_branch(repo), "trunk")

    def test_default_branch_unresolved(self):
        repo = self.fake_remote_repo()
        self.no_gh_path()
        self.assertEqual(repo_facts.default_branch(repo), "")

    def test_default_branch_ref_prefers_origin_head(self):
        _, clone = self.origin_pair()
        self.git(clone, "symbolic-ref", "refs/remotes/origin/HEAD",
                 "refs/remotes/origin/main")
        self.assertEqual(repo_facts.default_branch_ref(clone), "origin/main")

    def test_default_branch_ref_probes_usual_names(self):
        _, clone = self.origin_pair()
        self.git(clone, "update-ref", "-d", "refs/remotes/origin/HEAD")
        self.git(clone, "branch", "development")
        self.git(clone, "push", "-q", "origin", "development")
        self.assertEqual(repo_facts.default_branch_ref(clone), "origin/development")

    def test_default_branch_ref_unresolved(self):
        repo = self.fake_remote_repo()
        self.assertEqual(repo_facts.default_branch_ref(repo), "")

    def test_conf_get_precedence(self):
        self.overlay_fixture()
        repo = self.fake_remote_repo()
        self.write("home/.config/start-ticket/config",
                   "provider=machine\nother=machine\nonlymachine=machine\nskipper=machine\n")
        self.assertEqual(repo_facts.conf_get("other", repo), "overlay")
        self.assertEqual(repo_facts.conf_get("onlymachine", repo), "machine")
        self.write("fakerepo/.start-ticket.conf", "provider=repo\n")
        self.assertEqual(repo_facts.conf_get("provider", repo), "repo")

    def test_conf_get_empty_first_line_skips_to_next_file(self):
        self.overlay_fixture()
        repo = self.fake_remote_repo()
        self.write("home/.config/start-ticket/config", "skipper=machine\n")
        self.write("fakerepo/.start-ticket.conf", "skipper=\nskipper=real\n")
        self.assertEqual(repo_facts.conf_get("skipper", repo), "ov")

    def test_conf_get_unset(self):
        self.overlay_fixture()
        repo = self.fake_remote_repo()
        self.assertIsNone(repo_facts.conf_get("nosuchkey", repo))

    def test_conf_get_worktree_inherits_main_root(self):
        _, clone = self.origin_pair()
        self.write("widgets/.start-ticket.conf", "provider=frommain\n")
        self.git(clone, "branch", "7-first-ticket")
        wt = os.path.join(self.root, "wt")
        self.git(clone, "worktree", "add", "-q", wt, "7-first-ticket")
        self.assertEqual(repo_facts.conf_get("provider", wt), "frommain")

    def test_find_doc_repo_beats_overlay(self):
        self.overlay_fixture()
        repo = self.fake_remote_repo()
        self.write("fakerepo/.claude/governor.md", "repo governor\n")
        path, source = repo_facts.find_doc("governor.md", repo)
        self.assertEqual((os.path.basename(path), source), ("governor.md", "repo"))

    def test_find_doc_overlay_claude_subpath(self):
        self.overlay_fixture()
        repo = self.fake_remote_repo()
        path, source = repo_facts.find_doc("kickoff-preamble.md", repo)
        self.assertEqual(source, "overlay")
        self.assertTrue(path.endswith("claude/kickoff-preamble.md"))

    def test_find_doc_missing(self):
        self.overlay_fixture()
        repo = self.fake_remote_repo()
        self.assertIsNone(repo_facts.find_doc("nosuch.md", repo))


class Cli(Base):
    def run_cli(self, *args, cwd=None):
        return subprocess.run([CLI, *args], cwd=cwd or self.root,
                              capture_output=True, check=False)

    def test_single_value_has_no_trailing_newline(self):
        r = self.run_cli("ticket-from-branch", "7-first-ticket")
        self.assertEqual((r.returncode, r.stdout), (0, b"7"))

    def test_main_root_ends_with_newline(self):
        _, clone = self.origin_pair()
        r = self.run_cli("main-root", cwd=clone)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.endswith(b"\n"), r.stdout)
        self.assertEqual(r.stdout.decode().strip(), os.path.realpath(clone))

    def test_list_values_are_newline_terminated(self):
        _, clone = self.origin_pair()
        self.write("widgets/.start-ticket.conf", "provider=repo\n")
        r = self.run_cli("conf-files", cwd=clone)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.endswith(b"\n"))
        self.assertIn(f"{clone}/.start-ticket.conf\n", r.stdout.decode())

    def test_unresolved_facts_exit_1(self):
        # Not a repo: every tier fails, no gh fallback possible.
        r = self.run_cli("default-branch")
        self.assertEqual((r.returncode, r.stdout), (1, b""))
        r = self.run_cli("conf-get", "nosuchkey")
        self.assertEqual((r.returncode, r.stdout), (1, b""))
        r = self.run_cli("find-doc", "nosuch.md")
        self.assertEqual((r.returncode, r.stdout), (1, b""))

    def test_ticket_from_branch_empty_is_not_an_error(self):
        r = self.run_cli("ticket-from-branch", "release/2-fix")
        self.assertEqual((r.returncode, r.stdout), (0, b""))

    def test_get_dispatcher_accepts_underscore_names(self):
        r = self.run_cli("get", "ticket_from_branch", "7-first-ticket")
        self.assertEqual((r.returncode, r.stdout), (0, b"7"))

    def test_get_rejects_unknown_fact(self):
        r = self.run_cli("get", "no_such_fact")
        self.assertEqual(r.returncode, 2)
        self.assertIn(b"unknown fact", r.stderr)

    def test_env_knob_reaches_the_cli(self):
        r = self.run_cli("distill-title", B_TITLE)
        self.assertEqual(r.stdout, b"Data Deletion Retention Policy")
        env = dict(os.environ)
        env["GT_LABEL_NOISE"] = "retention"
        r = subprocess.run([CLI, "distill-title", B_TITLE], cwd=self.root,
                           env=env, capture_output=True, check=False)
        self.assertEqual(r.stdout, b"Billing Data Deletion Policy")

    def test_dash_leading_value_is_a_value(self):
        # The shell functions took "$1" verbatim, so a leading dash is data.
        r = self.run_cli("sanitize-label", "--force")
        self.assertEqual((r.returncode, r.stdout), (0, b"force"))
        r = self.run_cli("ticket-scheme", "-h")
        self.assertEqual((r.returncode, r.stdout), (0, b"unknown"))
        r = self.run_cli("distill-title", "-Fix the thing")
        self.assertEqual((r.returncode, r.stdout), (0, b"Thing"))

    def test_argless_fact_subcommands_still_work(self):
        # overlays-root takes no positional: the "--" guard for dash values
        # must not itself become an unrecognized argument.
        r = self.run_cli("overlays-root")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.endswith(b"project-overlays"), r.stdout)

    def test_crlf_conf_value_keeps_carriage_return(self):
        # sed split on \n only, so the \r of a CRLF file stayed in the value.
        repo = self.fake_remote_repo()
        Path(os.path.join(repo, ".start-ticket.conf")).write_bytes(
            b"color=green\r\n")
        r = self.run_cli("conf-get", "color", cwd=repo)
        self.assertEqual((r.returncode, r.stdout), (0, b"green\r"))

    def test_non_utf8_remote_url_degrades_to_no_overlay(self):
        # Old bash: =~ fails on invalid UTF-8, so repo_key printed nothing,
        # rc 0. A traceback here would abort set -e callers.
        repo = self.fake_remote_repo()
        subprocess.run(["git", "-C", repo, "config", "remote.origin.url",
                        b"git@host:acme/wi\xd0gets.git"],
                       check=True, capture_output=True)
        r = self.run_cli("overlay-dir", repo)
        self.assertEqual((r.returncode, r.stdout), (0, b""))


class Facade(Base):
    """The compatibility surface bash consumers actually execute: the gt::
    wrappers, the _gt env forwarding, and the native ticket functions
    (project-config.test.sh already covers gt::repo_key)."""

    LIB = os.path.join(HERE, "repo-facts.sh")

    def gt(self, call):
        r = subprocess.run(
            ["bash", "-c", f'source "{self.LIB}"; printf "%s" "$({call})"'],
            capture_output=True, text=True)
        return r.returncode, r.stdout

    def test_forwards_unexported_knobs(self):
        # worktree-manager assigns GT_LABEL_NOISE without export; only the
        # facade's forward list carries it to the CLI child process.
        rc, out = self.gt(f'GT_LABEL_NOISE=retention gt::distill_title "{B_TITLE}"')
        self.assertEqual((rc, out), (0, "Billing Data Deletion Policy"))

    def test_forwards_label_override(self):
        rc, out = self.gt('GT_LABEL_OVERRIDE="Rewards Structures" '
                          'gt::label_from_title "Build the rewards thing"')
        self.assertEqual((rc, out), (0, "Rewards Structures"))

    def test_ticket_from_branch_matrix(self):
        cases = {"7-first-ticket": "7", "2-sc-5/foo": "5", "sc-1/x-sc-2/y": "2",
                 "release/2-fix": "", "main": ""}
        for branch, expected in cases.items():
            self.assertEqual(self.gt(f'gt::ticket_from_branch "{branch}"'),
                             (0, expected), branch)

    def test_ticket_scheme_matrix(self):
        cases = {"sc-5/x": "shortcut", "7-foo": "github", "main": "unknown",
                 "2-sc-5/foo": "shortcut", "release/7-foo": "unknown"}
        for branch, expected in cases.items():
            self.assertEqual(self.gt(f'gt::ticket_scheme "{branch}"'),
                             (0, expected), branch)

    def test_exit_code_propagation(self):
        r = subprocess.run(
            ["bash", "-c",
             f'source "{self.LIB}"; gt::conf_get nosuchkey "{self.root}"; exit $?'],
            capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (1, ""))

    def test_dash_value_through_the_facade(self):
        self.assertEqual(self.gt("gt::sanitize_label --force"), (0, "force"))


if __name__ == "__main__":
    unittest.main()
