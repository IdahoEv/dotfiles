#!/usr/bin/env python3
"""Interactive tmux dashboard for agy-tmux workstreams."""

from __future__ import annotations

import argparse
import curses
import dataclasses
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import repo_facts  # noqa: E402
import workstream  # noqa: E402

ACTIVE_THRESHOLD_SECS = 5
PALETTE = ("red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan")
_DEFAULT_COLORS_FILE = _LIB_DIR.parent / "project-colors"

_BASE_CURSES_COLORS = {
    "red": curses.COLOR_RED,
    "blue": curses.COLOR_BLUE,
    "green": curses.COLOR_GREEN,
    "yellow": curses.COLOR_YELLOW,
    "purple": curses.COLOR_MAGENTA,
    "orange": curses.COLOR_YELLOW,
    "pink": curses.COLOR_MAGENTA,
    "cyan": curses.COLOR_CYAN,
}
_EXTENDED_256_COLORS = {
    "purple": 141,
    "orange": 208,
    "pink": 205,
}


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
    color: str = ""


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


def extract_last_line(captured_text: str) -> str:
    """Return the last non-empty line from captured pane output, single-line."""
    for line in reversed(captured_text.splitlines()):
        stripped = " ".join(line.split())
        if stripped:
            return stripped
    return ""


def _lookup_project_colors_file(project: str, colors_file: Path) -> str:
    """Return the palette color for <project> from <colors_file>, or ''."""
    if not project or not colors_file.is_file():
        return ""
    target = project.lower()
    try:
        text = colors_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower() == target:
            candidate = parts[1].lower()
            return candidate if candidate in PALETTE else ""
    return ""


