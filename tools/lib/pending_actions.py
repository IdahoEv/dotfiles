"""Pending-actions file: a markdown table of queued tracker actions, keyed (issue, action).

Rows: `| issue | action | detail | command |`. A literal `|` in a field is written `\\|`.
Only rows under HEADER are read or replaced; other lines are left untouched. Nothing here talks to the tracker.
"""

import argparse
import fcntl
import os
import re
import sys
import tempfile

HEADER = "| issue | action | detail | command |"
RULE = "| --- | --- | --- | --- |"
ROW = re.compile(r"^\|\s*([0-9]+)\s*\|")


def escape(s):
    return s.replace("\\", "\\\\").replace("|", r"\|")


def split_cells(line):
    cells, cur, i = [], "", 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur += line[i : i + 2]
            i += 2
            continue
        if c == "|":
            cells.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    cells.append(cur)
    return cells


def unescape(s):
    return re.sub(r"\\(.)", r"\1", s)


def format_row(issue, action, detail, command):
    return f"| {issue} | {escape(action)} | {escape(detail)} | {escape(command)} |"


def parse_row(line):
    """Return (issue, action, detail, command) or None if the line isn't a data row."""
    if not ROW.match(line):
        return None
    cells = [unescape(c.strip()) for c in split_cells(line.strip())[1:-1]]
    cells += [""] * (4 - len(cells))
    return tuple(cells[:4])


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        text = f.read()
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")


def table_span(lines):
    """Return (start, end) of the data rows under HEADER, or None if the table is absent."""
    if HEADER not in lines:
        return None
    start = lines.index(HEADER) + 1
    if start < len(lines) and lines[start] == RULE:
        start += 1
    end = start
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return start, end


def upsert(path, issue, action, detail, command):
    path = os.path.realpath(path)
    directory = os.path.dirname(path)
    # Lock the directory: the file itself is replaced, so a lock on it would not survive the swap.
    lock = os.open(directory, os.O_RDONLY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _upsert_locked(path, directory, issue, action, detail, command)
    finally:
        os.close(lock)


def _upsert_locked(path, directory, issue, action, detail, command):
    lines = read_lines(path)
    new = format_row(issue, action, detail, command)
    span = table_span(lines)
    if span is None:
        lines += [HEADER, RULE, new]
    else:
        start, end = span
        for i in range(start, end):
            row = parse_row(lines[i])
            if row and row[0] == issue and row[1] == action:
                lines[i] = new
                break
        else:
            lines.insert(end, new)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".pending-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def rows(path):
    lines = read_lines(path)
    span = table_span(lines)
    if span is None:
        return []
    return [r for r in map(parse_row, lines[span[0] : span[1]]) if r]


def main(argv):
    p = argparse.ArgumentParser(prog="pending-actions.sh")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("upsert", "has", "list"):
        s = sub.add_parser(name)
        s.add_argument("file")
        if name != "list":
            s.add_argument("--issue", required=True)
            s.add_argument("--action", required=True)
        if name == "upsert":
            s.add_argument("--detail", required=True)
            s.add_argument("--command", default="")
    a = p.parse_args(argv)

    if a.cmd == "list":
        for r in rows(a.file):
            print("\t".join(r))
        return 0

    if not re.fullmatch(r"[0-9]+", a.issue):
        p.error(f"--issue must be a number, got {a.issue!r}")
    a.issue = str(int(a.issue))
    if a.cmd == "has":
        return 0 if any(r[0] == a.issue and r[1] == a.action for r in rows(a.file)) else 1

    for field in (a.action, a.detail, a.command):
        if any(c in field for c in "\n\r\t"):
            p.error("fields must be single-line and tab-free")
    upsert(a.file, a.issue, a.action, a.detail, a.command)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
