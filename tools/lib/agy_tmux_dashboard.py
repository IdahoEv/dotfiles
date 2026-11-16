#!/usr/bin/env python3
"""Interactive tmux dashboard for agy-tmux workstreams."""

from __future__ import annotations

import argparse
import curses
import dataclasses
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import repo_facts  # noqa: E402
import workstream  # noqa: E402

ACTIVE_THRESHOLD_SECS = 5
VIEW_MODES = ("flat", "project", "state")
STATE_ORDER = ("running", "idle", "exited")


@dataclasses.dataclass
class WorkstreamRow:
    window_index: str
    window_name: str
    pane_id: str
    pane_path: str
    ticket_ref: str
    desc: str
    branch: str
    status: str
    last_line: str
    project: str = ""
    mem: str = ""  # estimate for the window's process tree ("~1.2 GB"), "" when not measured


@dataclasses.dataclass(frozen=True)
class DisplayItem:
    header: str | None = None
    row_index: int | None = None
    row: WorkstreamRow | None = None

    @property
    def is_header(self) -> bool:
        return self.header is not None


def format_age(seconds: int) -> str:
    """Format a non-negative age in seconds as a compact string."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h"


def compute_status(pane_dead: bool, last_activity: int | None, now: int) -> str:
    """Derive a concise agent status from pane liveness and tmux activity timestamp."""
    if pane_dead:
        return "exited"
    if last_activity is None or last_activity <= 0:
        return "running"
    age = max(0, now - last_activity)
    if age <= ACTIVE_THRESHOLD_SECS:
        return "running"
    return f"idle ({format_age(age)})"


def row_state(status: str) -> str:
    """Normalize a WorkstreamRow status string into running, idle, or exited."""
    if status == "exited":
        return "exited"
    if status.startswith("idle"):
        return "idle"
    return "running"


def resolve_project(pane_path: str) -> str:
    """Derive a project name from pane_path's git main root, falling back to basename."""
    if pane_path and os.path.isdir(pane_path):
        root = repo_facts.main_root(pane_path)
        return Path(root or pane_path).name or "other"
    if pane_path:
        return Path(pane_path).name or "other"
    return "other"


def _populate_projects(rows: list[WorkstreamRow], cache: dict[str, str]) -> None:
    """Resolve and cache row.project per pane_path for project grouping."""
    for row in rows:
        if row.project:
            continue
        if row.pane_path not in cache:
            cache[row.pane_path] = resolve_project(row.pane_path)
        row.project = cache[row.pane_path]


def extract_last_line(captured_text: str) -> str:
    """Return the last non-empty line from captured pane output, single-line."""
    for line in reversed(captured_text.splitlines()):
        stripped = " ".join(line.split())
        if stripped:
            return stripped
    return ""


def load_workstream_meta(pane_path: str) -> tuple[str, str]:
    """Return (ticket_ref, desc) from <pane_path>/.workstream.json when present."""
    if not pane_path or not os.path.isdir(pane_path):
        return ("", "")
    rec = workstream.load_record(pane_path)
    if rec is None:
        return ("", "")
    ticket_ref = rec.key or ""
    if not ticket_ref and rec.tickets:
        ids = [t.get("id", "") for t in rec.tickets if t.get("id")]
        if ids:
            prefix = workstream.PROVIDER_TOKENS.get(rec.ticket_provider, {}).get("brief", "")
            ticket_ref = f"{prefix}{'+'.join(ids)}"
    return (ticket_ref, rec.desc or "")


def _tmux_base(tmux_bin: str, socket: str | None) -> list[str]:
    cmd = [tmux_bin]
    if socket:
        cmd.extend(["-L", socket])
    return cmd


def _run_cmd(cmd: list[str]) -> str:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return res.stdout if res.returncode == 0 else ""
    except OSError:
        return ""


def _git_branch(path: str) -> str:
    if not path or not os.path.isdir(path):
        return ""
    return _run_cmd(["git", "-C", path, "branch", "--show-current"]).strip()


MEM_REFRESH_SECS = 10.0
MEM_CMD_TIMEOUT_SECS = 20.0


