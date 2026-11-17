#!/usr/bin/env python3
"""The deterministic /sync path: bring origin/<base> into the feature branch and push.

    sync-run.sh [--dir <worktree>] [--finish]

Exit 0   up to date (one line, nothing changed) or synced and pushed (one line).
Exit 3   hand back to the model: `handoff=<reason>`, `detail=`, `files=`, `base=`,
         `method=`. Reasons: conflict (merge state left in place), unresolved
         (--finish found unmerged paths), push-failed.
Exit 1   usage/precondition error: not a repo, detached HEAD, on the base branch,
         dirty tree or a merge already in progress, invalid `sync_method`.

`--finish` is the re-run after the model resolved a conflict: it completes the
merge (or rebase), then pushes.

Method: `sync_method` (merge|rebase) from start-ticket.conf, project or global;
default merge. Rebase pushes with --force-with-lease.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # wrapper runs -I
from repo_facts import conf_get, default_branch, git, git_ok, run_cmd

EXIT_OK, EXIT_USAGE, EXIT_HANDOFF = 0, 1, 3
METHODS = ("merge", "rebase")


def usage_error(msg: str) -> int:
    print(f"sync-run: {msg}", file=sys.stderr)
    return EXIT_USAGE


def handoff(reason: str, detail: str, base: str, method: str, files: str = "") -> int:
    print(f"handoff={reason}")
    print(f"detail={detail}")
    print(f"files={files}")
    print(f"base={base}")
    print(f"method={method}")
    return EXIT_HANDOFF


def unmerged(dir_: str) -> list[str]:
    return [l for l in git(dir_, "diff", "--name-only", "--diff-filter=U").splitlines() if l]


def in_progress(dir_: str, method: str) -> bool:
    if method == "merge":
        return git_ok(dir_, "rev-parse", "-q", "--verify", "MERGE_HEAD")
    return any(os.path.isdir(os.path.join(dir_, git(dir_, "rev-parse", "--git-path", p)))
               for p in ("rebase-merge", "rebase-apply"))


def push(dir_: str, branch: str, method: str) -> str:
    """"" on success, else the failure text."""
    cmd = ["git", "push"]
    if method == "rebase":
        cmd.append("--force-with-lease")
    if not git_ok(dir_, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"):
        cmd += ["-u", "origin", "HEAD"]
    r = run_cmd(cmd, cwd=dir_)
    if r.returncode == 0:
        return ""
    return (r.stderr.strip().splitlines() or ["git push failed"])[-1]


def finish_in_progress(dir_: str, method: str) -> str:
    """Complete the merge/rebase the model resolved; "" or the failure text."""
    if method == "merge":
        r = run_cmd(["git", "commit", "--no-edit"], cwd=dir_)
    else:
        r = run_cmd(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=dir_)
    return "" if r.returncode == 0 else (r.stderr or r.stdout).strip()


def summary(branch: str, base_ref: str, method: str, dir_: str) -> str:
    return f"Synced {branch} with {base_ref} ({method}); pushed {git(dir_, 'rev-parse', '--short', 'HEAD')}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sync-run.sh")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--finish", action="store_true")
    args = ap.parse_args(argv)
    d = args.dir
    if not git_ok(d, "rev-parse", "--show-toplevel"):
        return usage_error("not inside a git worktree")
    method = conf_get("sync_method", d) or "merge"
    if method not in METHODS:
        return usage_error(f"sync_method={method!r} is not one of {', '.join(METHODS)}")
    base = default_branch(d)
    if not base:
        return usage_error("cannot resolve the repository's default branch")
    base_ref = f"origin/{base}"
    paused = in_progress(d, method) or bool(unmerged(d))

    # A rebase in progress has a detached HEAD, so --finish reads the branch only
    # after the rebase completes.
    if args.finish:
        left = unmerged(d)
        if left:
            return handoff("unresolved", "unmerged paths remain", base_ref, method, ",".join(left))
        if in_progress(d, method):
            err = finish_in_progress(d, method)
            if err:
                return handoff("unresolved", err.splitlines()[-1], base_ref, method,
                               ",".join(unmerged(d)))
    elif paused:
        return usage_error("a merge or rebase is already in progress; resolve it, then run sync-run.sh --finish")

    branch = git(d, "symbolic-ref", "--short", "-q", "HEAD")
    if not branch:
        return usage_error("detached HEAD; check out the feature branch")
    if branch == base:
        return usage_error(f"on the base branch ({base}); run /sync from a feature worktree")

    if args.finish:
        err = push(d, branch, method)
        if err:
            return handoff("push-failed", err, base_ref, method)
        print(summary(branch, base_ref, method, d))
        return EXIT_OK

    if git(d, "status", "--porcelain"):
        return usage_error("working tree has uncommitted changes; commit or stash them first")
    if not git_ok(d, "fetch", "-q", "origin"):
        return usage_error("git fetch origin failed")
    if git_ok(d, "merge-base", "--is-ancestor", base_ref, "HEAD"):
        print(f"{branch} is up to date with {base_ref}")
        return EXIT_OK

    if method == "merge":
        r = run_cmd(["git", "merge", "--no-edit", base_ref], cwd=d)
    else:
        remote_branch = f"refs/remotes/origin/{branch}"
        if git_ok(d, "rev-parse", "-q", "--verify", remote_branch) and not git_ok(
                d, "merge-base", "--is-ancestor", remote_branch, "HEAD"):
            return handoff("push-failed", f"origin/{branch} has commits this branch lacks; "
                           "rebasing would overwrite them", base_ref, method)
        r = run_cmd(["git", "rebase", base_ref], cwd=d)
    if r.returncode != 0:
        files = unmerged(d)
        if not files:
            run_cmd(["git", "merge", "--abort"] if method == "merge" else ["git", "rebase", "--abort"],
                    cwd=d)
            return usage_error(f"git {method} {base_ref} failed: "
                               f"{((r.stderr or r.stdout).strip().splitlines() or ['unknown error'])[-1]}")
        return handoff("conflict", f"{method} of {base_ref} conflicts", base_ref, method, ",".join(files))
    err = push(d, branch, method)
    if err:
        return handoff("push-failed", err, base_ref, method)
    print(summary(branch, base_ref, method, d))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
