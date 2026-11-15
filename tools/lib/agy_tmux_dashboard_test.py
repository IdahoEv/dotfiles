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
            ):
                rows = dash.fetch_windows("agy-dotfiles", now=1000)

            git_mock.assert_not_called()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].window_index, "1")
            self.assertEqual(rows[0].ticket_ref, "Is183")
            self.assertEqual(rows[0].status, "idle (50s)")
            self.assertEqual(rows[0].last_line, "Ready for review?")

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


if __name__ == "__main__":
    unittest.main()