def fetch_memory(mem_cmd: str) -> tuple[dict[str, str], str]:
    """({window_index: "~1.2 GB"}, host line) from an optional memory provider.

    The provider is any command that prints the `mem-guard.sh report --json` shape. The
    dashboard knows only that JSON contract, not how memory is measured. Best effort: any
    failure yields ({}, "") so a broken provider never affects the dashboard.
    """
    if not mem_cmd:
        return ({}, "")
    try:
        res = subprocess.run(
            shlex.split(mem_cmd), capture_output=True, text=True, check=False, timeout=MEM_CMD_TIMEOUT_SECS
        )
        if res.returncode != 0:
            return ({}, "")
        data = json.loads(res.stdout)
        by_window = {
            str(s["key"]): str(s.get("mem") or "-")
            for s in data.get("sessions", [])
            if s.get("source") == "tmux" and s.get("key")
        }
        line = str(data.get("host_line") or "")
        status = str((data.get("verdict") or {}).get("status") or "")
        if line and status in ("warn", "block"):
            line += f"  [{status.upper()}]"
        if line and not data.get("process_table_ok", True):
            line += "  (process table unreadable)"
        return (by_window, line)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return ({}, "")


class MemorySampler:
    """Samples the memory provider on a background thread so slow `ps`/`lsof` never stall the UI."""

    def __init__(self, mem_cmd: str, interval: float = MEM_REFRESH_SECS) -> None:
        self._cmd = mem_cmd
        self._interval = interval
        self._lock = threading.Lock()
        self._value: tuple[dict[str, str], str] = ({}, "")
        if mem_cmd:
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while True:
            value = fetch_memory(self._cmd)
            with self._lock:
                self._value = value
            time.sleep(self._interval)

    def latest(self) -> tuple[dict[str, str], str]:
        with self._lock:
            return self._value


def fetch_windows(
    session: str,
    tmux_bin: str = "tmux",
    socket: str | None = None,
    now: int | None = None,
) -> list[WorkstreamRow]:
    """Query tmux for all non-dashboard windows in <session> and enrich with workstream metadata."""
    base = _tmux_base(tmux_bin, socket)
    fmt = "#{window_index}\t#{window_name}\t#{pane_id}\t#{pane_current_path}\t#{pane_dead}\t#{window_activity}"
    raw = _run_cmd([*base, "list-windows", "-t", f"={session}", "-F", fmt])
    if not raw.strip():
        return []

    current_time = int(time.time()) if now is None else now
    rows: list[WorkstreamRow] = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        win_idx, win_name, pane_id, pane_path, pane_dead_raw, activity_raw = parts[:6]
        if win_idx == "0":
            continue
        pane_dead = pane_dead_raw == "1"
        try:
            last_activity = int(activity_raw) if activity_raw else None
        except ValueError:
            last_activity = None

        ticket_ref, desc = load_workstream_meta(pane_path)
        branch = "" if desc else _git_branch(pane_path)
        captured = _run_cmd([*base, "capture-pane", "-p", "-t", pane_id, "-S", "-30"])
        status = compute_status(pane_dead, last_activity, current_time)
        rows.append(
            WorkstreamRow(
                window_index=win_idx,
                window_name=win_name,
                pane_id=pane_id,
                pane_path=pane_path,
                ticket_ref=ticket_ref or win_name,
                desc=desc or branch or Path(pane_path).name,
                branch=branch,
                status=status,
                last_line=extract_last_line(captured),
            )
        )
    return rows


