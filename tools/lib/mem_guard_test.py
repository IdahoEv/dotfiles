"""Tests for mem_guard.py.

Run:
    python3 -m unittest tools/lib/mem_guard_test.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import mem_guard as mg  # noqa: E402

PS = """\
  1     0   1000 /sbin/launchd
 100    1   5000 /usr/bin/login
 200  100  20000 -zsh
 300  200 300000 /Users/e/.local/bin/claude
 301  300 100000 /usr/local/bin/node
 302  301  50000 /usr/bin/python3
 303  300 200000 /Users/e/.local/bin/claude
 400    1  80000 /opt/homebrew/bin/agy
 401  400  40000 /bin/bash
 500    1 900000 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
 600    1  10000 /usr/local/bin/codex
"""
NAMES = mg.DEFAULT_AGENT_NAMES


class TestParse(unittest.TestCase):
    def test_parses_and_keeps_spaces_in_comm(self):
        procs = mg.parse_ps(PS)
        self.assertEqual(procs[300].rss_kb, 300000)
        self.assertEqual(procs[500].name, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    def test_skips_malformed_lines(self):
        procs = mg.parse_ps("garbage\n 1 x 3 foo\n 2 1 7 bar\n\n")
        self.assertEqual(list(procs), [2])

    def test_argv_never_requested(self):
        self.assertNotIn("args", " ".join(mg.PS_CMD))
        self.assertIn("comm=", mg.PS_CMD[-1])


class TestAgentDetection(unittest.TestCase):
    def test_basename_and_installer_dir(self):
        p = lambda n: mg.Proc(1, 0, 0, n)  # noqa: E731
        self.assertTrue(mg.is_agent(p("/usr/local/bin/codex"), NAMES))
        self.assertTrue(mg.is_agent(p("/Users/e/.local/share/claude/versions/2.1.0"), NAMES))
        self.assertFalse(mg.is_agent(p("/usr/local/bin/node"), NAMES))

    def test_directories_named_like_agents_do_not_match(self):
        p = lambda n: mg.Proc(1, 0, 0, n)  # noqa: E731
        self.assertFalse(mg.is_agent(p("/Users/claude/bin/vim"), NAMES))
        self.assertFalse(mg.is_agent(p("/Users/e/Development/codex/node_modules/.bin/vite"), NAMES))
        self.assertFalse(mg.is_agent(p("/Users/e/Development/agy/build/server"), NAMES))
        self.assertFalse(mg.is_agent(p("/Users/e/share/claude/other/2.1.0"), NAMES))  # not a versions/ layout

    def test_desktop_app_bundles_are_not_agent_sessions(self):
        p = lambda n: mg.Proc(1, 0, 0, n)  # noqa: E731
        self.assertFalse(mg.is_agent(p("/Applications/Claude.app/Contents/MacOS/Claude"), NAMES))
        self.assertFalse(mg.is_agent(p("/Applications/Claude.app/Contents/Frameworks/Helper (GPU).app/Contents/MacOS/claude"), NAMES))
        self.assertEqual(mg.backend_of(["/Applications/Claude.app/Contents/MacOS/Claude"], NAMES), "-")

    def test_backend_names(self):
        self.assertEqual(mg.backend_of(["/bin/bash", "/Users/e/.local/share/claude/versions/2.1.0"], NAMES), "claude")


class TestAttribution(unittest.TestCase):
    def setUp(self):
        self.procs = mg.parse_ps(PS)

    def test_nested_agent_is_one_root_and_not_double_counted(self):
        roots = mg.discover_agent_roots(self.procs, set(), NAMES)
        self.assertEqual(roots, [300, 400, 600])  # 303 is a claude under claude 300
        sessions = mg.attribute(self.procs, [mg.Root(p, str(p), "unmanaged") for p in roots], NAMES)
        by = {s.root_pid: s for s in sessions}
        self.assertEqual(by[300].rss_kb, 300000 + 100000 + 50000 + 200000)
        self.assertEqual(by[300].pids, [300, 301, 302, 303])
        self.assertEqual(by[400].rss_kb, 120000)
        self.assertEqual(by[300].backend, "claude")
        # every pid lands in at most one session
        all_pids = [pid for s in sessions for pid in s.pids]
        self.assertEqual(len(all_pids), len(set(all_pids)))
        # unrelated processes (chrome, login, zsh) are not attributed
        self.assertNotIn(500, all_pids)
        self.assertNotIn(200, all_pids)

    def test_managed_root_claims_nested_unmanaged_agent(self):
        known = [mg.Root(200, "ws", "tmux", "1")]  # shell pane that launched claude
        self.assertEqual(mg.discover_agent_roots(self.procs, {200}, NAMES), [400, 600])
        s = mg.attribute(self.procs, known, NAMES)[0]
        self.assertEqual(s.pids, [200, 300, 301, 302, 303])

    def test_nested_roots_nearest_wins(self):
        roots = [mg.Root(300, "outer", "tmux"), mg.Root(301, "inner", "tmux")]
        by = {s.label: s for s in mg.attribute(self.procs, roots, NAMES)}
        self.assertEqual(by["inner"].pids, [301, 302])
        self.assertEqual(by["outer"].pids, [300, 303])
        self.assertEqual(sum(s.rss_kb for s in by.values()), 650000)

    def test_exited_root_reports_gone_not_zero(self):
        s = mg.attribute(self.procs, [mg.Root(9999, "dead", "tmux")], NAMES)[0]
        self.assertEqual((s.state, s.rss_kb, s.procs), ("gone", None, 0))
        self.assertEqual(mg.fmt_mb(s.mb), "-")

    def test_parent_cycle_does_not_hang(self):
        procs = {1: mg.Proc(1, 2, 10, "claude"), 2: mg.Proc(2, 1, 10, "bash")}
        roots = mg.discover_agent_roots(procs, set(), NAMES)
        self.assertEqual(roots, [1])
        self.assertEqual(mg.attribute(procs, [mg.Root(1, "c", "unmanaged")], NAMES)[0].procs, 2)

    def test_sample_failure_degrades(self):
        self.assertIsNone(mg.sample_processes(lambda cmd: None))
        sessions, ok = mg.collect(mg.Config(), runner=lambda cmd: None)
        self.assertEqual((sessions, ok), ([], False))


class TestRoots(unittest.TestCase):
    def test_tmux_roots_skip_dashboard_and_keep_dead_panes(self):
        out = "0 10 0 dashboard\n1 300 0 Is5 thing\n2  1 Is6 old\n"
        roots = mg.tmux_roots("s", runner=lambda cmd: out)
        self.assertEqual([(r.key, r.pid, r.label) for r in roots], [("1", 300, "Is5 thing"), ("2", -2, "Is6 old")])
        sessions = mg.attribute(mg.parse_ps(PS), roots, NAMES)
        self.assertEqual(sessions[1].state, "gone")

    def test_tmux_unavailable_gives_no_roots(self):
        self.assertEqual(mg.tmux_roots("s", runner=lambda cmd: None), [])

    def test_untracked_agent_matched_to_workstream_by_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            wt = Path(d) / "wt" / "sub"
            wt.mkdir(parents=True)
            (Path(d) / "wt" / ".workstream.json").write_text(
                json.dumps({"version": 1, "key": "Is191", "tickets": [{"id": "191", "url": ""}]})
            )

            def runner(cmd):
                return f"p300\nn{wt}\np400\nn{d}\n" if cmd[0] == "lsof" else None

            roots = mg.build_roots_for_untracked(mg.parse_ps(PS), [], NAMES, runner)
        by = {r.pid: r for r in roots}
        self.assertEqual((by[300].label, by[300].source), ("Is191 (claude)", "worktree"))
        self.assertEqual(by[400].source, "unmanaged")
        self.assertIn("pid 400", by[400].label)

    def test_workstream_found_arbitrarily_deep_below_root(self):
        with tempfile.TemporaryDirectory() as d:
            deep = Path(d, *[f"d{i}" for i in range(15)])
            deep.mkdir(parents=True)
            (Path(d) / ".workstream.json").write_text(json.dumps({"version": 1, "key": "Is9"}))
            self.assertEqual(mg.workstream_label(str(deep)), "Is9")
            self.assertEqual(mg.workstream_label("/"), "")  # terminates at the filesystem root

    def test_lsof_partial_output_survives_an_exited_pid(self):
        # lsof exits 1 when any listed pid is gone but still prints the rest; run_lenient keeps it.
        import subprocess as sp
        with mock.patch.object(mg.subprocess, "run", return_value=sp.CompletedProcess([], 1, "p300\nn/w\n", "")):
            self.assertEqual(mg.run_lenient(["lsof"]), "p300\nn/w\n")
            self.assertIsNone(mg.run(["lsof"]))  # strict runner still treats non-zero as failure
        self.assertEqual(mg.resolve_cwds([300, 99999], lambda c: "p300\nn/w\n"), {300: "/w"})

    def test_lsof_missing_falls_back_to_unmanaged(self):
        roots = mg.build_roots_for_untracked(mg.parse_ps(PS), [], NAMES, lambda cmd: None)
        self.assertTrue(all(r.source == "unmanaged" for r in roots))


class TestHost(unittest.TestCase):
    def test_darwin_levels_and_free_pct(self):
        def runner(cmd):
            if cmd[0] == "sysctl":
                return "4\n"
            return "The system has 17179869184 (1048576 pages)\nSystem-wide memory free percentage: 7%\n"

        h = mg.read_host(runner, platform="darwin")
        self.assertEqual((h.level, h.free_pct), ("critical", 7.0))

    def test_darwin_sysctl_failure_is_unknown(self):
        h = mg.read_host(lambda cmd: None, platform="darwin")
        self.assertEqual((h.level, h.free_pct), ("unknown", None))

    def test_unsupported_platform(self):
        self.assertEqual(mg.read_host(lambda c: None, platform="win32").level, "unknown")

    def test_fixture_hook(self):
        with mock.patch.dict(os.environ, {"MEM_GUARD_HOST_FIXTURE": "level=warn free_pct=15"}):
            h = mg.read_host()
        self.assertEqual((h.level, h.free_pct), ("warn", 15.0))


class TestEvaluate(unittest.TestCase):
    cfg = mg.Config()

    def host(self, level="normal", free=None):
        return mg.Host(level, free, "t")

    def test_ok(self):
        self.assertEqual(mg.evaluate(self.host("normal", 60), [], self.cfg).status, "ok")

    def test_thresholds_boundaries(self):
        ev = lambda f: mg.evaluate(self.host("normal", f), [], self.cfg).status  # noqa: E731
        self.assertEqual(ev(20), "ok")      # not below warn
        self.assertEqual(ev(19.9), "warn")
        self.assertEqual(ev(8.1), "warn")
        self.assertEqual(ev(8), "block")    # at the block threshold
        self.assertEqual(ev(0), "block")

    def test_os_level_drives_status_even_with_plenty_free(self):
        self.assertEqual(mg.evaluate(self.host("warn", 70), [], self.cfg).status, "warn")
        self.assertEqual(mg.evaluate(self.host("critical", 70), [], self.cfg).status, "block")

    def test_session_estimates_only_warn_never_block(self):
        big = mg.SessionMem("big", "tmux", 1, "1", "claude", 3, 64 * 1024 * 1024, "live", [1])
        v = mg.evaluate(self.host("normal", 60), [big], self.cfg)
        self.assertEqual(v.status, "warn")
        self.assertIn("big", v.reasons[0])

    def test_agents_total_threshold(self):
        cfg = mg.Config(agents_warn_mb=1000, session_warn_mb=0)
        ss = [mg.SessionMem(str(i), "tmux", i, "", "-", 1, 600 * 1024, "live", [i]) for i in (1, 2)]
        self.assertEqual(mg.evaluate(self.host("normal", 60), ss, cfg).status, "warn")

    def test_gone_sessions_ignored(self):
        gone = mg.SessionMem("x", "tmux", -1, "", "-", 0, None, "gone", [])
        self.assertEqual(mg.evaluate(self.host("normal", 60), [gone], self.cfg).status, "ok")

    def test_unreadable_os_level_with_free_pct_is_not_silently_ok(self):
        # macOS sysctl failed but memory_pressure gave a healthy free %: fail-closed must still see it.
        v = mg.evaluate(self.host("unknown", 70), [], self.cfg)
        self.assertEqual(v.status, "unknown")
        self.assertIn("unreadable", v.reasons[0])
        # free % can still raise the status above "unknown"
        self.assertEqual(mg.evaluate(self.host("unknown", 5), [], self.cfg).status, "block")

    def test_linux_has_no_os_level_by_design_and_stays_ok(self):
        self.assertEqual(mg.evaluate(self.host("n/a", 70), [], self.cfg).status, "ok")

    def test_unreadable_host_is_unknown(self):
        v = mg.evaluate(mg.Host("unknown", None, "sysctl"), [], self.cfg)
        self.assertEqual(v.status, "unknown")


class TestConfig(unittest.TestCase):
    def test_env_overrides_and_invalid_falls_back(self):
        env = {"MEM_GUARD_WARN_FREE_PCT": "30", "MEM_GUARD_BLOCK_FREE_PCT": "oops", "MEM_GUARD_FAIL": "closed",
               "MEM_GUARD_ENABLED": "off"}
        with mock.patch.dict(os.environ, env):
            cfg = mg.load_config("/nonexistent")
        self.assertEqual(cfg.warn_free_pct, 30.0)
        self.assertEqual(cfg.block_free_pct, 8.0)
        self.assertTrue(cfg.fail_closed)
        self.assertFalse(cfg.guard)
        self.assertTrue(any("mem_block_free_pct" in n for n in cfg.notes))

    def test_non_finite_thresholds_are_ignored_not_crashes(self):
        for bad in ("nan", "inf", "-inf", "-1"):
            with mock.patch.dict(os.environ, {"MEM_GUARD_SESSION_WARN_MB": bad, "MEM_GUARD_WARN_FREE_PCT": bad}):
                cfg = mg.load_config("/nonexistent")
            self.assertEqual(cfg.session_warn_mb, 4096, bad)
            self.assertEqual(cfg.warn_free_pct, 20.0, bad)
            self.assertTrue(cfg.notes, bad)

    def test_block_above_warn_is_normalised(self):
        with mock.patch.dict(os.environ, {"MEM_GUARD_BLOCK_FREE_PCT": "40"}):
            cfg = mg.load_config("/nonexistent")
        self.assertEqual(cfg.warn_free_pct, 40.0)


class TestFormatting(unittest.TestCase):
    def test_fmt_mb_rounds_and_prefixes(self):
        self.assertEqual(mg.fmt_mb(None), "-")
        self.assertEqual(mg.fmt_mb(347.4), "~350 MB")
        self.assertEqual(mg.fmt_mb(1536), "~1.5 GB")

    def test_report_marks_unmanaged_and_notes_estimate(self):
        procs = mg.parse_ps(PS)
        roots = mg.build_roots_for_untracked(procs, [], NAMES, lambda c: None)
        text = mg.render_report(mg.attribute(procs, roots, NAMES), mg.Host("normal", 50.0, "t"))
        self.assertIn("host pressure: normal, ~50% free", text)
        self.assertIn("started outside the launcher", text)
        self.assertIn("over-count", text)


class TestCheckCli(unittest.TestCase):
    def run_check(self, host_fixture, *args, env=None):
        envv = {"MEM_GUARD_HOST_FIXTURE": host_fixture, "MEM_GUARD_PS_FIXTURE": "/nonexistent-ps"}
        envv.update(env or {})
        err = io.StringIO()
        with mock.patch.dict(os.environ, envv), redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = mg.main(["check", *args])
        return rc, err.getvalue()

    def test_ok_is_silent(self):
        rc, err = self.run_check("level=normal free_pct=70")
        self.assertEqual((rc, err), (0, ""))

    def test_warn_goes(self):
        rc, err = self.run_check("level=warn free_pct=15")
        self.assertEqual(rc, 0)
        self.assertIn("WARNING", err)

    def test_block_then_override(self):
        rc, err = self.run_check("level=critical free_pct=5", "--context", "agy-tmux")
        self.assertEqual(rc, mg.EXIT_BLOCKED)
        self.assertIn("BLOCKED (agy-tmux)", err)
        self.assertIn("no session was killed", err)
        rc, err = self.run_check("level=critical free_pct=5", "--force")
        self.assertEqual(rc, 0)
        self.assertIn("OVERRIDE", err)
        rc, _ = self.run_check("level=critical free_pct=5", env={"MEM_GUARD_OVERRIDE": "1"})
        self.assertEqual(rc, 0)

    def test_override_zero_is_not_an_override(self):
        rc, _ = self.run_check("level=critical", env={"MEM_GUARD_OVERRIDE": "0"})
        self.assertEqual(rc, mg.EXIT_BLOCKED)

    def test_guard_off(self):
        rc, err = self.run_check("level=critical free_pct=1", env={"MEM_GUARD_ENABLED": "off"})
        self.assertEqual((rc, err), (0, ""))

    def test_fail_closed_applies_when_only_the_os_level_is_missing(self):
        rc, _ = self.run_check("level=unknown free_pct=70", env={"MEM_GUARD_FAIL": "closed"})
        self.assertEqual(rc, mg.EXIT_BLOCKED)
        rc, _ = self.run_check("level=unknown free_pct=70")
        self.assertEqual(rc, 0)

    def test_unreadable_pressure_fail_open_and_closed(self):
        rc, err = self.run_check("level=unknown")
        self.assertEqual(rc, 0)
        self.assertIn("cannot read memory pressure; not blocking", err)
        rc, err = self.run_check("level=unknown", env={"MEM_GUARD_FAIL": "closed"})
        self.assertEqual(rc, mg.EXIT_BLOCKED)
        rc, _ = self.run_check("level=unknown", "--force", env={"MEM_GUARD_FAIL": "closed"})
        self.assertEqual(rc, 0)

    def test_quiet_suppresses_output_not_exit_code(self):
        rc, err = self.run_check("level=critical", "--quiet")
        self.assertEqual((rc, err), (mg.EXIT_BLOCKED, ""))

    def test_report_json_shape(self):
        out = io.StringIO()
        env = {"MEM_GUARD_HOST_FIXTURE": "level=normal free_pct=50", "MEM_GUARD_PS_FIXTURE": "/nonexistent-ps"}
        with mock.patch.dict(os.environ, env), redirect_stdout(out):
            self.assertEqual(mg.main(["report", "--json"]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["host_line"], "host pressure: normal, ~50% free")
        self.assertEqual(data["host"]["level"], "normal")
        self.assertFalse(data["process_table_ok"])
        self.assertEqual(data["sessions"], [])


if __name__ == "__main__":
    unittest.main()
