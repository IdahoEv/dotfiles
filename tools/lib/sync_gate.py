#!/usr/bin/env python3
"""The local-sync gate: is this worktree exactly what the PR would merge?

    sync-gate.sh [--dir <worktree>] [--branch <name>]

Read-only. stdout is `verdict=`, `reason=` (one line) and the facts behind it.
Exit 0   verdict=ready.
Exit 2   a refusal; stdout names which one (see REASONS).
Exit 1   usage/precondition error (not a repo, detached HEAD).

`/merge` runs this before merging; importable (`gather`, `choose_verdict`) so a
statusline indicator can share the same ladder.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # wrapper runs -I
from repo_facts import git, git_ok, run_cmd

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2
MERGEABLE_TRIES = 4

REASONS = {
    "ready": "working tree clean, HEAD equals the PR head, PR open and mergeable",
    "dirty": "working tree has uncommitted changes",
    "unknown": "could not read the PR from GitHub",
    "no-pr": "no pull request exists for this branch",
    "already-merged": "the PR is already merged",
    "closed": "the PR is closed without merging",
    "draft": "the PR is a draft; mark it ready for review first",
    "unpushed": "local commits are not on the PR; push them first",
    "behind-pr": "the PR has commits this checkout lacks; pull them first",
    "diverged": "local HEAD and the PR head have diverged; reconcile them first",
    "conflict": "the PR conflicts with its base; run /sync",
    "mergeable-unknown": "GitHub has not computed mergeability yet; retry shortly",
}


@dataclass
class Facts:
    dirty: list[str] = field(default_factory=list)
    head: str = ""
    pr_found: bool = False
    gh_ok: bool = True
    pr_number: str = ""
    pr_state: str = ""
    is_draft: bool = False
    mergeable: str = ""
    pr_head: str = ""
    head_vs_pr: str = ""   # equal | ahead | behind | diverged
    base: str = ""


def choose_verdict(f: Facts) -> tuple[str, str]:
    """First failing check wins; local state is judged before the PR's."""
    if f.dirty:
        v = "dirty"
    elif not f.gh_ok:
        v = "unknown"
    elif not f.pr_found:
        v = "no-pr"
    elif f.pr_state == "MERGED":
        v = "already-merged"
    elif f.pr_state != "OPEN":
        v = "closed"
    elif f.is_draft:
        v = "draft"
    elif f.head_vs_pr == "ahead":
        v = "unpushed"
    elif f.head_vs_pr == "behind":
        v = "behind-pr"
    elif f.head_vs_pr == "diverged":
        v = "diverged"
    elif f.mergeable == "CONFLICTING":
        v = "conflict"
    elif f.mergeable != "MERGEABLE":
        v = "mergeable-unknown"
    else:
        v = "ready"
    return v, REASONS[v]


def _relation(dir_: str, head: str, pr_head: str) -> str:
    if head == pr_head:
        return "equal"
    if not git_ok(dir_, "cat-file", "-e", f"{pr_head}^{{commit}}"):
        return "behind"
    if git_ok(dir_, "merge-base", "--is-ancestor", pr_head, head):
        return "ahead"
    if git_ok(dir_, "merge-base", "--is-ancestor", head, pr_head):
        return "behind"
    return "diverged"


def _view(dir_: str, branch: str) -> tuple[str, dict]:
    """("ok", data) | ("none", {}) | ("error", {}); retries while mergeable is UNKNOWN."""
    delay = float(os.environ.get("SYNC_GATE_RETRY_DELAY", "2"))
    data: dict = {}
    for attempt in range(MERGEABLE_TRIES):
        try:
            r = run_cmd(["gh", "pr", "view", branch, "--json",
                         "number,state,isDraft,mergeable,headRefOid,baseRefName"], cwd=dir_)
        except OSError:
            return "error", {}
        if r.returncode != 0:
            if "no pull requests found" in r.stderr:
                return "none", {}
            return "error", {}
        try:
            data = json.loads(r.stdout)
        except ValueError:
            return "error", {}
        if data.get("mergeable") != "UNKNOWN" or data.get("state") != "OPEN":
            break
        if attempt < MERGEABLE_TRIES - 1:
            time.sleep(delay)
    return "ok", data


def gather(dir_: str, branch: str) -> Facts:
    f = Facts(head=git(dir_, "rev-parse", "HEAD"))
    f.dirty = [l for l in git(dir_, "status", "--porcelain").splitlines() if l]
    if f.dirty:
        return f
    status, data = _view(dir_, branch)
    f.gh_ok = status != "error"
    f.pr_found = status == "ok"
    if status != "ok":
        return f
    f.pr_number = str(data.get("number", ""))
    f.pr_state = data.get("state", "")
    f.is_draft = bool(data.get("isDraft"))
    f.mergeable = data.get("mergeable", "")
    f.pr_head = data.get("headRefOid", "")
    f.base = data.get("baseRefName", "")
    f.head_vs_pr = _relation(dir_, f.head, f.pr_head)
    return f


def render(f: Facts, verdict: str, reason: str) -> str:
    lines = [f"verdict={verdict}", f"reason={reason}", f"pr_number={f.pr_number}",
             f"pr_state={f.pr_state}", f"pr_head={f.pr_head}", f"head={f.head}",
             f"base={f.base}", f"mergeable={f.mergeable}"]
    lines += [f"dirty={l}" for l in f.dirty]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sync-gate.sh")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--branch", default="")
    args = ap.parse_args(argv)
    if not git_ok(args.dir, "rev-parse", "--show-toplevel"):
        print("sync-gate: not inside a git worktree", file=sys.stderr)
        return EXIT_USAGE
    branch = args.branch or git(args.dir, "symbolic-ref", "--short", "-q", "HEAD")
    if not branch:
        print("sync-gate: detached HEAD; check out the PR branch", file=sys.stderr)
        return EXIT_USAGE
    facts = gather(args.dir, branch)
    verdict, reason = choose_verdict(facts)
    print(render(facts, verdict, reason))
    return EXIT_OK if verdict == "ready" else EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
