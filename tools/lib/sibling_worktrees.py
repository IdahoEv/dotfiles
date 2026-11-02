#!/usr/bin/env python3
"""Find worktrees in OTHER repos that belong to the same ticket (port of
sibling-worktrees.sh).

    sibling-worktrees.sh [--ticket <id>] [--branch <name>] [--root <dir>]
                         [--include-clean] [--repos <dir>[,<dir>...]]

A ticket is often implemented across several repos at once; each repo gets
its own worktree on a branch carrying the same ticket id. This locates the
sibling worktrees so /open-pr can fan a session out to each of them instead
of shipping only the repo it happens to be standing in. Pure local
inspection: no changes, no network, safe to run speculatively on every ship.

Stdout is one TAB-separated record per match: <repo>\\t<worktree-path>\\t
<branch>\\t<state>, state one of dirty, ahead, dirty+ahead, clean. Clean
worktrees (nothing to ship) are omitted unless --include-clean. Exit 0 with
empty output when nothing matches; 1 only on usage/precondition errors.
"""

from __future__ import annotations

import locale
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # wrapper runs -I
import repo_facts

HELP = """# sibling-worktrees.sh — find worktrees in OTHER repos that belong to the same ticket.
#
#   sibling-worktrees.sh [--ticket <id>] [--branch <name>] [--root <dir>]
#                        [--include-clean] [--repos <dir>[,<dir>...]]
#
# A ticket is often implemented across several repos at once (an API change in
# one, the shared schema package in another). Each repo gets its own worktree
# from `worktree-manager.sh`, on a branch carrying the same ticket id. This
# script locates those sibling worktrees so a caller — `/open-pr` — can fan a
# session out to each of them instead of shipping only the repo it happens to
# be standing in.
#
# It makes no changes and talks to no network: pure local inspection, safe to
# run speculatively on every ship.
#
# Ticket id is taken from --ticket, else parsed from --branch, else from the
# current branch, using the two conventions these tools create:
#   <id>-<slug>              GitHub issues  (worktree-manager default)
#   [<prefix>/]sc-<id>/<slug>  Shortcut     (worktree-manager --sc)
# The LAST sc-<id> in a branch wins (a follow-up branch can name several),
# matching open-pr-providers' issue_from_branch.
#
# Repos searched: every immediate subdirectory of <root> that is a git repo,
# excluding the one we're standing in. <root> defaults to the grandparent of
# the current worktree (…/Development/<repo>/<worktree> → …/Development), which
# is the layout `worktree-manager.sh --init` produces. --repos bypasses the
# scan entirely and inspects exactly the directories given.
#
# Output (stdout, one TAB-separated record per match, parseable):
#   <repo>\\t<worktree-path>\\t<branch>\\t<state>
# where <state> is one of dirty, ahead, dirty+ahead, clean. `clean` worktrees
# (nothing uncommitted, nothing beyond the base branch) are omitted unless
# --include-clean: they have nothing to ship.
#
# Exit codes: 0 matches found (or none — an empty list is not an error);
#             1 usage/precondition error.

"""


# ---- subprocess helpers ------------------------------------------------------

def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    # surrogateescape: git emits raw bytes (ref names, config values) and the
    # shell passed them through; a strict decode would crash instead.
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          errors="surrogateescape", check=False)


def _git(dir_: str, *args: str) -> str:
    """git -C stdout, or "" when the command fails (the shell's `|| true`)."""
    r = _run(["git", "-C", dir_, *args])
    return r.stdout.strip() if r.returncode == 0 else ""


def _git_ok(dir_: str, *args: str) -> bool:
    return _run(["git", "-C", dir_, *args]).returncode == 0


def _collated(names: list[str]) -> list[str]:
    """Glob order: bash sorted each expansion with the caller's strcoll, and
    the listing order is part of the byte-identical output."""
    try:
        prev = locale.setlocale(locale.LC_COLLATE, "")
        try:
            return sorted(names, key=locale.strxfrm)
        finally:
            locale.setlocale(locale.LC_COLLATE, prev)
    except locale.Error:
        return sorted(names)


def _common_dir(repo: str) -> str:
    """The repo's common git dir, resolved like cd -P from <repo>; "" when
    <repo> is not a git repo (the caller skips it)."""
    common = _git(repo, "rev-parse", "--git-common-dir")
    if not common:
        return ""
    p = common if common.startswith("/") else os.path.join(repo, common)
    real = os.path.realpath(p)
    return real if os.path.isdir(real) else ""


# ---- ticket and candidates ---------------------------------------------------

def resolve_ticket(ticket: str, branch: str, cwd: str) -> str:
    """--ticket, else parsed from --branch, else from the current branch,
    using the two conventions the tools create (<id>-<slug> GitHub,
    [<prefix>/]sc-<id>/<slug> Shortcut). The LAST sc-<id> wins — a follow-up
    branch can name several."""
    if not ticket:
        if not branch:
            branch = _git(cwd, "branch", "--show-current")
        if not branch:
            _die("not on a branch (detached HEAD) — pass --ticket")
        ticket = repo_facts.ticket_from_branch(branch)
    if not ticket:
        _die(f"can't parse a ticket id from branch '{branch or '?'}' — pass --ticket")
    if not re.fullmatch(r"[1-9][0-9]*", ticket):
        _die(f"ticket id must be a positive integer (got '{ticket}')")
    return ticket


