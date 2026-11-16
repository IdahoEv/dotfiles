#!/usr/bin/env python3
"""Interactive tmux dashboard for agy-tmux workstreams."""

from __future__ import annotations

import argparse
import curses
import dataclasses
import json
import os
import re
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
STATE_ORDER = ("waiting", "working", "idle", "exited")
PALETTE = ("red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan")
_DEFAULT_COLORS_FILE = _LIB_DIR.parent / "project-colors"
_COLOR_CACHE: dict[tuple[str, str], str] = {}

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
    tags: str = ""
    project: str = ""
    color: str = ""
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


_STATUSLINE_STATE_RE = re.compile(
    r"\|\s*\[(thinking|working|running|tool_use|idle|waiting|permission|question|error)\](?:\s*\||\s*$)",
    re.IGNORECASE,
)
_WAITING_PROMPT_RE = re.compile(
    r"(?:^|\s)(?:"
    r"enter to select|space to select|allow once|allow for this session|always allow|"
    r"yes,\s*allow|no,\s*deny|do you want to (?:proceed|run|allow|continue)|"
    r"\[[yY]/[nN]\]"
    r")",
    re.IGNORECASE,
)
_WAITING_MENU_RE = re.compile(r"^\s*[❯>]\s*1\.\s+\S")
_SUBAGENT_ACTIVE_RE = re.compile(r"^\s*●\s+Agent\(")
_SPINNER_RE = re.compile(r"^\s*[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷]\s+\w")
_INTERRUPT_HINT_RE = re.compile(r"\besc to interrupt\b", re.IGNORECASE)
_RULE_LINE_RE = re.compile(r"^─{10,}$")
_PROMPT_LINE_RE = re.compile(r"^>\s*(?:$|Plan mode:|Auto mode:)")


def _extract_statusline_state(lines: list[str]) -> tuple[str | None, list[str]]:
    """Return (statusline_state, body_lines) by inspecting the bottom statusline region."""
    tail = lines[-6:]
    state: str | None = None
    cut = len(lines)
    for idx in range(len(tail) - 1, -1, -1):
        m = _STATUSLINE_STATE_RE.search(tail[idx])
        if m:
            state = m.group(1).lower()
            cut = len(lines) - len(tail) + idx
            break
    return state, lines[:cut]


def _has_prompt_box(lines: list[str]) -> bool:
    """Return True when the tail contains agy's horizontal-rule input box."""
    for i, line in enumerate(lines):
        if _PROMPT_LINE_RE.match(line):
            has_rule_above = i > 0 and bool(_RULE_LINE_RE.match(lines[i - 1]))
            has_rule_below = i + 1 < len(lines) and bool(_RULE_LINE_RE.match(lines[i + 1]))
            if has_rule_above or has_rule_below:
                return True
    return False


def _classify_pane_state(captured: str) -> str | None:
    """Classify an agy pane's attention state from captured output, or None if unknown."""
    if not captured:
        return None
    non_empty = [ln.strip() for ln in captured.splitlines() if ln.strip()]
    if not non_empty:
        return None

    sl_state, body_lines = _extract_statusline_state(non_empty)
    if sl_state in ("waiting", "permission", "question"):
        return "waiting"

    recent_body = body_lines[-8:] if body_lines else non_empty[-8:]
    for line in recent_body:
        if _WAITING_PROMPT_RE.search(line) or _WAITING_MENU_RE.match(line):
            return "waiting"

    if sl_state in ("thinking", "working", "running", "tool_use"):
        return "working"

    for line in recent_body:
        if _SUBAGENT_ACTIVE_RE.match(line) or _SPINNER_RE.match(line) or _INTERRUPT_HINT_RE.search(line):
            return "working"

    if sl_state == "idle" or _has_prompt_box(non_empty[-6:]):
        return "idle"

    return None


def compute_status(
    pane_dead: bool,
    last_activity: int | None,
    now: int,
    captured: str = "",
) -> str:
    """Derive agent attention status from pane liveness, pane output, and activity age."""
    if pane_dead:
        return "exited"

    pane_state = _classify_pane_state(captured)
    if pane_state == "waiting":
        return "waiting"
    if pane_state == "working":
        return "working"
    if pane_state == "idle":
        if last_activity is not None and last_activity > 0:
            return f"idle ({format_age(max(0, now - last_activity))})"
        return "idle"

    if last_activity is None or last_activity <= 0:
        return "working"
    age = max(0, now - last_activity)
    if age <= ACTIVE_THRESHOLD_SECS:
        return "working"
    return f"idle ({format_age(age)})"


def row_state(status: str) -> str:
    """Normalize a WorkstreamRow status string into waiting, working, idle, or exited."""
    if status == "exited":
        return "exited"
    if status == "waiting":
        return "waiting"
    if status.startswith("idle"):
        return "idle"
    return "working"


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


