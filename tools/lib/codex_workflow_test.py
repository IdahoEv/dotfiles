"""Local Codex workstream launch and recovery contracts."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import codex_workflow as cw
import workstream


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.kickoff = self.root / "kickoff.md"
        self.kickoff.write_text("Plan the ordered chain.")
        self.rec = workstream.init_ticket_record(
            str(self.root), "github", [{"id": n, "url": ""} for n in ["12", "13", "14"]],
            title="Ordered work",
        )
        self.rpc = Mock()
        self.rpc.call.side_effect = self.respond

    def respond(self, method, params):
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}, "model": "configured-model", "reasoningEffort": "high"}
        if method == "thread/read":
            return {"thread": {"id": "thread-1", "cwd": str(self.root), "status": {"type": "idle"}}}
        return {}

    def test_launch_records_thread_and_order_before_submitting_plan(self):
        def respond(method, params):
            if method == "turn/start":
                saved = workstream.load_record(str(self.root))
                self.assertEqual(saved.codex_sessions, ["thread-1"])
                self.assertEqual([t["id"] for t in saved.tickets], ["12", "13", "14"])
                self.assertEqual(params["collaborationMode"]["mode"], "plan")
                self.assertEqual(params["collaborationMode"]["settings"]["model"], "configured-model")
                self.assertIn("codex-local.md", params["input"][0]["text"])
                self.assertIn("Plan the ordered chain.", params["input"][0]["text"])
            return self.respond(method, params)
        self.rpc.call.side_effect = respond
        result = cw.launch(self.rpc, str(self.root), str(self.kickoff))
        self.assertEqual(result["thread_id"], "thread-1")
        self.assertFalse(result["reused"])

    def test_failed_submission_keeps_recoverable_binding_without_duplicate_launch(self):
        def respond(method, params):
            if method == "turn/start":
                raise cw.RpcError("unavailable method")
            return self.respond(method, params)
        self.rpc.call.side_effect = respond
        with self.assertRaisesRegex(cw.RpcError, "thread-1"):
            cw.launch(self.rpc, str(self.root), str(self.kickoff))
        self.rpc.reset_mock()
        self.rpc.call.side_effect = self.respond
        result = cw.launch(self.rpc, str(self.root), str(self.kickoff))
        self.assertTrue(result["reused"])
        self.assertEqual([c.args[0] for c in self.rpc.call.call_args_list], ["thread/read"])

    def test_wrong_cwd_binding_fails_before_input(self):
        self.rec.codex_sessions = ["thread-1"]
        workstream.save_record(str(self.root), self.rec)
        self.rpc.call.return_value = {"thread": {"cwd": "/other"}}
        self.rpc.call.side_effect = None
        with self.assertRaisesRegex(cw.RpcError, "directory"):
            cw.launch(self.rpc, str(self.root), str(self.kickoff))

    def test_invalid_kickoff_does_not_create_thread(self):
        with self.assertRaises(FileNotFoundError):
            cw.launch(self.rpc, str(self.root), str(self.root / "missing"))
        self.rpc.call.assert_not_called()

    def test_rerunning_start_preserves_codex_binding(self):
        self.rec.codex_sessions = ["thread-1"]
        workstream.save_record(str(self.root), self.rec)
        rec = workstream.init_ticket_record(str(self.root), "github", [{"id": "12", "url": ""}])
        self.assertEqual(rec.codex_sessions, ["thread-1"])
        self.assertEqual([t["id"] for t in rec.tickets], ["12", "13", "14"])

    def test_title_override_changes_session_name_without_changing_record_name(self):
        with patch.dict(cw.os.environ, {"GT_LABEL_OVERRIDE": "Invoice Totals"}):
            result = cw.launch(self.rpc, str(self.root), str(self.kickoff))
        self.assertIn("invoice totals", result["name"])
        self.assertEqual(workstream.load_record(str(self.root)).desc, self.rec.desc)


class GroupTests(unittest.TestCase):
    def test_groups_are_independent_and_chains_stay_ordered(self):
        self.assertEqual(cw.parse_groups(["12,13,14", "15"]), ["12,13,14", "15"])

    def test_invalid_or_overlapping_groups_fail_before_any_setup(self):
        for groups in [["12,,13"], ["12,12"], ["12,13", "13"], ["--launcher"], []]:
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                cw.parse_groups(groups)

    def test_setup_failure_stops_before_launch_and_next_group(self):
        with patch.object(cw, "prepare", side_effect=cw.RpcError("setup failed")) as prepare:
            with self.assertRaisesRegex(cw.RpcError, "setup failed"):
                cw.start_groups(Mock(), ["12,13", "15"], "/repo")
            self.assertEqual(prepare.call_count, 1)

    def test_setup_uses_existing_script_and_never_launches_claude(self):
        completed = subprocess.CompletedProcess([], 0, "worktree=/w\nkickoff=/k\nbranch=Is12\n", "")
        with patch.object(cw.subprocess, "run", return_value=completed) as run:
            self.assertEqual(cw.prepare(["12,13", "--no-tab"], "/repo")["worktree"], "/w")
            self.assertEqual(run.call_args.args[0][-2:], ["12,13", "--no-tab"])
            self.assertEqual(run.call_args.kwargs["cwd"], "/repo")

    def test_two_groups_each_prepare_then_launch_with_their_own_kickoff(self):
        setups = [{"worktree": "/a", "kickoff": "/ka"}, {"worktree": "/b", "kickoff": "/kb"}]
        with patch.object(cw, "prepare", side_effect=setups) as prepare, \
                patch.object(cw, "launch", return_value={}) as launch, patch("builtins.print"):
            rpc = Mock()
            cw.start_groups(rpc, ["12,13,14", "15"], "/repo")
            self.assertEqual([c.args[0] for c in prepare.call_args_list], [["12,13,14", "--no-tab"], ["15", "--no-tab"]])
            self.assertEqual([c.args[1:] for c in launch.call_args_list], [("/a", "/ka"), ("/b", "/kb")])


class StatusTests(unittest.TestCase):
    def test_status_paginates_without_provider_filter(self):
        rpc = Mock()
        rpc.call.side_effect = [
            {"data": [{"id": "one"}], "nextCursor": "next"},
            {"data": [{"id": "two"}], "nextCursor": None},
        ]
        self.assertEqual([t["id"] for t in cw.list_threads(rpc)], ["one", "two"])
        self.assertEqual(rpc.call.call_args.args[1]["cursor"], "next")
        self.assertEqual(rpc.call.call_args.args[1]["modelProviders"], [])


if __name__ == "__main__":
    unittest.main()