def candidate_repos(repos_csv: str, root: str, cwd: str) -> list[str]:
    """Explicit --repos list, else every immediate subdirectory of <root>.

    A --repos entry may be a repo family dir OR a worktree inside one; git
    resolves either to the same common dir, so both work (the record's repo
    name is the basename of the entry). <root> defaults to the grandparent of
    the current worktree (…/Development/<repo>/<worktree> → …/Development),
    the layout worktree-manager.sh --init produces."""
    if repos_csv:
        out = []
        for d in repos_csv.split(","):
            if not d:
                continue
            if not os.path.isdir(d):
                _die(f"--repos entry is not a directory: {d}")
            out.append(d)
        return out
    if not root:
        toplevel = _git(cwd, "rev-parse", "--show-toplevel")
        root = os.path.dirname(os.path.dirname(toplevel))
    if not os.path.isdir(root):
        _die(f"root is not a directory: {root}")
    return _collated([os.path.join(root, n) for n in os.listdir(root)
                      if os.path.isdir(os.path.join(root, n))])


# ---- per-worktree state ------------------------------------------------------

def worktree_state(wt: str) -> str:
    """dirty | ahead | dirty+ahead | clean.

    `ahead` counts commits beyond origin/<base>. The base ref can be stale
    (notably when remote.origin.fetch is unset), but staleness only ever
    OVER-reports work — a worktree wrongly shown as ahead costs a
    confirmation, never a silently skipped repo. Erring that direction is
    deliberate. No base at all is treated as having work rather than
    hiding it, for the same reason."""
    dirty = bool(_git(wt, "status", "--porcelain"))
    base = repo_facts.default_branch_ref(wt)
    if base:
        n = _git(wt, "rev-list", "--count", f"{base}..HEAD")
        ahead = n.isdigit() and int(n) > 0
    else:
        ahead = True
    if dirty and ahead:
        return "dirty+ahead"
    if dirty:
        return "dirty"
    if ahead:
        return "ahead"
    return "clean"


def scan(candidates: list[str], ticket: str, self_common: str,
         include_clean: bool) -> list[str]:
    """TAB records for every worktree on a branch carrying <ticket>, in
    candidate order then worktree-list order. The repo we're shipping from
    is excluded by common dir."""
    records: list[str] = []
    for repo in candidates:
        common = _common_dir(repo)
        if not common or common == self_common:
            continue
        name = os.path.basename(repo.rstrip(os.sep))
        # worktree list --porcelain emits stanzas of "worktree <path>" /
        # "HEAD <oid>" / "branch refs/heads/<name>" (or "detached"),
        # blank-line separated; a synthetic trailing blank closes the last.
        wt = br = ""
        for line in _git(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
            if line.startswith("worktree "):
                wt = line[len("worktree "):]
                br = ""
            elif line.startswith("branch "):
                br = line[len("branch "):].removeprefix("refs/heads/")
            elif line == "":
                if wt and br and repo_facts.ticket_from_branch(br) == ticket:
                    state = worktree_state(wt)
                    if include_clean or state != "clean":
                        records.append(f"{name}\t{wt}\t{br}\t{state}")
                wt = br = ""
    return records


# ---- CLI ------------------------------------------------------------------------

def _die(msg: str) -> None:
    print(f"sibling-worktrees: {msg}", file=sys.stderr)
    sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 13):
        sys.exit("sibling_worktrees: Python 3.13+ required; "
                 "install with: pyenv install 3.13")
    if argv is None:
        argv = sys.argv[1:]
    ticket = branch = root = repos_csv = ""
    include_clean = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            sys.stdout.write(HELP)
            return 0
        if arg == "--include-clean":
            include_clean = True
            i += 1
        elif arg in ("--ticket", "--branch", "--root", "--repos"):
            if i + 1 >= len(argv):
                _die(f"{arg} needs a value")
            if arg == "--ticket":
                ticket = argv[i + 1]
            elif arg == "--branch":
                branch = argv[i + 1]
            elif arg == "--root":
                root = argv[i + 1]
            else:
                repos_csv = argv[i + 1]
            i += 2
        else:
            _die(f"unknown arg: {arg}")
    cwd = os.getcwd()
    if not _git_ok(cwd, "rev-parse", "--is-inside-work-tree"):
        _die("not inside a git repo")
    ticket = resolve_ticket(ticket, branch, cwd)
    self_common = _common_dir(cwd)
    records = scan(candidate_repos(repos_csv, root, cwd), ticket,
                   self_common, include_clean)
    # Branch names may carry non-UTF-8 bytes from git (surrogateescape in
    # _git); stdout must pass them back through as bytes, as printf did.
    sys.stdout.reconfigure(errors="surrogateescape")
    for record in records:
        sys.stdout.write(f"{record}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
