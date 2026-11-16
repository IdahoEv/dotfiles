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
        wrapper_mock.assert_called_once_with(dash._curses_loop, "agy-dotfiles", None, 2.0, "/env/tmux", "")


class TestMemoryColumn(unittest.TestCase):
    def _row(self, mem=""):
        return dash.WorkstreamRow("1", "Is5", "%1", "/x", "Is5", "desc", "b", "running", "out", mem=mem)

    def test_render_shows_mem_and_host_line(self):
        lines = dash.render_lines([self._row("~1.2 GB")], 0, 120, "s", host_line="host pressure: warn  [WARN]")
        self.assertIn("host pressure: warn", lines[0])
        self.assertIn("Mem", lines[2])
        self.assertIn("~1.2 GB", lines[3])

    def test_unmeasured_row_shows_dash(self):
        lines = dash.render_lines([self._row()], 0, 120, "s")
        self.assertIn(" - ", lines[3])

    def _provider(self, payload, rc=0):
        import subprocess as sp
        out = payload if isinstance(payload, str) else json.dumps(payload)
        return mock.patch.object(dash.subprocess, "run", return_value=sp.CompletedProcess([], rc, out, ""))

    def test_no_provider_means_no_memory_column(self):
        self.assertEqual(dash.fetch_memory(""), ({}, ""))

    def test_fetch_memory_never_raises(self):
        with mock.patch.object(dash.subprocess, "run", side_effect=OSError("missing")):
            self.assertEqual(dash.fetch_memory("nope report"), ({}, ""))
        with self._provider("not json"):
            self.assertEqual(dash.fetch_memory("x"), ({}, ""))
        with self._provider({}, rc=3):
            self.assertEqual(dash.fetch_memory("x"), ({}, ""))
        with self._provider({"sessions": [{"source": "tmux"}]}):  # missing key is ignored, not a crash
            self.assertEqual(dash.fetch_memory("x"), ({}, ""))

    def test_fetch_memory_maps_tmux_windows_and_flags_pressure(self):
        data = {
            "host_line": "host pressure: critical, ~5% free",
            "verdict": {"status": "block"},
            "process_table_ok": True,
            "sessions": [
                {"source": "tmux", "key": "1", "mem": "~2.0 GB"},
                {"source": "unmanaged", "key": "", "mem": "~9.0 GB"},
            ],
        }
        with self._provider(data):
            by_win, line = dash.fetch_memory("mem-guard report --json")
        self.assertEqual(by_win, {"1": "~2.0 GB"})
        self.assertIn("[BLOCK]", line)

    def test_dashboard_does_not_import_the_memory_module(self):
        self.assertFalse(hasattr(dash, "mem_guard"))
        src = Path(dash.__file__).read_text()
        self.assertNotIn("import mem_guard", src)


