#!/usr/bin/env python3
"""Assemble a PR body from two model-written sections plus mechanical ones.

    pr_body.py assemble --base <ref> --summary-file F --judgment-file F [--test-result S] [--footer LINE]…
    pr_body.py draft save --base <ref> --summary-file F --judgment-file F
    pr_body.py draft load --base <ref> --summary-file OUT --judgment-file OUT
    pr_body.py review-write --rounds N --fixed N --dismissed N --deferred N

The model supplies Summary (<=3 one-line bullets) and Needs your judgment (<=3
items, or "none"). Risk, Review and Tests come from the diff, the review report
and the caller. State lives in the git dir: review-report.json, pr-draft.json.
Exit codes: 0 ok; 1 draft missing or stale; 2 section over its cap.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys

MAX_ITEMS = 3
DEFAULT_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pr-risk.json")
REPO_TABLE = os.path.join(".claude", "pr-risk.json")


class CapError(ValueError):
    pass


def git(root, *args):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def git_dir(root):
    return git(root, "rev-parse", "--absolute-git-dir")


def resolve_base(root, base):
    remote = f"origin/{base}"
    r = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "-q", remote],
                       capture_output=True, check=False)
    return remote if r.returncode == 0 else base


def touched_files(root, base):
    out = git(root, "diff", "--name-only", f"{resolve_base(root, base)}...HEAD")
    return sorted(out.splitlines())


def parse_bullets(text, label):
    items = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith("- "):
            raise CapError(f"{label}: each item must be a single '- ' line, one line long; got {line!r}")
        items.append(line[2:].strip())
    if len(items) > MAX_ITEMS:
        raise CapError(f"{label}: at most {MAX_ITEMS} items, got {len(items)}")
    return items


def parse_summary(text):
    items = parse_bullets(text, "Summary (one line per bullet)")
    if not items:
        raise CapError("Summary: needs 1 to 3 bullets")
    return items


def parse_judgment(text):
    if text.strip().lower() == "none":
        return []
    if not text.strip():
        raise CapError("Needs your judgment: write 'none' or up to 3 bullets")
    return parse_bullets(text, "Needs your judgment (or 'none')")


def load_table(root):
    path = os.path.join(root, REPO_TABLE) if root else ""
    if not (path and os.path.isfile(path)):
        path = DEFAULT_TABLE
    with open(path) as fh:
        return json.load(fh)


def matches(path, patterns):
    base = os.path.basename(path)
    return any(fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(base, p) for p in patterns)


def classify(paths, table):
    if any(matches(p, table.get("high", [])) for p in paths):
        return "high"
    if all(matches(p, table.get("low", [])) for p in paths):
        return "low"
    return "medium"


def fingerprint(root, base):
    head = git(root, "rev-parse", "HEAD")
    files = "\n".join(touched_files(root, base))
    return hashlib.sha256(f"{head}\n{files}".encode()).hexdigest()


def state_path(root, name):
    return os.path.join(git_dir(root), name)


def write_review(root, rounds, fixed, dismissed, deferred):
    report = {"rounds": rounds, "fixed": fixed, "dismissed": dismissed,
              "deferred": deferred, "head": git(root, "rev-parse", "HEAD")}
    with open(state_path(root, "review-report.json"), "w") as fh:
        json.dump(report, fh)


def review_section(root):
    path = state_path(root, "review-report.json")
    if not os.path.isfile(path):
        return "Not run"
    with open(path) as fh:
        r = json.load(fh)
    noun = "round" if r["rounds"] == 1 else "rounds"
    line = f"{r['rounds']} {noun}: {r['fixed']} fixed, {r['dismissed']} dismissed, {r['deferred']} deferred"
    if r.get("head") != git(root, "rev-parse", "HEAD"):
        line += " (stale: commits since the review)"
    return line


def risk_section(root, base):
    tier = classify(touched_files(root, base), load_table(root))
    stat = git(root, "diff", "--shortstat", f"{resolve_base(root, base)}...HEAD")
    return f"**{tier}**" + (f" — {stat}" if stat else "")


def render_items(items):
    return "\n".join(f"- {i}" for i in items) if items else "none"


def assemble(root, base, summary, judgment, test_result, footers=()):
    summary_items = parse_summary(summary)
    judgment_items = parse_judgment(judgment)
    sections = [
        ("Summary", render_items(summary_items)),
        ("Needs your judgment", render_items(judgment_items)),
        ("Risk", risk_section(root, base)),
        ("Review", review_section(root)),
        ("Tests", test_result or "Not reported"),
    ]
    body = "\n\n".join(f"## {name}\n{text}" for name, text in sections) + "\n"
    return body + "".join(f"\n{line}\n" for line in footers)


def save_draft(root, base, summary, judgment):
    parse_summary(summary)
    parse_judgment(judgment)
    draft = {"summary": summary, "judgment": judgment, "fingerprint": fingerprint(root, base)}
    with open(state_path(root, "pr-draft.json"), "w") as fh:
        json.dump(draft, fh)


def load_draft(root, base):
    path = state_path(root, "pr-draft.json")
    if not os.path.isfile(path):
        return None
    with open(path) as fh:
        draft = json.load(fh)
    if draft.get("fingerprint") != fingerprint(root, base):
        return None
    return draft["summary"], draft["judgment"]


def read(path):
    with open(path) as fh:
        return fh.read()


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assemble")
    a.add_argument("--base", required=True)
    a.add_argument("--summary-file", required=True)
    a.add_argument("--judgment-file", required=True)
    a.add_argument("--test-result")
    a.add_argument("--footer", action="append", default=[])
    d = sub.add_parser("draft")
    d.add_argument("action", choices=["save", "load"])
    d.add_argument("--base", required=True)
    d.add_argument("--summary-file", required=True)
    d.add_argument("--judgment-file", required=True)
    r = sub.add_parser("review-write")
    for name in ("rounds", "fixed", "dismissed", "deferred"):
        r.add_argument(f"--{name}", type=int, required=True)
    return p


def run(args, root):
    if args.cmd == "assemble":
        sys.stdout.write(assemble(root, args.base, read(args.summary_file),
                                  read(args.judgment_file), args.test_result, args.footer))
    elif args.cmd == "review-write":
        write_review(root, args.rounds, args.fixed, args.dismissed, args.deferred)
    elif args.action == "save":
        save_draft(root, args.base, read(args.summary_file), read(args.judgment_file))
    else:
        draft = load_draft(root, args.base)
        if draft is None:
            return 1
        for path, text in zip((args.summary_file, args.judgment_file), draft):
            with open(path, "w") as fh:
                fh.write(text)
    return 0


def main(argv=None):
    if sys.version_info < (3, 13):
        sys.exit("pr_body: Python 3.13+ required")
    args = build_parser().parse_args(argv)
    try:
        return run(args, os.getcwd())
    except CapError as e:
        print(f"pr_body: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"pr_body: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