def _clip(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return text[:1]
    return text[: width - 1] + "…"


def next_view_mode(mode: str) -> str:
    """Cycle through flat -> project -> state -> flat."""
    try:
        idx = VIEW_MODES.index(mode)
    except ValueError:
        return VIEW_MODES[0]
    return VIEW_MODES[(idx + 1) % len(VIEW_MODES)]


def build_display_items(
    rows: list[WorkstreamRow],
    view_mode: str = "flat",
) -> list[DisplayItem]:
    """Build display items (with optional group headers) for the active view mode."""
    if not rows:
        return []
    if view_mode == "flat":
        return [DisplayItem(row_index=i, row=row) for i, row in enumerate(rows)]

    groups: dict[str, list[tuple[int, WorkstreamRow]]] = {}
    for i, row in enumerate(rows):
        if view_mode == "project":
            key = row.project or resolve_project(row.pane_path)
        elif view_mode == "state":
            key = row_state(row.status)
        else:
            key = "other"
        groups.setdefault(key, []).append((i, row))

    if view_mode == "state":
        ordered_keys = [k for k in STATE_ORDER if k in groups]
        ordered_keys.extend(k for k in sorted(groups) if k not in STATE_ORDER)
    else:
        ordered_keys = sorted(groups, key=str.lower)

    items: list[DisplayItem] = []
    for key in ordered_keys:
        members = groups[key]
        items.append(DisplayItem(header=f"── {key} ({len(members)})"))
        for orig_idx, row in members:
            items.append(DisplayItem(row_index=orig_idx, row=row))
    return items


def step_selection(items: list[DisplayItem], selected: int, delta: int) -> int:
    """Move selection by delta (+1/-1), wrapping and skipping group headers."""
    selectable = [i for i, item in enumerate(items) if not item.is_header]
    if not selectable:
        return 0
    if selected not in selectable:
        return selectable[0] if delta >= 0 else selectable[-1]
    pos = selectable.index(selected)
    return selectable[(pos + delta) % len(selectable)]


def first_selectable_index(
    items: list[DisplayItem],
    preferred_pane_id: str | None = None,
) -> int:
    """Return display index matching preferred_pane_id, or the first selectable row."""
    first = 0
    found_first = False
    for i, item in enumerate(items):
        if item.is_header:
            continue
        if not found_first:
            first = i
            found_first = True
        if preferred_pane_id and item.row and item.row.pane_id == preferred_pane_id:
            return i
    return first


def visible_slice(
    total: int,
    selected: int,
    max_rows: int | None,
    items: list[DisplayItem] | None = None,
) -> tuple[int, int]:
    """Return [start, end) slice of items keeping selected centered in max_rows."""
    if total <= 0:
        return (0, 0)
    if max_rows is None or total <= max_rows:
        return (0, total)
    cap = max(1, max_rows)
    start = max(0, min(selected - cap // 2, total - cap))
    # Include the group header immediately above start when it fits without hiding selected.
    if items and start > 0 and items[start - 1].is_header and selected < start + cap - 1:
        start -= 1
    return (start, start + cap)


def render_lines(
    rows: list[WorkstreamRow],
    selected: int,
    width: int,
    session: str,
    max_rows: int | None = None,
    view_mode: str = "flat",
    host_line: str = "",
) -> list[str]:
    """Render the dashboard header, workstream table, and footer into text lines."""
    w = max(40, width)
    lines: list[str] = []
    title = f"agy-tmux dashboard  [{session}]  [{view_mode}]  ({len(rows)} workstreams)"
    lines.append(_clip(f"{title}  {host_line}" if host_line else title, w))
    lines.append("─" * w)

    items = build_display_items(rows, view_mode)
    if not items:
        lines.append("No active workstream windows. Launch tickets with: agy-tmux.sh <id> ...")
    else:
        header = f"  {'#':<3} {'Ticket':<12} {'Status':<12} {'Mem':<9} {'Title':<28} {'Last output'}"
        lines.append(_clip(header, w))
        start, end = visible_slice(len(items), selected, max_rows, items=items)
        fixed_width = 2 + 4 + 13 + 13 + 10 + 29
        rem = max(10, w - fixed_width)
        for idx in range(start, end):
            item = items[idx]
            if item.is_header:
                lines.append(_clip(item.header or "", w))
                continue
            row = item.row
            assert row is not None
            marker = ">" if idx == selected else " "
            line = (
                f"{marker} {row.window_index:<3} "
                f"{_clip(row.ticket_ref, 12):<12} "
                f"{_clip(row.status, 12):<12} "
                f"{_clip(row.mem or '-', 9):<9} "
                f"{_clip(row.desc, 28):<28} "
                f"{_clip(row.last_line, rem)}"
            )
            lines.append(_clip(line, w))

    lines.append("─" * w)
    lines.append(
        _clip(
            "↑/↓ j/k: select  Enter/1-9: switch  g: group  Ctrl-z (in agent): return  r: refresh  x: close  q: detach",
            w,
        )
    )
    return lines


def _switch_to_window(base: list[str], session: str, window_index: str) -> None:
    subprocess.run([*base, "select-window", "-t", f"={session}:{window_index}"], check=False)


def _kill_window(base: list[str], session: str, window_index: str) -> None:
    subprocess.run([*base, "kill-window", "-t", f"={session}:{window_index}"], check=False)


def _detach_client(base: list[str]) -> None:
    subprocess.run([*base, "detach-client"], check=False)


def _curses_loop(
    stdscr: Any,
    session: str,
    socket: str | None,
    refresh_sec: float,
    tmux_bin: str = "tmux",
    mem_cmd: str = "",
) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(int(refresh_sec * 1000))
    base = _tmux_base(tmux_bin, socket)
    selected = 0
    view_mode = VIEW_MODES[0]
    rows: list[WorkstreamRow] = []
    items: list[DisplayItem] = []
    project_cache: dict[str, str] = {}
    host_line = ""
    sampler = MemorySampler(mem_cmd)
    needs_refresh = True

    while True:
        if needs_refresh:
            prev_pane_id = (
                items[selected].row.pane_id
                if 0 <= selected < len(items) and items[selected].row is not None
                else None
            )
            rows = fetch_windows(session, tmux_bin=tmux_bin, socket=socket)
            mem_by_window, host_line = sampler.latest()
            for row in rows:
                row.mem = mem_by_window.get(row.window_index, "")
            if view_mode == "project":
                _populate_projects(rows, project_cache)
            items = build_display_items(rows, view_mode)
            selected = first_selectable_index(items, prev_pane_id)
            needs_refresh = False
        elif items:
            selected = first_selectable_index(
                items,
                items[selected].row.pane_id
                if 0 <= selected < len(items) and items[selected].row is not None
                else None,
            )
        else:
            selected = 0

        height, width = stdscr.getmaxyx()
        max_rows = max(1, height - 6)
        start, end = visible_slice(len(items), selected, max_rows, items=items)
        selected_line = 3 + (selected - start)
        lines = render_lines(
            rows,
            selected,
            width - 1,
            session,
            max_rows=max_rows,
            view_mode=view_mode,
            host_line=host_line,
        )
        stdscr.erase()
        for y, text in enumerate(lines[: max(1, height - 1)]):
            attr = curses.A_NORMAL
            if y == 0:
                attr = curses.A_BOLD
            elif items and y == selected_line and not items[selected].is_header:
                attr = curses.A_REVERSE
            elif 3 <= y < 3 + (end - start) and items[start + (y - 3)].is_header:
                attr = curses.A_BOLD
            try:
                stdscr.addnstr(y, 0, text, max(1, width - 1), attr)
            except curses.error:
                pass
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1 or ch in (ord("r"), ord("R")):
            needs_refresh = True
            continue
        if ch in (ord("q"), ord("Q")):
            _detach_client(base)
            continue
        if ch in (ord("g"), ord("G")):
            prev_pane_id = (
                items[selected].row.pane_id
                if 0 <= selected < len(items) and items[selected].row is not None
                else None
            )
            view_mode = next_view_mode(view_mode)
            if view_mode == "project":
                _populate_projects(rows, project_cache)
            items = build_display_items(rows, view_mode)
            selected = first_selectable_index(items, prev_pane_id)
        elif ch in (curses.KEY_UP, ord("k")) and items:
            selected = step_selection(items, selected, -1)
        elif ch in (curses.KEY_DOWN, ord("j")) and items:
            selected = step_selection(items, selected, 1)
        elif ch in (10, 13, curses.KEY_ENTER) and items:
            row = items[selected].row if 0 <= selected < len(items) else None
            if row is not None:
                _switch_to_window(base, session, row.window_index)
        elif ord("1") <= ch <= ord("9") and rows:
            target = chr(ch)
            for row in rows:
                if row.window_index == target:
                    _switch_to_window(base, session, target)
                    break
        elif ch in (ord("x"), ord("X")) and items:
            row = items[selected].row if 0 <= selected < len(items) else None
            if row is not None and row.status == "exited":
                _kill_window(base, session, row.window_index)
                needs_refresh = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive tmux dashboard for agy-tmux.")
    parser.add_argument("--session", required=True, help="Target tmux session name")
    parser.add_argument("--socket", default=None, help="Optional tmux -L socket name")
    parser.add_argument(
        "--tmux-bin",
        default=os.environ.get("AGY_TMUX_TMUX_BIN") or "tmux",
        help="Path or name of the tmux binary",
    )
    parser.add_argument("--refresh", type=float, default=2.0, help="Refresh interval in seconds")
    parser.add_argument(
        "--mem-cmd",
        default="",
        help="Optional command printing `mem-guard.sh report --json`; enables the Mem column and host line",
    )
    args = parser.parse_args(argv)

    curses.wrapper(_curses_loop, args.session, args.socket, args.refresh, args.tmux_bin, args.mem_cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