def _cached_project_color(pane_path: str) -> str:
    if not pane_path or not os.path.isdir(pane_path):
        return ""
    key = (pane_path, os.environ.get("SESSION_LABEL_COLORS_FILE", ""))
    if key not in _COLOR_CACHE:
        _COLOR_CACHE[key] = resolve_project_color(pane_path)
    return _COLOR_CACHE[key]


def load_workstream_meta(pane_path: str) -> tuple[str, str, str]:
    """Return (ticket_ref, desc, tags) from <pane_path>/.workstream.json when present."""
    if not pane_path or not os.path.isdir(pane_path):
        return ("", "", "")
    rec = workstream.load_record(pane_path)
    if rec is None:
        return ("", "", "")
    ticket_ref = rec.key or ""
    if not ticket_ref and rec.tickets:
        ids = [t.get("id", "") for t in rec.tickets if t.get("id")]
        if ids:
            prefix = workstream.PROVIDER_TOKENS.get(rec.ticket_provider, {}).get("brief", "")
            ticket_ref = f"{prefix}{'+'.join(ids)}"
    return (ticket_ref, rec.desc or "", workstream.format_phase_tags(rec))


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

        ticket_ref, desc, tags = load_workstream_meta(pane_path)
        branch = "" if desc else _git_branch(pane_path)
        captured = _run_cmd([*base, "capture-pane", "-p", "-t", pane_id, "-S", "-30"])
        status = compute_status(pane_dead, last_activity, current_time, captured=captured)
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
                tags=tags,
                color=_cached_project_color(pane_path),
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
        header = f"  {'#':<3} {'Ticket':<12} {'Tags':<14} {'Status':<12} {'Mem':<9} {'Title':<28} {'Last output'}"
        lines.append(_clip(header, w))
        start, end = visible_slice(len(items), selected, max_rows, items=items)
        fixed_width = 2 + 4 + 13 + 15 + 13 + 10 + 29
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
                f"{_clip(row.tags, 14):<14} "
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


def _status_attr(status: str, base_attr: int, color_pairs: dict[str, int]) -> int:
    """Return curses attributes for the Status column based on attention state."""
    state = row_state(status)
    if state == "waiting":
        pair = color_pairs.get("yellow")
        return base_attr | curses.A_BOLD | (curses.color_pair(pair) if pair else 0)
    if state == "working":
        pair = color_pairs.get("green")
        return base_attr | (curses.color_pair(pair) if pair else 0)
    if state == "idle":
        return base_attr | curses.A_DIM
    if state == "exited":
        pair = color_pairs.get("red")
        return base_attr | (curses.color_pair(pair) if pair else 0)
    return base_attr


def _draw_row(
    stdscr: Any,
    y: int,
    text: str,
    max_width: int,
    row: WorkstreamRow | None,
    is_selected: bool,
    color_pairs: dict[str, int],
) -> None:
    """Draw one dashboard line, colorizing status by attention state and ticket/title by project."""
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

    if row is None:
        return
    limit = min(len(text), max_width)
    status_attr = _status_attr(row.status, base_attr, color_pairs)
    if 34 < limit and status_attr != base_attr:
        seg = text[34 : min(46, limit)]
        if seg:
            try:
                stdscr.addnstr(y, 34, seg, len(seg), status_attr)
            except curses.error:
                pass

    if row.color not in color_pairs:
        return
    color_attr = base_attr | curses.color_pair(color_pairs[row.color])
    for start, end in ((6, 18), (57, 85)):
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
    mem_cmd: str = "",
) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(int(refresh_sec * 1000))
    color_pairs = init_color_pairs()
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
        lines = render_lines(
            rows,
            selected,
            width - 1,
            session,
            max_rows=max_rows,
            view_mode=view_mode,
            host_line=host_line,
        )
        max_width = max(1, width - 1)
        stdscr.erase()
        for y, text in enumerate(lines[: max(1, height - 1)]):
            item_idx = start + (y - 3)
            item = (
                items[item_idx]
                if (items and 3 <= y < 3 + (end - start) and 0 <= item_idx < len(items))
                else None
            )
            if item is not None and item.is_header:
                try:
                    stdscr.addnstr(y, 0, text, max_width, curses.A_BOLD)
                except curses.error:
                    pass
                continue
            row = item.row if item is not None else None
            is_selected = bool(
                items and item is not None and not item.is_header and item_idx == selected
            )
            _draw_row(stdscr, y, text, max_width, row, is_selected, color_pairs)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1 or ch in (ord("r"), ord("R")):
            if ch in (ord("r"), ord("R")):
                _COLOR_CACHE.clear()
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
