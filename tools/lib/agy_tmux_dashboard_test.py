"""Tests for agy_tmux_dashboard.py.

Run:
    python3 -m unittest tools/lib/agy_tmux_dashboard_test.py
"""

from __future__ import annotations

import curses
import json
import os
import subprocess
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

    def test_compute_status_fallback_without_agy_signals(self):
        self.assertEqual(dash.compute_status(True, 1000, 1001), "exited")
        self.assertEqual(dash.compute_status(False, 1000, 1003), "working")
        self.assertEqual(dash.compute_status(False, 1000, 1045), "idle (45s)")
        self.assertEqual(dash.compute_status(False, None, 1045), "working")
        self.assertEqual(dash.compute_status(False, 1000, 1045, captured="plain shell\n$ "), "idle (45s)")

    def test_stale_or_prose_prompt_text_is_not_waiting(self):
        answered = "Do you want to proceed?\n1. yes\n● Edit file\nfoo | main | [idle]\n"
        self.assertEqual(dash.compute_status(False, 900, 1000, captured=answered), "idle (1m)")
        prose = "I'll explain: use [y/N] flags\n──────────\n>\n──────────\nfoo | main | [idle]\n"
        self.assertEqual(dash.compute_status(False, 900, 1000, captured=prose), "idle (1m)")
        mid_line = "make it so [y/N] ok\n$ "
        self.assertEqual(dash.compute_status(False, 900, 1000, captured=mid_line), "idle (1m)")

    def test_live_prompt_after_activity_marker_is_waiting(self):
        menu = (
            "● Bash(x)\nDo you want to proceed?\n❯ 1. Yes\n2. Yes, and don't ask again\n"
            "3. No\n4. Tell Claude what to do\nEsc to cancel\nfoo | main | [idle]\n"
        )
        self.assertEqual(dash.compute_status(False, 999, 1000, captured=menu), "waiting")
        self.assertEqual(
            dash.compute_status(False, 999, 1000, captured="● Bash\nOverwrite? [y/N]\n"), "waiting"
        )

    def test_compute_status_from_agy_pane_signals(self):
        # pane_dead always wins over captured output
        self.assertEqual(
            dash.compute_status(True, 1000, 1001, captured="dotfiles | main | [tool_use]\n"),
            "exited",
        )

        # working: statusline states
        for tag in ("tool_use", "thinking", "working", "running"):
            cap = f"──────\n> Plan mode:\n──────\ndotfiles | main | [{tag}]\nGemini 4 | 5%\n"
            self.assertEqual(dash.compute_status(False, 900, 1000, captured=cap), "working")

        # working: spinner / interrupt hint without statusline
        self.assertEqual(
            dash.compute_status(False, 900, 1000, captured="⣟  Waiting...\n└ Tip: Use /btw\n"),
            "working",
        )
        self.assertEqual(
            dash.compute_status(False, 900, 1000, captured="Running tests (esc to interrupt)\n"),
            "working",
        )

        # working: active subagent even when main statusline says [idle]
        subagent_cap = (
            "──────\n>\n──────\n"
            "  ● Agent(local-review-cycle-manager: Local Review Cycle Manager) · 14s\n"
            "──────\n"
            "dotfiles | Is180 | [idle]\n"
            "Gemini 4 | 14% | tasks: 1\n"
        )
        self.assertEqual(dash.compute_status(False, 900, 1000, captured=subagent_cap), "working")

        # waiting: permission / approval / question prompts override [tool_use] or [idle]
        perm_cap = (
            "Run command: rm -rf build?\n"
            "❯ 1. Allow once\n"
            "  2. Deny\n"
            "Enter to select · Esc to cancel\n"
            "dotfiles | main | [tool_use]\n"
        )
        self.assertEqual(dash.compute_status(False, 999, 1000, captured=perm_cap), "waiting")

        question_cap = (
            "Which approach?\n"
            "❯ 1. Option A (Recommended)\n"
            "  2. Option B\n"
            "dotfiles | main | [idle]\n"
        )
        self.assertEqual(dash.compute_status(False, 999, 1000, captured=question_cap), "waiting")

        self.assertEqual(
            dash.compute_status(False, 999, 1000, captured="Continue? [y/N]\n"),
            "waiting",
        )
        self.assertEqual(
            dash.compute_status(False, 999, 1000, captured="dotfiles | main | [waiting]\n"),
            "waiting",
        )

        # idle: statusline [idle] or bare prompt box, even when last_activity is very recent
        idle_cap = "──────\n>\n──────\ndotfiles | main | [idle]\nGemini 4 | 15%\n"
        self.assertEqual(dash.compute_status(False, 998, 1000, captured=idle_cap), "idle (2s)")
        self.assertEqual(dash.compute_status(False, None, 1000, captured=idle_cap), "idle")

        bare_prompt = "Some response\n────────────\n>\n────────────\n"
        self.assertEqual(dash.compute_status(False, 998, 1000, captured=bare_prompt), "idle (2s)")

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
                        "tags": ["WIP", "PR"],
                    }
                ),
                encoding="utf-8",
            )
            ref, desc, tags = dash.load_workstream_meta(tmp)
            self.assertEqual(ref, "Is12+13")
            self.assertEqual(desc, "Add OAuth flow")
            self.assertEqual(tags, "[WIP][PR]")

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
            ref, desc, tags = dash.load_workstream_meta(tmp)
            self.assertEqual(ref, "sc-12+13")
            self.assertEqual(desc, "")
            self.assertEqual(tags, "")

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
                tags="[WIP][PR]",
            )
        ]
        lines = dash.render_lines(rows, selected=0, width=120, session="agy-dotfiles")
        joined = "\n".join(lines)
        self.assertIn("agy-dotfiles", joined)
        self.assertIn("Tags", joined)
        self.assertIn("[WIP][PR]", joined)
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
                        "tags": ["PLAN"],
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
            self.assertEqual(rows[0].tags, "[PLAN]")
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

    def test_fetch_windows_ignores_pane_output_without_workstream_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "wt"
            wt.mkdir()
            list_out = f"1\tshell\t%1\t{wt}\t0\t998\n"
            box_prompt = "─" * 20 + "\n> \n" + "─" * 20 + "\n"

            def fake_run(cmd: list[str]) -> str:
                if "list-windows" in cmd:
                    return list_out
                if "capture-pane" in cmd:
                    return box_prompt
                return ""

            with (
                mock.patch.object(dash, "_run_cmd", side_effect=fake_run),
                mock.patch.object(dash, "_git_branch", return_value="main"),
            ):
                rows = dash.fetch_windows("agy-dotfiles", now=1000)

            self.assertEqual(rows[0].status, "working")

    def test_has_workstream_record_ignores_legacy_chain_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "wt"
            wt.mkdir()
            legacy = dash.workstream.WorkstreamRecord.from_dict({"tickets": ["Is1"]})
            with mock.patch.object(dash.workstream, "load_record", return_value=legacy):
                self.assertFalse(dash._has_workstream_record(str(wt)))
            (wt / dash.workstream.RECORD_FILENAME).write_text("{}", encoding="utf-8")
            self.assertTrue(dash._has_workstream_record(str(wt)))

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
        self.assertEqual(dash.row_state("waiting"), "waiting")
        self.assertEqual(dash.row_state("working"), "working")
        self.assertEqual(dash.row_state("idle (15s)"), "idle")
        self.assertEqual(dash.row_state("idle"), "idle")
        self.assertEqual(dash.row_state("exited"), "exited")
        self.assertEqual(dash.next_view_mode("flat"), "project")
        self.assertEqual(dash.next_view_mode("project"), "state")
        self.assertEqual(dash.next_view_mode("state"), "flat")
        self.assertEqual(dash.next_view_mode("unknown"), "flat")

    def test_build_display_items_flat_project_and_state(self):
        rows = [
            self._row("1", status="exited", project="beta"),
            self._row("2", status="working", project="alpha"),
            self._row("3", status="idle (5m)", project="beta"),
            self._row("4", status="waiting", project="alpha"),
        ]
        flat = dash.build_display_items(rows, "flat")
        self.assertEqual([item.row.window_index for item in flat if item.row], ["1", "2", "3", "4"])
        self.assertFalse(any(item.is_header for item in flat))

        by_project = dash.build_display_items(rows, "project")
        self.assertEqual(
            [item.header if item.is_header else item.row.window_index for item in by_project],
            ["── alpha (2)", "2", "4", "── beta (2)", "1", "3"],
        )

        by_state = dash.build_display_items(rows, "state")
        self.assertEqual(
            [item.header if item.is_header else item.row.window_index for item in by_state],
            ["── waiting (1)", "4", "── working (1)", "2", "── idle (1)", "3", "── exited (1)", "1"],
        )

        # Empty state groups are omitted.
        only_working = dash.build_display_items([self._row("1", status="working")], "state")
        self.assertEqual(
            [item.header if item.is_header else item.row.window_index for item in only_working],
            ["── working (1)", "1"],
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


class TestProjectColors(unittest.TestCase):
    def test_resolve_color_reads_workstreams_settings_over_legacy_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "My-Project"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / ".workstreams").mkdir()
            (repo / ".workstreams" / "settings.json").write_text('{"color": "Orange"}', encoding="utf-8")
            (repo / ".start-ticket.conf").write_text("color=cyan\n", encoding="utf-8")
            colors_file = Path(tmp) / "project-colors"
            colors_file.write_text("My-Project purple\n", encoding="utf-8")
            home = Path(tmp) / "home"
            home.mkdir()
            with mock.patch.dict(os.environ, {"HOME": str(home)}):
                self.assertEqual(dash.resolve_project_color(str(repo), colors_file=colors_file), "orange")
                (repo / ".workstreams" / "settings.json").unlink()
                self.assertEqual(dash.resolve_project_color(str(repo), colors_file=colors_file), "cyan")

    def test_resolve_color_conf_override_beats_project_colors(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "My-Project" / "wt1"
            wt.mkdir(parents=True)
            colors_file = Path(tmp) / "project-colors"
            colors_file.write_text("# comment\nMy-Project purple\n", encoding="utf-8")

            with (
                mock.patch.object(dash.repo_facts, "conf_get", return_value="  Cyan \r"),
                mock.patch.object(dash.repo_facts, "main_root", return_value=str(Path(tmp) / "My-Project")),
            ):
                self.assertEqual(dash.resolve_project_color(str(wt), colors_file=colors_file), "cyan")

    def test_resolve_color_falls_back_to_project_colors_when_conf_unset_or_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "My-Project" / "wt1"
            wt.mkdir(parents=True)
            colors_file = Path(tmp) / "project-colors"
            colors_file.write_text(
                "# header\n\ndotfiles green\nmy-project Purple\n",
                encoding="utf-8",
            )

            for conf_val in (None, "   "):
                with (
                    mock.patch.object(dash.repo_facts, "conf_get", return_value=conf_val),
                    mock.patch.object(dash.repo_facts, "main_root", return_value=str(Path(tmp) / "My-Project")),
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

    def test_fetch_windows_caches_project_color_across_refreshes(self):
        dash._COLOR_CACHE.clear()
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "wt"
            wt.mkdir()
            list_out = f"1\tIs187\t%1\t{wt}\t0\t1000\n"

            def fake_run(cmd: list[str]) -> str:
                if "list-windows" in cmd:
                    return list_out
                if "capture-pane" in cmd:
                    return "ok\n"
                return ""

            with (
                mock.patch.object(dash, "_run_cmd", side_effect=fake_run),
                mock.patch.object(dash, "_git_branch", return_value="Is187-test"),
                mock.patch.object(dash, "resolve_project_color", return_value="cyan") as color_mock,
            ):
                rows1 = dash.fetch_windows("agy-dotfiles", now=1000)
                rows2 = dash.fetch_windows("agy-dotfiles", now=1002)
                dash._COLOR_CACHE.clear()
                rows3 = dash.fetch_windows("agy-dotfiles", now=1004)

            self.assertEqual(color_mock.call_count, 2)
            self.assertEqual([r.color for r in (rows1[0], rows2[0], rows3[0])], ["cyan", "cyan", "cyan"])

    def test_curses_loop_clears_color_cache_only_on_manual_refresh(self):
        dash._COLOR_CACHE.clear()
        dash._COLOR_CACHE[("/tmp/wt", "")] = "green"
        keys = [-1, ord("r")]
        cache_sizes_at_fetch: list[int] = []

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

        def fake_fetch(*_args, **_kwargs):
            cache_sizes_at_fetch.append(len(dash._COLOR_CACHE))
            return []

        with (
            mock.patch.object(curses, "curs_set"),
            mock.patch.object(curses, "has_colors", return_value=False),
            mock.patch.object(dash, "fetch_windows", side_effect=fake_fetch),
        ):
            with self.assertRaises(StopIteration):
                dash._curses_loop(FakeStdscr(), "agy-dotfiles", None, 2.0)

        # Initial fetch + timeout (-1) preserve cache; manual 'r' clears it before fetch.
        self.assertEqual(cache_sizes_at_fetch, [1, 1, 0])


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

    def test_init_color_pairs_keeps_valid_pairs_when_pair_limit_reached(self):
        def fake_init_pair(idx, _fg, _bg):
            if idx >= 8:
                raise curses.error("pair limit")

        with (
            mock.patch.object(curses, "has_colors", return_value=True),
            mock.patch.object(curses, "start_color"),
            mock.patch.object(curses, "use_default_colors"),
            mock.patch.object(curses, "init_pair", side_effect=fake_init_pair),
            mock.patch.object(curses, "COLORS", 8, create=True),
        ):
            pairs = dash.init_color_pairs()

        self.assertEqual(set(pairs.keys()), set(dash.PALETTE[:7]))

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
            status="working",
            last_line="ok",
            color="green",
        )
        line = dash.render_lines([row], selected=0, width=100, session="agy-dotfiles")[3]

        with mock.patch.object(curses, "color_pair", return_value=0x200) as cp_mock:
            dash._draw_row(FakeStdscr(), 3, line, 100, row, is_selected=True, color_pairs={"green": 3})

        self.assertEqual(cp_mock.call_count, 2)
        self.assertEqual(calls[0][1], 0)
        self.assertEqual(calls[0][4], curses.A_REVERSE)
        # Status (x=34), Ticket (x=6), and Title (x=57) get color_pair | A_REVERSE
        self.assertEqual(
            [(c[1], c[4]) for c in calls[1:]],
            [(34, curses.A_REVERSE | 0x200), (6, curses.A_REVERSE | 0x200), (57, curses.A_REVERSE | 0x200)],
        )
        self.assertEqual(calls[3][2].strip(), "Port project colors")

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
            status="working",
            last_line="ok",
            color="green",
        )
        line = dash.render_lines([row], selected=0, width=100, session="agy-dotfiles")[3]

        with mock.patch.object(curses, "color_pair") as cp_mock:
            dash._draw_row(FakeStdscr(), 3, line, 100, row, is_selected=False, color_pairs={})

        cp_mock.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][4], curses.A_NORMAL)

    def test_status_attr_styles_each_attention_state(self):
        pairs = {"yellow": 4, "green": 3, "red": 1}
        with mock.patch.object(curses, "color_pair", side_effect=lambda p: p * 0x100):
            self.assertEqual(dash._status_attr("waiting", 0, pairs), curses.A_BOLD | 0x400)
            self.assertEqual(dash._status_attr("working", 0, pairs), 0x300)
            self.assertEqual(dash._status_attr("idle (5s)", 0, pairs), curses.A_DIM)
            self.assertEqual(dash._status_attr("exited", 0, pairs), 0x100)


if __name__ == "__main__":
    unittest.main()
