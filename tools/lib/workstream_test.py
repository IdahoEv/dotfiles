"""Tests for workstream record, resolver, and settings layering.

    python3 -m unittest tools/lib/workstream_test.py
"""

from __future__ import annotations

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

import repo_facts  # noqa: E402
import workstream  # noqa: E402

CLI = os.path.join(os.path.dirname(HERE), "workstream.sh")


class WorkstreamTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="workstream-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self._saved_env = dict(os.environ)
        for k in list(os.environ):
            if k.startswith(("GT_", "WORKSTREAM_", "PROJECT_OVERLAYS_", "GIT_TOOLS_")):
                os.environ.pop(k, None)
        os.environ["HOME"] = self.home
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved_env)

    def write(self, relpath: str, text: str) -> str:
        path = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")
        return path

    def make_repo(self, name: str = "widgets") -> str:
        repo = os.path.join(self.root, name)
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        subprocess.run(["git", "-C", repo, "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", repo, "config", "user.name", "T"], check=True)
        subprocess.run(
            ["git", "-C", repo, "remote", "add", "origin", f"git@github.com:acme/{name}.git"],
            check=True,
        )
        subprocess.run(["git", "-C", repo, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        return repo


class SettingsLayeringTests(WorkstreamTestBase):
    def test_layer_precedence_project_machine_user_default(self) -> None:
        repo = self.make_repo("widgets")
        overlays = os.path.join(self.home, ".config", "project-overlays")
        self.write("home/.config/start-ticket/user.conf", "base={key}_{desc}\nuser_only=u\n")
        self.write("home/.config/project-overlays/start-ticket.conf", "base={key}-{desc}\nstore_user=su\n")
        self.write("home/.config/start-ticket/config", "base={key}:{desc}\nmachine_only=m\n")
        self.write("home/.config/project-overlays/acme/widgets/start-ticket.conf", "base={key}/{desc}\noverlay_only=ov\n")
        self.write("widgets/.start-ticket.conf", "base={key} {desc}\n")

        val, src = workstream.resolve_setting("base", repo, default="{key} {desc}")
        self.assertEqual((val, src), ("{key} {desc}", "project"))

        val, src = workstream.resolve_setting("overlay_only", repo, default="def")
        self.assertEqual((val, src), ("ov", "project"))

        val, src = workstream.resolve_setting("machine_only", repo, default="def")
        self.assertEqual((val, src), ("m", "machine"))

        val, src = workstream.resolve_setting("store_user", repo, default="def")
        self.assertEqual((val, src), ("su", "user"))

        val, src = workstream.resolve_setting("user_only", repo, default="def")
        self.assertEqual((val, src), ("u", "user"))

        val, src = workstream.resolve_setting("missing_key", repo, default="fallback")
        self.assertEqual((val, src), ("fallback", "default"))
        self.assertTrue(os.path.isdir(overlays))

    def test_template_source_detection(self) -> None:
        repo = self.make_repo("widgets")
        self.assertEqual(workstream.detect_template_source(repo), "default")

        self.write("home/.config/start-ticket/user.conf", "commit.key_prefix=true\n")
        self.assertEqual(workstream.detect_template_source(repo), "user")
        self.write("home/.config/start-ticket/user.conf", "")

        self.write("home/.config/start-ticket/user.conf", "branch.form=snake\n")
        self.assertEqual(workstream.detect_template_source(repo), "user")

        self.write("home/.config/start-ticket/config", "pr.template={type}: {base}\n")
        self.assertEqual(workstream.detect_template_source(repo), "machine")

        self.write("widgets/.start-ticket.conf", "row.form=Title\n")
        self.assertEqual(workstream.detect_template_source(repo), "project")

    def test_env_override_in_resolve_setting(self) -> None:
        repo = self.make_repo("widgets")
        self.write("widgets/.start-ticket.conf", "label_noise=fromrepo\n")
        os.environ["GT_LABEL_NOISE"] = "fromenv"
        val, src = workstream.resolve_setting("label_noise", repo, env_var="GT_LABEL_NOISE", default="")
        self.assertEqual(val, "fromenv")


class RecordPersistenceTests(WorkstreamTestBase):
    def test_save_and_load_record_and_exclude(self) -> None:
        repo = self.make_repo("widgets")
        rec = workstream.WorkstreamRecord(
            kind="ticket",
            tickets=[
                {"id": "312", "url": "https://github.com/acme/widgets/issues/312"},
                {"id": "313", "url": "https://github.com/acme/widgets/issues/313"},
            ],
            ticket_provider="github",
            key="Is312+313",
            key_aliases=["Is312"],
            desc="invoice totals",
            type="bug",
            template_source="default",
            tags=["PLAN"],
            pr={"number": 42, "url": "https://github.com/acme/widgets/pull/42"},
            reviews={"local": 2, "remote": 1},
            claude_sessions=["sess-1"],
        )
        path = workstream.save_record(repo, rec)
        self.assertEqual(path, os.path.join(repo, ".workstream.json"))
        self.assertTrue(os.path.isfile(path))

        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(
            set(raw.keys()),
            {
                "version",
                "kind",
                "tickets",
                "ticket_provider",
                "key",
                "key_aliases",
                "desc",
                "type",
                "template_source",
                "tags",
                "pr",
                "reviews",
                "claude_sessions",
            },
        )
        self.assertEqual(raw["version"], 1)

        loaded = workstream.load_record(repo)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.key, "Is312+313")
        self.assertEqual(loaded.tickets, rec.tickets)
        self.assertEqual(loaded.key_aliases, ["Is312"])
        self.assertEqual(loaded.pr, {"number": 42, "url": "https://github.com/acme/widgets/pull/42"})
        self.assertEqual(loaded.reviews, {"local": 2, "remote": 1})

        # Verify .git/info/exclude contains .workstream.json once even after multiple saves
        workstream.save_record(repo, rec)
        exclude_path = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--git-path", "info/exclude"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if not os.path.isabs(exclude_path):
            exclude_path = os.path.join(repo, exclude_path)
        exclude_lines = [
            line.strip()
            for line in Path(exclude_path).read_text(encoding="utf-8").splitlines()
            if line.strip() == ".workstream.json"
        ]
        self.assertEqual(exclude_lines, [".workstream.json"])

        # git status --porcelain should ignore .workstream.json
        st = subprocess.run(
            ["git", "-C", repo, "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(st, "")

    def test_save_record_fails_closed_when_exclude_unwritable(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("chmod does not restrict root")
        repo = self.make_repo("widgets")
        exclude_path = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--git-path", "info/exclude"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if not os.path.isabs(exclude_path):
            exclude_path = os.path.join(repo, exclude_path)
        Path(exclude_path).parent.mkdir(parents=True, exist_ok=True)
        Path(exclude_path).write_text("", encoding="utf-8")
        os.chmod(exclude_path, 0o444)
        try:
            rec = workstream.WorkstreamRecord(key="Is1", ticket_provider="github")
            with self.assertRaises(OSError):
                workstream.save_record(repo, rec)
            self.assertFalse(os.path.exists(os.path.join(repo, ".workstream.json")))
        finally:
            os.chmod(exclude_path, 0o644)

    def test_legacy_chain_file_fallback(self) -> None:
        repo = self.make_repo("widgets")
        subprocess.run(["git", "-C", repo, "checkout", "-q", "-b", "12-head-ticket"], check=True)
        git_dir = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--absolute-git-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        Path(os.path.join(git_dir, "chain")).write_text("12\n13\n14\n", encoding="utf-8")

        loaded = workstream.load_record(repo)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.kind, "ticket")
        self.assertEqual(loaded.ticket_provider, "github")
        self.assertEqual([t["id"] for t in loaded.tickets], ["12", "13", "14"])
        self.assertEqual(loaded.key, "Is12+13+14")
        self.assertEqual(workstream.chain_ids(repo, "12"), ["12", "13", "14"])
        self.assertEqual(workstream.chain_tag(repo), "12+13+14")

    def test_chain_tag_collapses_four_or_more_tickets(self) -> None:
        repo = self.make_repo("widgets")
        rec = workstream.init_ticket_record(
            repo,
            provider="github",
            tickets=[
                {"id": "7", "url": ""},
                {"id": "8", "url": ""},
                {"id": "9", "url": ""},
                {"id": "10", "url": ""},
            ],
            title="Ticket 7",
        )
        self.assertEqual(rec.key, "Is7+8+9+10")
        self.assertEqual(workstream.chain_tag(repo), "7+10")

        # Single-ticket re-run on an existing chain worktree preserves the chain
        rec2 = workstream.init_ticket_record(
            repo,
            provider="github",
            tickets=[{"id": "7", "url": "https://example.test/7"}],
            title="Ticket 7",
        )
        self.assertEqual([t["id"] for t in rec2.tickets], ["7", "8", "9", "10"])
        self.assertEqual(rec2.tickets[0]["url"], "https://example.test/7")

    def test_init_for_different_ticket_drops_prior_state(self) -> None:
        repo = self.make_repo("widgets")
        rec = workstream.init_ticket_record(
            repo, provider="github", tickets=[{"id": "7", "url": ""}], title="Ticket 7"
        )
        rec.pr = {"number": 1, "url": "u"}
        rec.reviews = {"local": 2, "remote": 1}
        workstream.save_record(repo, rec)
        rec9 = workstream.init_ticket_record(
            repo, provider="github", tickets=[{"id": "9", "url": ""}], title="Ticket 9"
        )
        self.assertIsNone(rec9.pr)
        self.assertEqual(rec9.reviews, {"local": 0, "remote": 0})

    def test_malformed_record_shape_falls_back(self) -> None:
        repo = self.make_repo("widgets")
        self.write("widgets/.workstream.json", '{"tickets": 5}')
        self.assertIsNone(workstream.load_record(repo))
        self.assertEqual(workstream.chain_ids(repo, "7"), ["7"])

    def test_key_follows_settings_changed_after_init(self) -> None:
        repo = self.make_repo("widgets")
        rec = workstream.init_ticket_record(
            repo,
            provider="github",
            tickets=[{"id": "7", "url": ""}, {"id": "8", "url": ""}],
            title="Ticket 7",
        )
        self.assertEqual(workstream.render_surface(rec, "key", repo), "Is7+8")
        self.write("widgets/.start-ticket.conf", "chain.sep=-\n")
        self.assertEqual(workstream.render_surface(rec, "key", repo), "Is7-8")


class ResolverTests(WorkstreamTestBase):
    def test_builtin_defaults_github_chain_and_shortcut(self) -> None:
        repo = self.make_repo("widgets")
        gh_rec = workstream.WorkstreamRecord(
            kind="ticket",
            tickets=[
                {"id": "312", "url": ""},
                {"id": "313", "url": ""},
                {"id": "315", "url": ""},
            ],
            ticket_provider="github",
            key="Is312+313+315",
            desc="invoice totals",
            tags=["WIP"],
        )
        self.assertEqual(workstream.render_surface(gh_rec, "key", repo), "Is312+313+315")
        self.assertEqual(workstream.render_surface(gh_rec, "branch", repo), "Is312+313+315-invoice-totals")
        self.assertEqual(workstream.render_surface(gh_rec, "worktree", repo), "Is312+313+315-invoice-totals")
        self.assertEqual(workstream.render_surface(gh_rec, "row", repo), "[WIP] Is312+313+315 invoice totals")
        self.assertEqual(workstream.render_surface(gh_rec, "pr", repo), "Is312+313+315: invoice totals")
        self.assertEqual(workstream.render_surface(gh_rec, "commit", repo), "invoice totals")

        sc_rec = workstream.WorkstreamRecord(
            kind="ticket",
            tickets=[{"id": "7435", "url": ""}],
            ticket_provider="shortcut",
            key="sc-7435",
            desc="invoice totals",
            tags=["PLAN"],
        )
        self.assertEqual(workstream.render_surface(sc_rec, "key", repo), "sc-7435")
        self.assertEqual(workstream.render_surface(sc_rec, "branch", repo), "sc-7435-invoice-totals")
        self.assertEqual(workstream.render_surface(sc_rec, "worktree", repo), "sc-7435-invoice-totals")
        self.assertEqual(workstream.render_surface(sc_rec, "row", repo), "[PLAN] sc-7435 invoice totals")
        self.assertEqual(workstream.render_surface(sc_rec, "pr", repo), "sc-7435: invoice totals")

    def test_surface_form_and_template_overrides(self) -> None:
        repo = self.make_repo("widgets")
        self.write(
            "widgets/.start-ticket.conf",
            "branch.template={type}/{base}\n"
            "pr.template={type}: {base}\n"
            "row.form=Title\n",
        )
        rec = workstream.WorkstreamRecord(
            kind="ticket",
            tickets=[{"id": "312", "url": ""}, {"id": "313", "url": ""}],
            ticket_provider="github",
            key="Is312+313",
            desc="invoice totals",
            type="bug",
            tags=["WIP"],
        )
        self.assertEqual(workstream.render_surface(rec, "branch", repo), "bug/Is312+313-invoice-totals")
        self.assertEqual(workstream.render_surface(rec, "worktree", repo), "bug-Is312+313-invoice-totals")
        self.assertEqual(workstream.render_surface(rec, "pr", repo), "bug: Is312+313 invoice totals")
        self.assertEqual(workstream.render_surface(rec, "row", repo), "[WIP] Is312+313 Invoice Totals")

        # When type is empty, leading {type}/ or {type}: collapses cleanly
        rec.type = ""
        self.assertEqual(workstream.render_surface(rec, "branch", repo), "Is312+313-invoice-totals")
        self.assertEqual(workstream.render_surface(rec, "pr", repo), "Is312+313 invoice totals")

    def test_tokens_provider_chain_desc_phase(self) -> None:
        repo = self.make_repo("widgets")
        rec = workstream.WorkstreamRecord(
            kind="ticket",
            tickets=[
                {"id": "312", "url": ""},
                {"id": "313", "url": ""},
                {"id": "315", "url": ""},
            ],
            ticket_provider="github",
            key="Is312+313+315",
            desc="SQL invoice totals",
            type="feature",
            tags=["REVIEW", "PR"],
        )
        self.assertEqual(
            workstream.render_template("{provider:full}-{chain:first}..{chain:last} {desc:snake}", rec, form="words", dir_=repo),
            "Issue-312..315 sql_invoice_totals",
        )
        self.assertEqual(
            workstream.render_template("{phase} {key} {desc:Title}", rec, form="words", dir_=repo),
            "[REVIEW][PR] Is312+313+315 SQL Invoice Totals",
        )


class CliTests(WorkstreamTestBase):
    def test_cli_init_render_and_chain_ids(self) -> None:
        repo = self.make_repo("widgets")
        r = subprocess.run(
            [
                CLI,
                "init-ticket",
                "--dir",
                repo,
                "--provider",
                "github",
                "--ids",
                "312,313,315",
                "--urls",
                "https://e/312,https://e/313,https://e/315",
                "--title",
                "Fix invoice totals in staging",
                "--tag",
                "PLAN",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        r_ids = subprocess.run(
            [CLI, "chain-ids", "--dir", repo],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(r_ids.stdout.strip(), "312,313,315")

        r_branch = subprocess.run(
            [CLI, "render", "branch", "--dir", repo],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(r_branch.stdout.strip(), "Is312+313+315-invoice-totals-staging")

    def test_cli_ephemeral_render_without_record(self) -> None:
        repo = self.make_repo("widgets")
        r_branch = subprocess.run(
            [
                CLI,
                "render",
                "branch",
                "--dir",
                repo,
                "--provider",
                "shortcut",
                "--ids",
                "7435",
                "--title",
                "Fix invoice totals",
                "--type",
                "fix",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(r_branch.stdout.strip(), "sc-7435-invoice-totals")
        self.assertFalse(os.path.exists(os.path.join(repo, ".workstream.json")))

    def test_acronym_preserved_in_record_and_title_surface(self) -> None:
        repo = self.make_repo("widgets")
        rec = workstream.init_ticket_record(
            repo,
            provider="github",
            tickets=[{"id": "160"}],
            title="Fix SQL invoice totals",
        )
        self.assertIn("SQL", rec.desc)
        rendered = workstream.render_surface(rec, "row", repo)
        self.assertIn("SQL", rendered)

    def test_gt_label_override_ignored_for_branch_and_record(self) -> None:
        repo = self.make_repo("widgets")
        old_label = os.environ.get("GT_LABEL_OVERRIDE")
        old_slug = os.environ.get("GT_LABEL_SLUG_OVERRIDE")
        try:
            os.environ["GT_LABEL_OVERRIDE"] = "Custom Display Only"
            os.environ.pop("GT_LABEL_SLUG_OVERRIDE", None)
            rec = workstream.init_ticket_record(
                repo,
                provider="github",
                tickets=[{"id": "160"}],
                title="Fix invoice totals",
            )
            self.assertEqual(workstream.render_surface(rec, "branch", repo), "Is160-invoice-totals")
            os.environ["GT_LABEL_SLUG_OVERRIDE"] = "Custom Slug"
            rec2 = workstream.init_ticket_record(
                repo,
                provider="github",
                tickets=[{"id": "161"}],
                title="Fix invoice totals",
            )
            self.assertEqual(workstream.render_surface(rec2, "branch", repo), "Is161-custom-slug")
        finally:
            if old_label is None:
                os.environ.pop("GT_LABEL_OVERRIDE", None)
            else:
                os.environ["GT_LABEL_OVERRIDE"] = old_label
            if old_slug is None:
                os.environ.pop("GT_LABEL_SLUG_OVERRIDE", None)
            else:
                os.environ["GT_LABEL_SLUG_OVERRIDE"] = old_slug

    def test_cli_render_punctuation_desc_falls_back_to_title(self) -> None:
        repo = self.make_repo("widgets")
        r = subprocess.run(
            [
                CLI,
                "render",
                "branch",
                "--dir",
                repo,
                "--provider",
                "github",
                "--ids",
                "160",
                "--title",
                "Fix invoice totals",
                "--desc",
                "???",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(r.stdout.strip(), "Is160-invoice-totals")


if __name__ == "__main__":
    unittest.main()
