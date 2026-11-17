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
        self.guard = patch.object(cw, "check_memory").start()
        self.addCleanup(patch.stopall)

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
        self.guard.assert_called_once_with(str(self.root), "session launch")

    def test_blocked_launch_creates_no_thread_or_binding(self):
        self.guard.side_effect = cw.RpcError("blocked by mem-guard")
        with self.assertRaisesRegex(cw.RpcError, "blocked"):
            cw.launch(self.rpc, str(self.root), str(self.kickoff))
        self.rpc.call.assert_not_called()
        self.assertEqual(workstream.load_record(str(self.root)).codex_sessions, [])

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
        self.guard.reset_mock()
        cw.launch(self.rpc, str(self.root), str(self.kickoff))
        self.guard.assert_not_called()

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
    def setUp(self):
        self.guard = patch.object(cw, "check_memory").start()
        self.addCleanup(patch.stopall)

    def test_blocked_group_stops_before_setup(self):
        self.guard.side_effect = cw.RpcError("blocked by mem-guard")
        with patch.object(cw, "prepare") as prepare:
            with self.assertRaisesRegex(cw.RpcError, "blocked"):
                cw.start_groups(Mock(), ["12,13", "15"], "/repo")
            prepare.assert_not_called()
        self.guard.assert_called_once_with("/repo", "ticket 12,13")

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

    def test_pressure_rising_after_setup_reports_worktree_and_stops_next_group(self):
        setup = {"worktree": "/prepared", "kickoff": "/kickoff", "ticket_in_progress": "yes"}
        with patch.object(cw, "prepare", return_value=setup) as prepare, \
                patch.object(cw, "launch", side_effect=cw.RpcError("blocked by mem-guard")):
            with self.assertRaisesRegex(cw.RpcError, "Setup already completed.*prepared.*ticket_in_progress"):
                cw.start_groups(Mock(), ["12", "15"], "/repo")
        prepare.assert_called_once()

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


class MemoryTests(unittest.TestCase):
    def test_real_guard_blocks_before_ticket_setup_and_honors_explicit_override(self):
        with tempfile.TemporaryDirectory() as directory:
            processes = Path(directory) / "processes"
            processes.write_text("")
            environment = {"MEM_GUARD_HOST_FIXTURE": "level=critical free_pct=3",
                           "MEM_GUARD_PS_FIXTURE": str(processes), "MEM_GUARD_ENABLED": "on",
                           "MEM_GUARD_OVERRIDE": ""}
            with patch.dict(cw.os.environ, environment), patch.object(cw, "prepare") as prepare, \
                    patch("sys.stderr"):
                with self.assertRaisesRegex(cw.RpcError, "blocked by mem-guard"):
                    cw.start_groups(Mock(), ["12", "15"], directory)
                prepare.assert_not_called()
                with patch.dict(cw.os.environ, {"MEM_GUARD_OVERRIDE": "1"}):
                    cw.check_memory(directory, "explicit override")

    def test_discussion_block_stops_before_setup(self):
        with patch.object(cw, "Daemon"), patch.object(cw, "prepare") as prepare, \
                patch.object(cw, "check_memory", side_effect=cw.RpcError("blocked")), patch("sys.stderr"):
            self.assertEqual(cw.main(["discuss", "topic", "--dir", "/project"]), 1)
        prepare.assert_not_called()

    def test_guard_runs_in_target_project_and_reports_block(self):
        result = subprocess.CompletedProcess([], 3, "", "BLOCKED: critical pressure\n")
        with patch.object(cw.subprocess, "run", return_value=result) as run, \
                patch("sys.stderr") as stderr:
            with self.assertRaisesRegex(cw.RpcError, "blocked by mem-guard"):
                cw.check_memory("/project", "ticket 12")
        self.assertEqual(run.call_args.args[0], [str(cw.TOOLS / "mem-guard.sh"), "check", "--context", "codex ticket 12"])
        self.assertEqual(run.call_args.kwargs["cwd"], "/project")
        self.assertIn("BLOCKED", "".join(c.args[0] for c in stderr.write.call_args_list))

    def test_missing_crashing_or_timed_out_guard_warns_and_continues(self):
        outcomes = [FileNotFoundError("missing"), subprocess.TimeoutExpired("guard", 20),
                    subprocess.CompletedProcess([], 1, "", "broken\n")]
        for outcome in outcomes:
            with self.subTest(outcome=outcome), patch.object(cw.subprocess, "run") as run, \
                    patch("sys.stderr") as stderr:
                if isinstance(outcome, Exception):
                    run.side_effect = outcome
                else:
                    run.return_value = outcome
                cw.check_memory("/project", "launch")
                self.assertIn("launching without a memory check", "".join(c.args[0] for c in stderr.write.call_args_list))

    def test_warning_allows_launch_and_override_is_scoped_to_guard(self):
        result = subprocess.CompletedProcess([], 0, "", "WARNING: pressure\n")
        with patch.dict(cw.os.environ, {"MEM_GUARD_OVERRIDE": "1"}), \
                patch.object(cw.subprocess, "run", return_value=result) as run, patch("sys.stderr"):
            cw.check_memory("/project", "launch")
            self.assertEqual(run.call_args.kwargs["env"]["MEM_GUARD_OVERRIDE"], "1")
            self.assertNotIn("MEM_GUARD_OVERRIDE", cw.child_environment())


if __name__ == "__main__":
    unittest.main()
