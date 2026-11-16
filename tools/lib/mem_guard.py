#!/usr/bin/env python3
"""Memory attribution and launch guard for parallel agent sessions.

    mem_guard.py report [--session <tmux-session>] [--tmux-bin B] [--socket S] [--json]
    mem_guard.py check  [--force] [--quiet] [--context <name>]

`report` attributes resident memory (RSS, summed over each session's process
tree) to workstreams and prints the host-wide pressure signal beside it.
`check` is the launch guard: exit 0 = go (possibly with warnings), exit 3 =
blocked. It never kills a process or touches a worktree.

Measurement model (see docs/memory-guard.md for the long version):

* Per-session figures are *estimates*: RSS counts a shared page once in every
  process mapping it (over-count) and omits compressed/swapped pages on macOS
  (under-count). Output rounds and prefixes them with "~".
* The *decision* to warn or block rests on the host signal, not the estimates:
  macOS `kern.memorystatus_vm_pressure_level` (the kernel's own verdict), plus
  free-memory percent where it can be read.
* Every process is assigned to exactly one session (its nearest root ancestor),
  so nested agents and subprocess trees are never double counted.
* Only the executable name is read from `ps` (`comm`), never argv, so prompts and
  secrets passed on a command line cannot reach the output.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import workstream  # noqa: E402

EXIT_BLOCKED = 3
LEVELS = ("ok", "warn", "block")
DEFAULT_AGENT_NAMES = ("claude", "agy", "codex")
PS_CMD = ["ps", "-axo", "pid=,ppid=,rss=,comm="]

Runner = Callable[[list[str]], "str | None"]


# ---- configuration ----------------------------------------------------------

@dataclasses.dataclass
class Config:
    guard: bool = True            # mem_enabled=off disables warnings and blocking
    warn_free_pct: float = 20.0   # free memory below this -> warn
    block_free_pct: float = 8.0   # free memory at/below this -> block launches
    session_warn_mb: int = 4096   # one session's estimate above this -> warn
    agents_warn_mb: int = 0       # all agent sessions together above this -> warn (0 = off)
    fail_closed: bool = False     # unreadable host pressure: False = warn and go
    agent_names: tuple[str, ...] = DEFAULT_AGENT_NAMES
    notes: list[str] = dataclasses.field(default_factory=list)


def _num(raw: str, default: float, key: str, notes: list[str]) -> float:
    try:
        val = float(raw)
        if not math.isfinite(val) or val < 0:
            raise ValueError
        return val
    except ValueError:
        notes.append(f"ignoring invalid {key}={raw!r}; using {default:g}")
        return default


def load_config(dir_: str = ".") -> Config:
    """Resolve settings: env MEM_GUARD_* > project > machine > user conf > defaults."""
    cfg = Config()

    def get(key: str, default: str) -> str:
        return workstream.resolve_setting(f"mem_{key}", dir_, f"MEM_GUARD_{key.upper()}", default)[0]

    cfg.guard = get("enabled", "on").strip().lower() not in ("off", "0", "false", "no")
    cfg.warn_free_pct = _num(get("warn_free_pct", "20"), 20.0, "mem_warn_free_pct", cfg.notes)
    cfg.block_free_pct = _num(get("block_free_pct", "8"), 8.0, "mem_block_free_pct", cfg.notes)
    cfg.session_warn_mb = int(_num(get("session_warn_mb", "4096"), 4096, "mem_session_warn_mb", cfg.notes))
    cfg.agents_warn_mb = int(_num(get("agents_warn_mb", "0"), 0, "mem_agents_warn_mb", cfg.notes))
    cfg.fail_closed = get("fail", "open").strip().lower() == "closed"
    names = tuple(n.strip().lower() for n in get("agent_names", ",".join(DEFAULT_AGENT_NAMES)).split(",") if n.strip())
    cfg.agent_names = names or DEFAULT_AGENT_NAMES
    if cfg.block_free_pct > cfg.warn_free_pct:
        cfg.notes.append("mem_block_free_pct is above mem_warn_free_pct; warning threshold raised to match")
        cfg.warn_free_pct = cfg.block_free_pct
    return cfg


# ---- process sampling and attribution ---------------------------------------

@dataclasses.dataclass
class Proc:
    pid: int
    ppid: int
    rss_kb: int
    name: str  # executable path as reported by ps comm (no arguments)


def run(cmd: list[str], timeout: float = 10.0, accept_nonzero: bool = False) -> str | None:
    """stdout of cmd, or None when it is missing, fails or times out.

    accept_nonzero keeps stdout from a non-zero exit: lsof exits 1 when any listed pid has
    gone or is unreadable yet still prints the rows it could read.
    """
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if (res.returncode == 0 or accept_nonzero) else None


def run_lenient(cmd: list[str]) -> str | None:
    return run(cmd, accept_nonzero=True)


def parse_ps(text: str) -> dict[int, Proc]:
    """Parse `ps -axo pid=,ppid=,rss=,comm=`; malformed lines are skipped."""
    procs: dict[int, Proc] = {}
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            pid, ppid, rss = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        procs[pid] = Proc(pid, ppid, max(0, rss), parts[3].strip())
    return procs


def sample_processes(runner: Runner = run) -> dict[int, Proc] | None:
    """Snapshot of all processes; None when ps is unavailable (callers degrade)."""
    fixture = os.environ.get("MEM_GUARD_PS_FIXTURE")  # test hook
    if fixture:
        try:
            return parse_ps(Path(fixture).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return None
    out = runner(PS_CMD)
    if out is None:
        return None
    procs = parse_ps(out)
    return procs or None


def _basename(name: str) -> str:
    return name.rstrip("/").rsplit("/", 1)[-1].lower()


def agent_name_of(name: str, agent_names: tuple[str, ...]) -> str | None:
    """Agent CLI name for an executable path, or None.

    Matches the basename, or an installer layout `<...>/<agent>/versions/<file>` (a native
    `claude` install execs a versioned file). Anything inside a `.app` bundle is a desktop
    application, not the CLI, and never matches: Claude.app and its helpers are not sessions.
    """
    low = name.lower()
    if ".app/" in low:
        return None
    parts = low.rstrip("/").split("/")
    if parts[-1] in agent_names:
        return parts[-1]
    if len(parts) >= 3 and parts[-2] == "versions" and parts[-3] in agent_names:
        return parts[-3]
    return None


def is_agent(proc: Proc, agent_names: tuple[str, ...]) -> bool:
    return agent_name_of(proc.name, agent_names) is not None


def backend_of(proc_names: list[str], agent_names: tuple[str, ...]) -> str:
    for name in proc_names:
        found = agent_name_of(name, agent_names)
        if found:
            return found
    return "-"


@dataclasses.dataclass
class Root:
    pid: int
    label: str
    source: str  # tmux | worktree | unmanaged
    key: str = ""  # stable id (tmux window index); label is for humans


@dataclasses.dataclass
class SessionMem:
    label: str
    source: str
    root_pid: int
    key: str
    backend: str
    procs: int
    rss_kb: int | None  # None: root process gone or ps unreadable
    state: str  # live | gone | unknown
    pids: list[int]

    @property
    def mb(self) -> float | None:
        return None if self.rss_kb is None else self.rss_kb / 1024.0


def _owner(pid: int, root_pids: set[int], procs: dict[int, Proc]) -> int | None:
    """Nearest ancestor-or-self of pid that is a root; None if there is none."""
    seen: set[int] = set()
    cur = pid
    while cur in procs and cur not in seen:
        if cur in root_pids:
            return cur
        seen.add(cur)
        cur = procs[cur].ppid
    return cur if cur in root_pids else None


def discover_agent_roots(
    procs: dict[int, Proc], known_roots: set[int], agent_names: tuple[str, ...]
) -> list[int]:
    """Top-most agent processes not already inside a known root.

    An agent that spawned another agent (subagents, nested CLIs) yields one
    root, so the pair is not listed twice.
    """
    agent_pids = {p.pid for p in procs.values() if is_agent(p, agent_names)}
    found: list[int] = []
    for pid in sorted(agent_pids):
        if _owner(pid, known_roots, procs) is not None:
            continue
        seen: set[int] = {pid}
        cur = procs[pid].ppid
        nested = False
        while cur in procs and cur not in seen:
            if cur in agent_pids:
                nested = True
                break
            seen.add(cur)
            cur = procs[cur].ppid
        if not nested:
            found.append(pid)
    return found


def attribute(
    procs: dict[int, Proc], roots: list[Root], agent_names: tuple[str, ...] = DEFAULT_AGENT_NAMES
) -> list[SessionMem]:
    """Assign every process to its nearest root and total each root's RSS.

    A process belongs to exactly one session, so overlapping trees (a root that
    is itself under another root) cannot be double counted. A root whose pid is
    no longer in the snapshot reports state "gone" and no figure rather than 0.
    """
    root_pids = {r.pid for r in roots}
    members: dict[int, list[Proc]] = {r.pid: [] for r in roots}
    for proc in procs.values():
        owner = _owner(proc.pid, root_pids, procs)
        if owner is not None:
            members[owner].append(proc)
    out: list[SessionMem] = []
    for root in roots:
        group = members.get(root.pid, [])
        live = root.pid in procs
        out.append(
            SessionMem(
                label=root.label,
                source=root.source,
                root_pid=root.pid,
                key=root.key,
                backend=backend_of([p.name for p in sorted(group, key=lambda p: p.pid)], agent_names),
                procs=len(group),
                rss_kb=sum(p.rss_kb for p in group) if live else None,
                state="live" if live else "gone",
                pids=sorted(p.pid for p in group),
            )
        )
    return out


def resolve_cwds(pids: list[int], runner: Runner = run_lenient) -> dict[int, str]:
    """Working directory per pid via one lsof call; empty when lsof is unavailable."""
    if not pids:
        return {}
    out = runner(["lsof", "-a", "-d", "cwd", "-Fpn", "-p", ",".join(str(p) for p in pids)])
    cwds: dict[int, str] = {}
    cur: int | None = None
    for line in (out or "").splitlines():
        if line.startswith("p") and line[1:].isdigit():
            cur = int(line[1:])
        elif line.startswith("n") and cur is not None:
            cwds[cur] = line[1:]
    return cwds


def workstream_label(cwd: str) -> str:
    """Workstream key for the nearest .workstream.json at or above cwd; '' if none."""
    cur = Path(cwd)
    while True:
        if (cur / workstream.RECORD_FILENAME).is_file():
            try:
                rec = workstream.load_record(str(cur))
            except (OSError, ValueError):
                rec = None
            if rec is not None:
                ids = "+".join(t["id"] for t in rec.tickets if t.get("id"))
                return rec.key or ids or cur.name
        if cur.parent == cur:
            break
        cur = cur.parent
    return ""


def build_roots_for_untracked(
    procs: dict[int, Proc],
    known: list[Root],
    agent_names: tuple[str, ...],
    cwd_runner: Runner = run_lenient,
) -> list[Root]:
    """Roots for agent sessions that were not started by the managed launcher."""
    pids = discover_agent_roots(procs, {r.pid for r in known}, agent_names)
    cwds = resolve_cwds(pids, cwd_runner)
    roots: list[Root] = []
    for pid in pids:
        cwd = cwds.get(pid, "")
        ws = workstream_label(cwd) if cwd else ""
        name = agent_name_of(procs[pid].name, agent_names) or _basename(procs[pid].name)
        if ws:
            roots.append(Root(pid, f"{ws} ({name})", "worktree"))
        else:
            where = Path(cwd).name if cwd else "?"
            roots.append(Root(pid, f"{name} pid {pid} [{where}]", "unmanaged"))
    return roots


def tmux_roots(
    session: str, tmux_bin: str = "tmux", socket: str | None = None, runner: Runner = run
) -> list[Root]:
    """One root per live pane of a launcher-managed tmux session (window 0 excluded)."""
    cmd = [tmux_bin] + (["-L", socket] if socket else [])
    # Space-separated with the free-text window name last: tmux rewrites control characters
    # (including tabs) in -F output when the locale is not UTF-8.
    fmt = "#{window_index} #{pane_pid} #{pane_dead} #{window_name}"
    out = runner([*cmd, "list-panes", "-s", "-t", f"={session}", "-F", fmt])
    roots: list[Root] = []
    for line in (out or "").splitlines():
        parts = line.split(" ", 3)
        if len(parts) < 4 or not parts[0].isdigit() or parts[0] == "0":
            continue
        idx, pid, dead, name = parts
        if dead == "1" or not pid.isdigit():
            # Dead pane: keep a row so the workstream is still listed, with no pid to measure.
            roots.append(Root(-int(idx), name, "tmux", idx))
        else:
            roots.append(Root(int(pid), name, "tmux", idx))
    return roots


# ---- host pressure -----------------------------------------------------------

@dataclasses.dataclass
class Host:
    level: str            # normal | warn | critical | unknown (OS level unreadable) | n/a (platform has none)
    free_pct: float | None
    source: str
    detail: str = ""


_DARWIN_LEVELS = {"1": "normal", "2": "warn", "4": "critical"}


def read_host(runner: Runner = run, platform: str | None = None) -> Host:
    """Host-wide pressure. Never raises; an unreadable signal comes back as level "unknown"."""
    fixture = os.environ.get("MEM_GUARD_HOST_FIXTURE")  # test hook: "level=critical free_pct=6"
    if fixture:
        kv = dict(re.findall(r"(\w+)=(\S+)", fixture))
        try:
            free = float(kv["free_pct"]) if "free_pct" in kv else None
        except ValueError:
            free = None
        return Host(kv.get("level", "unknown"), free, "fixture")
    plat = platform or sys.platform
    if plat == "darwin":
        raw = (runner(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]) or "").strip()
        level = _DARWIN_LEVELS.get(raw, "unknown")
        free: float | None = None
        mp = runner(["memory_pressure"])
        m = re.search(r"free percentage:\s*(\d+)%", mp or "")
        if m:
            free = float(m.group(1))
        src = "sysctl kern.memorystatus_vm_pressure_level" + (" + memory_pressure" if free is not None else "")
        return Host(level, free, src, "" if level != "unknown" else "pressure level unreadable")
    if plat.startswith("linux"):
        try:
            text = Path("/proc/meminfo").read_text()
            total = int(re.search(r"MemTotal:\s+(\d+)", text).group(1))  # type: ignore[union-attr]
            avail = int(re.search(r"MemAvailable:\s+(\d+)", text).group(1))  # type: ignore[union-attr]
            return Host("n/a", 100.0 * avail / total, "/proc/meminfo MemAvailable", "no OS pressure level on Linux")
        except (OSError, AttributeError, ValueError, ZeroDivisionError):
            return Host("unknown", None, "/proc/meminfo", "unreadable")
    return Host("unknown", None, plat, "unsupported platform")


# ---- verdict ------------------------------------------------------------------

@dataclasses.dataclass
class Verdict:
    status: str  # ok | warn | block | unknown
    reasons: list[str]


def _worse(a: str, b: str) -> str:
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


def evaluate(host: Host, sessions: list[SessionMem] | None, cfg: Config) -> Verdict:
    """Pure threshold logic. Only the host signal can block; per-session estimates only warn."""
    status = "ok"
    degraded = False
    reasons: list[str] = []
    if host.level == "unknown" and host.free_pct is None:
        return Verdict("unknown", [f"host memory pressure unreadable ({host.source}{': ' + host.detail if host.detail else ''})"])
    if host.level == "critical":
        status = "block"
        reasons.append("OS memory pressure is critical")
    elif host.level == "warn":
        status = "warn"
        reasons.append("OS memory pressure is elevated")
    if host.level == "unknown":
        # OS verdict unreadable but free % is available: judge by it, yet remember the
        # primary signal is missing so mem_fail=closed still applies if nothing else trips.
        degraded = True
        reasons.append(f"OS pressure level unreadable ({host.source}); relying on free memory only")
    if host.free_pct is not None:
        if host.free_pct <= cfg.block_free_pct:
            status = _worse(status, "block")
            reasons.append(f"free memory {host.free_pct:.0f}% <= block threshold {cfg.block_free_pct:g}%")
        elif host.free_pct < cfg.warn_free_pct:
            status = _worse(status, "warn")
            reasons.append(f"free memory {host.free_pct:.0f}% < warn threshold {cfg.warn_free_pct:g}%")
    live = [s for s in (sessions or []) if s.rss_kb is not None]
    if cfg.session_warn_mb:
        for s in live:
            if s.mb is not None and s.mb > cfg.session_warn_mb:
                status = _worse(status, "warn")
                reasons.append(f"{s.label} uses {fmt_mb(s.mb)} (> {cfg.session_warn_mb} MB per-session warning)")
    if cfg.agents_warn_mb:
        total = sum(s.mb or 0 for s in live)
        if total > cfg.agents_warn_mb:
            status = _worse(status, "warn")
            reasons.append(f"agent sessions total {fmt_mb(total)} (> {cfg.agents_warn_mb} MB)")
    if degraded and status == "ok":
        status = "unknown"  # free % looked fine, but the kernel's own verdict is missing
    return Verdict(status, reasons)


# ---- formatting --------------------------------------------------------------

def fmt_mb(mb: float | None) -> str:
    """Rounded, '~'-prefixed figure: estimates must not look exact."""
    if mb is None:
        return "-"
    if mb >= 1024:
        return f"~{mb / 1024:.1f} GB"
    return f"~{int(round(mb / 10.0)) * 10} MB"


def host_line(host: Host) -> str:
    free = f", ~{host.free_pct:.0f}% free" if host.free_pct is not None else ""
    return f"host pressure: {host.level}{free}"


ESTIMATE_NOTE = (
    "Mem is summed RSS per process tree: shared pages count in every process that maps them "
    "(over-count) and macOS compressed/swapped pages are missing (under-count). "
    "Trust the host pressure line over these figures."
)


def render_report(sessions: list[SessionMem], host: Host, procs_ok: bool = True) -> str:
    lines = [host_line(host)]
    if not procs_ok:
        lines.append("process table unreadable (ps failed); no per-session figures")
    rows = sorted(sessions, key=lambda s: -(s.rss_kb or -1))
    if rows:
        lines.append(f"{'Session':<34} {'Backend':<8} {'Procs':>5} {'Mem':>10}  State")
        for s in rows:
            state = {"live": "", "gone": "exited", "unknown": "unknown"}[s.state]
            tag = "" if s.source in ("tmux", "worktree") else " *"
            lines.append(f"{(s.label + tag)[:34]:<34} {s.backend:<8} {s.procs:>5} {fmt_mb(s.mb):>10}  {state}")
        total = sum(s.mb or 0 for s in rows)
        lines.append(f"{'total (agent sessions)':<34} {'':<8} {sum(s.procs for s in rows):>5} {fmt_mb(total):>10}")
        if any(s.source == "unmanaged" for s in rows):
            lines.append("* started outside the launcher; matched by executable name only")
    else:
        lines.append("no agent sessions found")
    lines.append(ESTIMATE_NOTE)
    return "\n".join(lines)


# ---- sampling entry points ------------------------------------------------------

def collect(
    cfg: Config,
    session: str | None = None,
    tmux_bin: str = "tmux",
    socket: str | None = None,
    runner: Runner = run,
) -> tuple[list[SessionMem], bool]:
    """(sessions, procs_ok). Never raises; a failed ps yields ([], False)."""
    procs = sample_processes(runner)
    if procs is None:
        return ([], False)
    roots = tmux_roots(session, tmux_bin, socket, runner) if session else []
    roots += build_roots_for_untracked(procs, roots, cfg.agent_names, run_lenient if runner is run else runner)
    return (attribute(procs, roots, cfg.agent_names), True)


# ---- CLI ----------------------------------------------------------------------

def _cmd_report(args: argparse.Namespace) -> int:
    cfg = load_config()
    sessions, ok = collect(cfg, args.session, args.tmux_bin, args.socket)
    host = read_host()
    if args.json:
        print(json.dumps({
            "host": dataclasses.asdict(host),
            "process_table_ok": ok,
            "host_line": host_line(host),
            "sessions": [{**dataclasses.asdict(s), "mem": fmt_mb(s.mb)} for s in sessions],
            "verdict": dataclasses.asdict(evaluate(host, sessions, cfg)),
            "estimate_note": ESTIMATE_NOTE,
        }, indent=2))
    else:
        print(render_report(sessions, host, ok))
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    cfg = load_config()
    say = (lambda *_: None) if args.quiet else (lambda m: print(m, file=sys.stderr))
    for note in cfg.notes:
        say(f"mem-guard: {note}")
    if not cfg.guard:
        return 0
    override = args.force or os.environ.get("MEM_GUARD_OVERRIDE", "") not in ("", "0")
    host = read_host()
    sessions, _ = collect(cfg)
    verdict = evaluate(host, sessions, cfg)
    ctx = f" ({args.context})" if args.context else ""
    top = sorted((s for s in sessions if s.rss_kb), key=lambda s: -(s.rss_kb or 0))[:3]
    detail = "; ".join(f"{s.label} {fmt_mb(s.mb)}" for s in top)

    def explain() -> None:
        for r in verdict.reasons:
            say(f"mem-guard:   - {r}")
        if detail:
            say(f"mem-guard:   largest sessions (estimates): {detail}")
        say("mem-guard:   inspect with: mem-guard.sh report")

    if verdict.status == "ok":
        return 0
    if verdict.status == "warn":
        say(f"mem-guard: WARNING{ctx}: memory is getting tight; launching anyway ({host_line(host)})")
        explain()
        return 0
    if verdict.status == "unknown":
        if cfg.fail_closed and not override:
            say(f"mem-guard: BLOCKED{ctx}: cannot read memory pressure and mem_fail=closed")
            explain()
            say("mem-guard:   override: --force or MEM_GUARD_OVERRIDE=1 (nothing was killed or discarded)")
            return EXIT_BLOCKED
        say(f"mem-guard: WARNING{ctx}: cannot read memory pressure; not blocking (mem_fail=open)")
        explain()
        return 0
    if override:
        say(f"mem-guard: OVERRIDE{ctx}: memory pressure is dangerous but the guard was overridden ({host_line(host)})")
        explain()
        return 0
    say(f"mem-guard: BLOCKED{ctx}: not launching more work while memory pressure is dangerous ({host_line(host)})")
    explain()
    say("mem-guard:   free memory by closing sessions yourself (no session was killed, no work discarded),")
    say("mem-guard:   or override once with MEM_GUARD_OVERRIDE=1 (or --force where the launcher takes it), or tune mem_block_free_pct / mem_enabled=off")
    return EXIT_BLOCKED


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Agent session memory attribution and launch guard.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="per-session memory estimates and host pressure")
    r.add_argument("--session", help="tmux session to attribute by window (agy-tmux session)")
    r.add_argument("--tmux-bin", default=os.environ.get("AGY_TMUX_TMUX_BIN") or "tmux")
    r.add_argument("--socket", default=None)
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=_cmd_report)
    c = sub.add_parser("check", help="launch guard: exit 0 go, exit 3 blocked")
    c.add_argument("--force", action="store_true", help="launch despite a block (also MEM_GUARD_OVERRIDE=1)")
    c.add_argument("--quiet", action="store_true")
    c.add_argument("--context", default="", help="what is being launched, for the message")
    c.set_defaults(fn=_cmd_check)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
