#!/usr/bin/env python3
"""The deterministic /merge path: sync gate, then GitHub merges the PR and the
remote branch is deleted. Local cleanup stays with /finalize.

    merge-run.sh [--dir <worktree>] [--branch <name>]

Exit 0   merged; stdout is one summary line (plus `warning=` lines).
Exit 2   stopped before or without merging: `stopped=<reason>` and `reason=`.
         Gate refusals use sync_gate's verdicts; others are merge-method-ambiguous, merge-method-unknown,
         merge-method-not-allowed, merge-failed, not-merged.
Exit 1   usage/precondition error (including an invalid `merge_method`).

Method: `merge_method` (merge|squash|rebase) from start-ticket.conf, project or
global; unset takes plain merge, else the repo's single allowed method.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # wrapper runs -I
import sync_gate as sg
from repo_facts import conf_get, git, git_ok, run_cmd

EXIT_OK, EXIT_USAGE, EXIT_STOP = 0, 1, 2
METHODS = {"merge": "mergeCommitAllowed", "squash": "squashMergeAllowed",
           "rebase": "rebaseMergeAllowed"}

STOP_REASONS = {
    "merge-method-ambiguous": "several merge methods are allowed and merge_method is unset; set it in start-ticket.conf",
    "merge-method-not-allowed": "the configured merge_method is not enabled on this repository",
    "merge-method-unknown": "could not read the repository's merge settings from GitHub; set merge_method in start-ticket.conf",
    "merge-failed": "GitHub refused the merge",
    "not-merged": "GitHub accepted the merge request but the PR is not merged (queued or auto-merge); nothing was deleted",
}


def resolve_method(configured: str | None, allowed: dict | None) -> tuple[str, str]:
    """(method, "") or ("", stop-reason). `allowed` is None when unreadable."""
    if configured:
        if allowed is not None and not allowed.get(METHODS[configured]):
            return "", "merge-method-not-allowed"
        return configured, ""
    if allowed is None:
        return "", "merge-method-unknown"
    enabled = [m for m, key in METHODS.items() if allowed.get(key)]
    if "merge" in enabled:
        return "merge", ""
    if len(enabled) == 1:
        return enabled[0], ""
    return "", "merge-method-ambiguous"


def allowed_methods(dir_: str) -> dict | None:
    r = run_cmd(["gh", "repo", "view", "--json",
                 "mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed"], cwd=dir_)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def stop(reason: str, detail: str = "") -> int:
    print(f"stopped={reason}")
    print(f"reason={detail or STOP_REASONS.get(reason, sg.REASONS.get(reason, ''))}")
    return EXIT_STOP


def pr_state(dir_: str, number: str) -> str:
    r = run_cmd(["gh", "pr", "view", number, "--json", "state"], cwd=dir_)
    try:
        return json.loads(r.stdout).get("state", "") if r.returncode == 0 else ""
    except ValueError:
        return ""


def delete_remote_branch(dir_: str, branch: str, merged_head: str) -> str:
    """"" on success (or already gone), else the failure text. Skips the delete
    when the remote branch has moved past the head that was merged."""
    ref = run_cmd(["gh", "api", f"repos/{{owner}}/{{repo}}/git/ref/heads/{branch}",
                   "--jq", ".object.sha"], cwd=dir_)
    if ref.returncode != 0:
        if "Not Found" in ref.stderr or "Reference does not exist" in ref.stderr:
            return ""
        return (ref.stderr.strip().splitlines() or ["unknown error"])[0]
    if ref.stdout.strip() != merged_head:
        return "remote branch no longer points at the merged head"
    r = run_cmd(["gh", "api", "-X", "DELETE", f"repos/{{owner}}/{{repo}}/git/refs/heads/{branch}"],
                cwd=dir_)
    if r.returncode == 0 or "Reference does not exist" in r.stderr:
        return ""
    return (r.stderr.strip().splitlines() or ["unknown error"])[0]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="merge-run.sh")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--branch", default="")
    args = ap.parse_args(argv)
    d = args.dir
    if not git_ok(d, "rev-parse", "--show-toplevel"):
        print("merge-run: not inside a git worktree", file=sys.stderr)
        return EXIT_USAGE
    head_branch = git(d, "symbolic-ref", "--short", "-q", "HEAD")
    if not head_branch:
        print("merge-run: detached HEAD; check out the PR branch", file=sys.stderr)
        return EXIT_USAGE
    branch = args.branch or head_branch
    configured = conf_get("merge_method", d)
    if configured and configured not in METHODS:
        print(f"merge-run: merge_method={configured!r} is not one of "
              f"{', '.join(METHODS)}", file=sys.stderr)
        return EXIT_USAGE

    facts = sg.gather(d, branch)
    verdict, reason = sg.choose_verdict(facts)
    if verdict != "ready":
        return stop(verdict, reason)

    method, why = resolve_method(configured, allowed_methods(d))
    if not method:
        return stop(why)

    r = run_cmd(["gh", "pr", "merge", facts.pr_number, f"--{method}",
                 "--match-head-commit", facts.pr_head], cwd=d)
    if r.returncode != 0:
        return stop("merge-failed", (r.stderr.strip().splitlines() or [STOP_REASONS["merge-failed"]])[0])
    if pr_state(d, facts.pr_number) != "MERGED":
        return stop("not-merged")

    failure = delete_remote_branch(d, branch, facts.pr_head)
    tail = "remote branch deleted" if not failure else "remote branch kept"
    print(f"Merged #{facts.pr_number} ({method}) into {facts.base}; {tail}")
    if failure:
        print(f"warning=remote-branch-not-deleted: {failure}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
