"""Pending-actions file: a markdown table of queued tracker actions, keyed (issue, action).

Rows: `| issue | action | detail | command |`. A literal `|` in a field is written `\\|`.
Lines outside the table are left untouched. Nothing here talks to the tracker.
"""

import argparse
import os
import re
import sys

HEADER = "| issue | action | detail | command |"
RULE = "| --- | --- | --- | --- |"
ROW = re.compile(r"^\|\s*(\d+)\s*\|")
SPLIT = re.compile(r"(?<!\\)\|")


def escape(s):
    return s.replace("|", r"\|")


def unescape(s):
    return s.replace(r"\|", "|")


def format_row(issue, action, detail, command):
    return f"| {issue} | {escape(action)} | {escape(detail)} | {escape(command)} |"


def parse_row(line):
    """Return (issue, action, detail, command) or None if the line isn't a data row."""
    if not ROW.match(line):
        return None
    cells = [unescape(c.strip()) for c in SPLIT.split(line.strip())[1:-1]]
    cells += [""] * (4 - len(cells))
    return tuple(cells[:4])


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return f.read().splitlines()


def upsert(path, issue, action, detail, command):
    lines = read_lines(path)
    new = format_row(issue, action, detail, command)
    last_row = None
    for i, line in enumerate(lines):
        row = parse_row(line)
        if row is None:
            continue
        last_row = i
        if row[0] == issue and row[1] == action:
            lines[i] = new
            break
    else:
        if last_row is not None:
            lines.insert(last_row + 1, new)
        else:
            if HEADER not in lines:
                lines += [HEADER, RULE]
            lines.append(new)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def rows(path):
    return [r for r in map(parse_row, read_lines(path)) if r]


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

    if not a.issue.isdigit():
        p.error(f"--issue must be a number, got {a.issue!r}")
    if a.cmd == "has":
        return 0 if any(r[0] == a.issue and r[1] == a.action for r in rows(a.file)) else 1

    for field in (a.action, a.detail, a.command):
        if "\n" in field or "\r" in field:
            p.error("fields must be single-line")
    upsert(a.file, a.issue, a.action, a.detail, a.command)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