class TestGroupingAndNavigation(unittest.TestCase):
    def _row(
        self,
        idx: str,
        status: str = "running",
        project: str = "alpha",
        pane_path: str = "/tmp/alpha/wt",
    ) -> dash.WorkstreamRow:
        return dash.WorkstreamRow(
            window_index=idx,
            window_name=f"Is{idx}",
            pane_id=f"%{idx}",
            pane_path=pane_path,
            ticket_ref=f"Is{idx}",
            desc=f"Task {idx}",
            branch="",
            status=status,
            last_line="ok",
            project=project,
        )

    def test_resolve_project_uses_main_root_and_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(dash.repo_facts, "main_root", return_value="/repos/dotfiles"):
                self.assertEqual(dash.resolve_project(tmp), "dotfiles")
            with mock.patch.object(dash.repo_facts, "main_root", return_value=""):
                self.assertEqual(dash.resolve_project(tmp), Path(tmp).name)
        with mock.patch.object(dash.repo_facts, "main_root", return_value=""):
            self.assertEqual(dash.resolve_project("/"), "other")
        with mock.patch.object(dash.os.path, "isdir", return_value=False):
            self.assertEqual(dash.resolve_project("/"), "other")
        self.assertEqual(dash.resolve_project(""), "other")

    def test_row_state_and_next_view_mode(self):
        self.assertEqual(dash.row_state("running"), "running")
        self.assertEqual(dash.row_state("idle (15s)"), "idle")
        self.assertEqual(dash.row_state("exited"), "exited")
        self.assertEqual(dash.next_view_mode("flat"), "project")
        self.assertEqual(dash.next_view_mode("project"), "state")
        self.assertEqual(dash.next_view_mode("state"), "flat")
        self.assertEqual(dash.next_view_mode("unknown"), "flat")

    def test_build_display_items_flat_project_and_state(self):
        rows = [
            self._row("1", status="exited", project="beta"),
            self._row("2", status="running", project="alpha"),
            self._row("3", status="idle (5m)", project="beta"),
        ]
        flat = dash.build_display_items(rows, "flat")
        self.assertEqual([item.row.window_index for item in flat if item.row], ["1", "2", "3"])
        self.assertFalse(any(item.is_header for item in flat))

        by_project = dash.build_display_items(rows, "project")
        self.assertEqual(
            [item.header if item.is_header else item.row.window_index for item in by_project],
            ["── alpha (1)", "2", "── beta (2)", "1", "3"],
        )

        by_state = dash.build_display_items(rows, "state")
        self.assertEqual(
            [item.header if item.is_header else item.row.window_index for item in by_state],
            ["── running (1)", "2", "── idle (1)", "3", "── exited (1)", "1"],
        )

        # Empty state groups are omitted.
        only_running = dash.build_display_items([self._row("1", status="running")], "state")
        self.assertEqual(
            [item.header if item.is_header else item.row.window_index for item in only_running],
            ["── running (1)", "1"],
        )

    def test_step_selection_skips_headers_and_wraps(self):
        rows = [
            self._row("1", status="running", project="alpha"),
            self._row("2", status="exited", project="beta"),
            self._row("3", status="exited", project="beta"),
        ]
        items = dash.build_display_items(rows, "project")
        # items: 0:H(alpha), 1:row1, 2:H(beta), 3:row2, 4:row3
        self.assertEqual(dash.step_selection(items, 1, 1), 3)
        self.assertEqual(dash.step_selection(items, 3, 1), 4)
        self.assertEqual(dash.step_selection(items, 4, 1), 1)
        self.assertEqual(dash.step_selection(items, 1, -1), 4)
        self.assertEqual(dash.step_selection(items, 3, -1), 1)
        self.assertEqual(dash.step_selection(items, 0, 1), 1)

    def test_viewport_scrolling_with_group_headers_keeps_selected_visible(self):
        rows = [
            self._row(str(i + 1), status="running" if i < 4 else "exited", project=f"p{i // 2}")
            for i in range(8)
        ]
        items = dash.build_display_items(rows, "project")
        # 4 project headers + 8 rows = 12 display items; test every selectable index with max_rows=4
        for idx, item in enumerate(items):
            if item.is_header:
                continue
            start, end = dash.visible_slice(len(items), idx, max_rows=4, items=items)
            self.assertLessEqual(start, idx)
            self.assertLess(idx, end)
            self.assertEqual(end - start, 4)

            lines = dash.render_lines(rows, selected=idx, width=100, session="agy-dotfiles", max_rows=4, view_mode="project")
            joined = "\n".join(lines)
            self.assertIn("[project]", lines[0])
            self.assertIn("g: group", lines[-1])
            self.assertIn(f"> {item.row.window_index}", joined)
            self.assertEqual(len(lines), 9)  # 3 header + 4 display items + 2 footer

    def test_curses_loop_cycles_modes_and_skips_headers(self):
        rows = [
            self._row("1", status="exited", project="beta"),
            self._row("2", status="running", project="alpha"),
        ]
        # Start on row 1 (flat idx 0). 'g' -> project mode (items: H(alpha), row2, H(beta), row1; selected=3).
        # 'k' -> skips H(beta), lands on row2 (idx 1). Enter -> switches to window 2.
        keys = [ord("g"), ord("k"), 10]

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
            mock.patch.object(dash, "fetch_windows", return_value=rows),
            mock.patch.object(dash, "_switch_to_window") as switch_mock,
        ):
            with self.assertRaises(StopIteration):
                dash._curses_loop(FakeStdscr(), "agy-dotfiles", None, 2.0)

        switch_mock.assert_called_once_with(["tmux"], "agy-dotfiles", "2")

    def test_fetch_windows_defers_project_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "wt"
            wt.mkdir()
            list_out = f"1\tIs189\t%1\t{wt}\t0\t1000\n"

            def fake_run(cmd: list[str]) -> str:
                if "list-windows" in cmd:
                    return list_out
                if "capture-pane" in cmd:
                    return "ok\n"
                return ""

            with (
                mock.patch.object(dash, "_run_cmd", side_effect=fake_run),
                mock.patch.object(dash, "_git_branch", return_value="main"),
                mock.patch.object(dash, "resolve_project") as proj_mock,
            ):
                rows = dash.fetch_windows("agy-dotfiles", now=1000)

            proj_mock.assert_not_called()
            self.assertEqual(rows[0].project, "")

    def test_curses_loop_lazily_resolves_and_caches_projects(self):
        def make_rows():
            return [
                self._row("1", status="running", project="", pane_path="/tmp/alpha/wt1"),
                self._row("2", status="running", project="", pane_path="/tmp/beta/wt2"),
            ]

        # flat (initial) -> 'r' (still flat, no resolve) -> 'g' (project, resolves 2) -> 'r' (project, cached)
        keys = [ord("r"), ord("g"), ord("r")]

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
            mock.patch.object(dash, "fetch_windows", side_effect=lambda *_a, **_kw: make_rows()),
            mock.patch.object(dash, "resolve_project", side_effect=lambda p: Path(p).parent.name) as proj_mock,
        ):
            with self.assertRaises(StopIteration):
                dash._curses_loop(FakeStdscr(), "agy-dotfiles", None, 2.0)

        self.assertEqual(proj_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
