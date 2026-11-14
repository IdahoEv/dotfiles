"""Tests for agy_tmux_dashboard.py.

Run:
    python3 -m unittest tools/lib/agy_tmux_dashboard_test.py
"""

from __future__ import annotations

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

    def test_fetch_windows_skips_dashboard_window_zero(self):
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

            with mock.patch.object(dash, "_run_cmd", side_effect=fake_run):
                rows = dash.fetch_windows("agy-dotfiles", now=1000)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].window_index, "1")
            self.assertEqual(rows[0].ticket_ref, "Is183")
            self.assertEqual(rows[0].status, "idle (50s)")
            self.assertEqual(rows[0].last_line, "Ready for review?")


if __name__ == "__main__":
    unittest.main()