def resolve_project_color(pane_path: str, colors_file: Path | None = None) -> str:
    """Resolve a workstream's project color via .start-ticket.conf then project-colors."""
    if not pane_path or not os.path.isdir(pane_path):
        return ""
    conf_val = repo_facts.conf_get("color", pane_path)
    if conf_val is not None:
        candidate = conf_val.strip().lower()
        if candidate:
            return candidate if candidate in PALETTE else ""

    main = repo_facts.main_root(pane_path)
    proj = Path(main).name if main else ""
    if not proj:
        return ""

    if colors_file is None:
        env_file = os.environ.get("SESSION_LABEL_COLORS_FILE")
        colors_file = Path(env_file) if env_file else _DEFAULT_COLORS_FILE
    return _lookup_project_colors_file(proj, colors_file)


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
        rows.append(
            WorkstreamRow(
                window_index=win_idx,
                window_name=win_name,
                pane_id=pane_id,
                pane_path=pane_path,
                ticket_ref=ticket_ref or win_name,
                desc=desc or branch or Path(pane_path).name,
                branch=branch,
                status=compute_status(pane_dead, last_activity, current_time),
                last_line=extract_last_line(captured),
                color=resolve_project_color(pane_path),
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


def visible_slice(total: int, selected: int, max_rows: int | None) -> tuple[int, int]:
    """Return [start, end) slice of rows keeping selected centered in max_rows."""
    if total <= 0:
        return (0, 0)
    if max_rows is None or total <= max_rows:
        return (0, total)
    cap = max(1, max_rows)
    start = max(0, min(selected - cap // 2, total - cap))
    return (start, start + cap)


def render_lines(
    rows: list[WorkstreamRow],
    selected: int,
    width: int,
    session: str,
    max_rows: int | None = None,
) -> list[str]:
    """Render the dashboard header, workstream table, and footer into text lines."""
    w = max(40, width)
    lines: list[str] = []
    lines.append(_clip(f"agy-tmux dashboard  [{session}]  ({len(rows)} workstreams)", w))
    lines.append("─" * w)

    if not rows:
        lines.append("No active workstream windows. Launch tickets with: agy-tmux.sh <id> ...")
    else:
        header = f"  {'#':<3} {'Ticket':<12} {'Status':<12} {'Title':<28} {'Last output'}"
        lines.append(_clip(header, w))
        start, end = visible_slice(len(rows), selected, max_rows)
        for idx in range(start, end):
            row = rows[idx]
            marker = ">" if idx == selected else " "
            fixed_width = 2 + 4 + 13 + 13 + 29
            rem = max(10, w - fixed_width)
            line = (
                f"{marker} {row.window_index:<3} "
                f"{_clip(row.ticket_ref, 12):<12} "
                f"{_clip(row.status, 12):<12} "
                f"{_clip(row.desc, 28):<28} "
                f"{_clip(row.last_line, rem)}"
            )
            lines.append(_clip(line, w))

    lines.append("─" * w)
    lines.append(
        _clip(
            "↑/↓ j/k: select  Enter/1-9: switch  Ctrl-z (in agent): return  r: refresh  x: close  q: detach",
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


def init_color_pairs() -> dict[str, int]:
    """Initialize curses color pairs for PALETTE; return {} when unsupported."""
    try:
        if not curses.has_colors():
            return {}
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        use_256 = getattr(curses, "COLORS", 0) >= 256
        pairs: dict[str, int] = {}
        for idx, name in enumerate(PALETTE, start=1):
            fg = _EXTENDED_256_COLORS[name] if (use_256 and name in _EXTENDED_256_COLORS) else _BASE_CURSES_COLORS[name]
            try:
                curses.init_pair(idx, fg, bg)
            except curses.error:
                break
            pairs[name] = idx
        return pairs
    except curses.error:
        return {}


def _draw_row(
    stdscr: Any,
    y: int,
    text: str,
    max_width: int,
    row: WorkstreamRow | None,
    is_selected: bool,
    color_pairs: dict[str, int],
) -> None:
    """Draw one dashboard line, colorizing the ticket and title columns when supported."""
    if y == 0:
        base_attr = curses.A_BOLD
    elif is_selected:
        base_attr = curses.A_REVERSE
    else:
        base_attr = curses.A_NORMAL
    try:
        stdscr.addnstr(y, 0, text, max_width, base_attr)
    except curses.error:
        return

    if row is None or row.color not in color_pairs:
        return
    color_attr = base_attr | curses.color_pair(color_pairs[row.color])
    limit = min(len(text), max_width)
    for start, end in ((6, 18), (32, 60)):
        if start >= limit:
            continue
        seg = text[start : min(end, limit)]
        if seg:
            try:
                stdscr.addnstr(y, start, seg, len(seg), color_attr)
            except curses.error:
                pass


def _curses_loop(
    stdscr: Any,
    session: str,
    socket: str | None,
    refresh_sec: float,
    tmux_bin: str = "tmux",
) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(int(refresh_sec * 1000))
    color_pairs = init_color_pairs()
    base = _tmux_base(tmux_bin, socket)
    selected = 0
    rows: list[WorkstreamRow] = []
    needs_refresh = True

    while True:
        if needs_refresh:
            rows = fetch_windows(session, tmux_bin=tmux_bin, socket=socket)
            needs_refresh = False
        if rows:
            selected = max(0, min(selected, len(rows) - 1))
        else:
            selected = 0

        height, width = stdscr.getmaxyx()
        max_rows = max(1, height - 6)
        start, end = visible_slice(len(rows), selected, max_rows)
        visible_rows = rows[start:end]
        lines = render_lines(rows, selected, width - 1, session, max_rows=max_rows)
        max_width = max(1, width - 1)
        stdscr.erase()
        for y, text in enumerate(lines[: max(1, height - 1)]):
            row_idx = y - 3
            row = visible_rows[row_idx] if (rows and 0 <= row_idx < len(visible_rows)) else None
            is_selected = bool(rows and row is not None and (start + row_idx) == selected)
            _draw_row(stdscr, y, text, max_width, row, is_selected, color_pairs)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1 or ch in (ord("r"), ord("R")):
            needs_refresh = True
            continue
        if ch in (ord("q"), ord("Q")):
            _detach_client(base)
            continue
        if ch in (curses.KEY_UP, ord("k")) and rows:
            selected = (selected - 1) % len(rows)
        elif ch in (curses.KEY_DOWN, ord("j")) and rows:
            selected = (selected + 1) % len(rows)
        elif ch in (10, 13, curses.KEY_ENTER) and rows:
            _switch_to_window(base, session, rows[selected].window_index)
        elif ord("1") <= ch <= ord("9") and rows:
            target = chr(ch)
            for row in rows:
                if row.window_index == target:
                    _switch_to_window(base, session, target)
                    break
        elif ch in (ord("x"), ord("X")) and rows:
            row = rows[selected]
            if row.status == "exited":
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
    args = parser.parse_args(argv)

    curses.wrapper(_curses_loop, args.session, args.socket, args.refresh, args.tmux_bin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
