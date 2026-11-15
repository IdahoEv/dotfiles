"""Tests for agy_tmux_dashboard.py.

Run:
    python3 -m unittest tools/lib/agy_tmux_dashboard_test.py
"""

from __future__ import annotations

import curses
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import agy_tmux_dashboard as dash  # noqa: E402


class TestHelpers(unittest.TestCase):
    def test_format_age(self):
        self.assertEqual(dash.format_age(0), "0s")
        self.assertEqual(dash.format_age(42), "42s")
        self.assertEqual(dash.format_age(125), "2m")
        self.assertEqual(dash.format_age(7200), "2h")

    def test_compute_status(self):
        self.assertEqual(dash.compute_status(True, 1000, 1001), "exited")
        self.assertEqual(dash.compute_status(False, 1000, 1003), "running")
        self.assertEqual(dash.compute_status(False, 1000, 1045), "idle (45s)")
        self.assertEqual(dash.compute_status(False, None, 1045), "running")

    def test_extract_last_line(self):
        text = "line one\n\n   line   two  \n   \n"
        self.assertEqual(dash.extract_last_line(text), "line two")
        self.assertEqual(dash.extract_last_line("\n\n"), "")

    def test_load_workstream_meta_reads_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec_path = Path(tmp) / ".workstream.json"
            rec_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "kind": "ticket",
                        "tickets": [{"id": "12", "url": ""}, {"id": "13", "url": ""}],
                        "ticket_provider": "github",
                        "key": "Is12+13",
                        "desc": "Add OAuth flow",
                    }
                ),
                encoding="utf-8",
            )
            ref, desc = dash.load_workstream_meta(tmp)
            self.assertEqual(ref, "Is12+13")
            self.assertEqual(desc, "Add OAuth flow")

    def test_load_workstream_meta_fallback_from_tickets(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec_path = Path(tmp) / ".workstream.json"
            rec_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "kind": "ticket",
                        "tickets": [{"id": "12", "url": ""}, {"id": "13", "url": ""}],
                        "ticket_provider": "shortcut",
                        "key": "",
                        "desc": "",
                    }
                ),
                encoding="utf-8",
            )
            ref, desc = dash.load_workstream_meta(tmp)
            self.assertEqual(ref, "sc-12+13")
            self.assertEqual(desc, "")

    def test_render_lines_includes_rows_and_footer(self):
        rows = [
            dash.WorkstreamRow(
                window_index="1",
                window_name="Is183",
                pane_id="%1",
                pane_path="/tmp/wt1",
                ticket_ref="Is183",
                desc="Agy tmux dashboard",
                branch="Is183-agy-tmux",
                status="idle (12s)",
                last_line="Waiting for plan approval?",
            )
        ]
        lines = dash.render_lines(rows, selected=0, width=100, session="agy-dotfiles")
        joined = "\n".join(lines)
        self.assertIn("agy-dotfiles", joined)
        self.assertIn("Is183", joined)
        self.assertIn("idle (12s)", joined)
        self.assertIn("Waiting for plan approval?", joined)
        self.assertIn("Ctrl-z", joined)

    def test_render_lines_viewport_keeps_selected_and_footer_visible(self):
        rows = [
            dash.WorkstreamRow(
                window_index=str(i + 1),
                window_name=f"Is{i + 1}",
                pane_id=f"%{i + 1}",
                pane_path=f"/tmp/wt{i + 1}",
                ticket_ref=f"Is{i + 1}",
                desc=f"Task {i + 1}",
                branch="",
                status="running",
                last_line="working",
            )
            for i in range(10)
        ]
        lines = dash.render_lines(rows, selected=7, width=100, session="agy-dotfiles", max_rows=3)
        joined = "\n".join(lines)
        self.assertIn("Is8", joined)
        self.assertIn("Ctrl-z", joined)
        self.assertEqual(len(lines), 8)  # 3 header + 3 rows + 2 footer

    def test_fetch_windows_skips_dashboard_window_zero_and_git_when_desc_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "wt"
            wt.mkdir()
            (wt / ".workstream.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "kind": "ticket",
                        "tickets": [{"id": "183", "url": ""}],
                        "ticket_provider": "github",
                        "key": "Is183",
                        "desc": "Dashboard",
                    }
                ),
                encoding="utf-8",
            )
            list_out = (
                f"0\tdashboard\t%0\t{tmp}\t0\t1000\n"
                f"1\tIs183\t%1\t{wt}\t0\t950\n"
            )

            def fake_run(cmd: list[str]) -> str:
                if "list-windows" in cmd:
                    return list_out
                if "capture-pane" in cmd:
                    return "Proposing plan...\nReady for review?\n"
                return ""

            with (
                mock.patch.object(dash, "_run_cmd", side_effect=fake_run),
                mock.patch.object(dash, "_git_branch") as git_mock,
                mock.patch.object(dash, "resolve_project_color", return_value="green"),
            ):
                rows = dash.fetch_windows("agy-dotfiles", now=1000)

            git_mock.assert_not_called()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].window_index, "1")
            self.assertEqual(rows[0].ticket_ref, "Is183")
            self.assertEqual(rows[0].status, "idle (50s)")
            self.assertEqual(rows[0].last_line, "Ready for review?")
            self.assertEqual(rows[0].color, "green")

    def test_fetch_windows_pane_dead_and_missing_workstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "wt"
            wt.mkdir()
            list_out = f"1\tIs99\t%1\t{wt}\t1\t950\n"

            def fake_run(cmd: list[str]) -> str:
                if "list-windows" in cmd:
                    return list_out
                if "capture-pane" in cmd:
                    return "Done\n"
                return ""

            with (
                mock.patch.object(dash, "_run_cmd", side_effect=fake_run),
                mock.patch.object(dash, "_git_branch", return_value="Is99-some-branch"),
            ):
                rows = dash.fetch_windows("agy-dotfiles", now=1000)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].ticket_ref, "Is99")
            self.assertEqual(rows[0].desc, "Is99-some-branch")
            self.assertEqual(rows[0].status, "exited")

    def test_curses_loop_skips_fetch_on_navigation_and_uses_tmux_bin(self):
        rows = [
            dash.WorkstreamRow("1", "Is1", "%1", "/tmp/1", "Is1", "One", "", "running", "ok"),
            dash.WorkstreamRow("2", "Is2", "%2", "/tmp/2", "Is2", "Two", "", "exited", "done"),
        ]
        keys = [ord("j"), ord("k"), ord("r"), ord("j"), ord("x")]

        class FakeStdscr:
            def keypad(self, _flag): pass
            def timeout(self, _ms): pass
            def getmaxyx(self): return (24, 100)
            def erase(self): pass
            def addnstr(self, *_args): pass
            def refresh(self): pass
            def getch(self):
                if keys:
                    return keys.pop(0)
                raise StopIteration

        with (
            mock.patch.object(curses, "curs_set"),
            mock.patch.object(curses, "has_colors", return_value=False),
            mock.patch.object(dash, "fetch_windows", return_value=rows) as fetch_mock,
            mock.patch.object(dash, "_kill_window") as kill_mock,
        ):
            with self.assertRaises(StopIteration):
                dash._curses_loop(FakeStdscr(), "agy-dotfiles", None, 2.0, tmux_bin="/custom/tmux")

        # Initial fetch + 1 on 'r' + 1 after 'x' killing exited window = 3 (not 6)
        self.assertEqual(fetch_mock.call_count, 3)
        fetch_mock.assert_called_with("agy-dotfiles", tmux_bin="/custom/tmux", socket=None)
        kill_mock.assert_called_once_with(["/custom/tmux"], "agy-dotfiles", "2")

    def test_main_honors_agy_tmux_bin_env(self):
        with (
            mock.patch.dict(os.environ, {"AGY_TMUX_TMUX_BIN": "/env/tmux"}),
            mock.patch.object(curses, "wrapper") as wrapper_mock,
        ):
            dash.main(["--session", "agy-dotfiles"])
        wrapper_mock.assert_called_once_with(dash._curses_loop, "agy-dotfiles", None, 2.0, "/env/tmux")


class TestProjectColors(unittest.TestCase):
    def test_resolve_color_conf_override_beats_project_colors(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "Kardashev" / "wt1"
            wt.mkdir(parents=True)
            colors_file = Path(tmp) / "project-colors"
            colors_file.write_text("# comment\nKardashev purple\n", encoding="utf-8")

            with (
                mock.patch.object(dash.repo_facts, "conf_get", return_value="  Cyan \r"),
                mock.patch.object(dash.repo_facts, "main_root", return_value=str(Path(tmp) / "Kardashev")),
            ):
                self.assertEqual(dash.resolve_project_color(str(wt), colors_file=colors_file), "cyan")

    def test_resolve_color_falls_back_to_project_colors_when_conf_unset_or_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "Kardashev" / "wt1"
            wt.mkdir(parents=True)
            colors_file = Path(tmp) / "project-colors"
            colors_file.write_text(
                "# header\n\ndotfiles green\nkardashev Purple\n",
                encoding="utf-8",
            )

            for conf_val in (None, "   "):
                with (
                    mock.patch.object(dash.repo_facts, "conf_get", return_value=conf_val),
                    mock.patch.object(dash.repo_facts, "main_root", return_value=str(Path(tmp) / "Kardashev")),
                ):
                    self.assertEqual(dash.resolve_project_color(str(wt), colors_file=colors_file), "purple")

    def test_resolve_color_unknown_project_and_invalid_color_return_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "unknown-repo"
            wt.mkdir()
            colors_file = Path(tmp) / "project-colors"
            colors_file.write_text("dotfiles green\n", encoding="utf-8")

            with (
                mock.patch.object(dash.repo_facts, "conf_get", return_value=None),
                mock.patch.object(dash.repo_facts, "main_root", return_value=str(wt)),
            ):
                self.assertEqual(dash.resolve_project_color(str(wt), colors_file=colors_file), "")

            with (
                mock.patch.object(dash.repo_facts, "conf_get", return_value="teal"),
                mock.patch.object(dash.repo_facts, "main_root", return_value=str(wt)),
            ):
                self.assertEqual(dash.resolve_project_color(str(wt), colors_file=colors_file), "")

        self.assertEqual(dash.resolve_project_color("/nonexistent/path/for/test"), "")


class TestColorRendering(unittest.TestCase):
    def test_init_color_pairs_without_color_support_returns_empty(self):
        with mock.patch.object(curses, "has_colors", return_value=False):
            self.assertEqual(dash.init_color_pairs(), {})

        with (
            mock.patch.object(curses, "has_colors", return_value=True),
            mock.patch.object(curses, "start_color", side_effect=curses.error),
        ):
            self.assertEqual(dash.init_color_pairs(), {})

    def test_init_color_pairs_initializes_all_palette_colors(self):
        with (
            mock.patch.object(curses, "has_colors", return_value=True),
            mock.patch.object(curses, "start_color"),
            mock.patch.object(curses, "use_default_colors"),
            mock.patch.object(curses, "init_pair") as init_pair_mock,
            mock.patch.object(curses, "COLORS", 256, create=True),
        ):
            pairs = dash.init_color_pairs()

        self.assertEqual(set(pairs.keys()), set(dash.PALETTE))
        self.assertEqual(init_pair_mock.call_count, len(dash.PALETTE))

    def test_draw_row_colorizes_ticket_and_title_with_color_support(self):
        calls: list[tuple[int, int, str, int, int]] = []

        class FakeStdscr:
            def addnstr(self, y, x, text, n, attr):
                calls.append((y, x, text, n, attr))

        row = dash.WorkstreamRow(
            window_index="1",
            window_name="Is187",
            pane_id="%1",
            pane_path="/tmp/wt1",
            ticket_ref="Is187",
            desc="Port project colors",
            branch="",
            status="running",
            last_line="ok",
            color="green",
        )
        line = dash.render_lines([row], selected=0, width=100, session="agy-dotfiles")[3]

        with mock.patch.object(curses, "color_pair", return_value=0x200) as cp_mock:
            dash._draw_row(FakeStdscr(), 3, line, 100, row, is_selected=True, color_pairs={"green": 3})

        cp_mock.assert_called_once_with(3)
        self.assertEqual(calls[0][1], 0)
        self.assertEqual(calls[0][4], curses.A_REVERSE)
        # Ticket column (x=6) and Title column (x=32) get color_pair | A_REVERSE
        self.assertEqual([(c[1], c[4]) for c in calls[1:]], [(6, curses.A_REVERSE | 0x200), (32, curses.A_REVERSE | 0x200)])

    def test_draw_row_falls_back_to_unstyled_without_color_support(self):
        calls: list[tuple[int, int, str, int, int]] = []

        class FakeStdscr:
            def addnstr(self, y, x, text, n, attr):
                calls.append((y, x, text, n, attr))

        row = dash.WorkstreamRow(
            window_index="1",
            window_name="Is187",
            pane_id="%1",
            pane_path="/tmp/wt1",
            ticket_ref="Is187",
            desc="Port project colors",
            branch="",
            status="running",
            last_line="ok",
            color="green",
        )
        line = dash.render_lines([row], selected=0, width=100, session="agy-dotfiles")[3]

        with mock.patch.object(curses, "color_pair") as cp_mock:
            dash._draw_row(FakeStdscr(), 3, line, 100, row, is_selected=False, color_pairs={})

        cp_mock.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][4], curses.A_NORMAL)


if __name__ == "__main__":
    unittest.main()
