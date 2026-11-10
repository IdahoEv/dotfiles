#!/usr/bin/env python3
"""The deterministic /finalize path: verdict gate, phase stamps, GitHub ticket
close, base pull, dotfiles deploy, worktree + branch removal, session disposal.

    finalize-run.sh [--branch <name>] [--dir <worktree>] [--ticket-closed]

Exit 0   finished; stdout is one summary line (plus a reload table in the
         dotfiles repo). Nothing else for the caller to do.
Exit 2   stopped; nothing was touched. stdout: `stopped=<verdict>`.
Exit 3   hand back to the model; stdout: `handoff=<reason>`, `detail=`,
         `done=` (steps already complete) and the finalize-check facts.
         Reasons: shortcut, squash-merged, unknown, no-base-worktree,
         ticket-unreadable, unclaimed-ticket, needs-pull, dirty, locked,
         remove-failed.
Exit 1   usage/precondition error.

`--ticket-closed` is the re-run after the model closed a Shortcut ticket.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # wrapper runs -I
import finalize_check as fc
import prune_worktrees as pw
from repo_facts import git, git_ok, run_cmd

TOOLS_DIR = fc.TOOLS_DIR
EXIT_OK, EXIT_USAGE, EXIT_STOP, EXIT_HANDOFF = 0, 1, 2, 3

STOP_VERDICTS = {"no-pr", "not-merged", "local-commits", "not-on-base"}
HANDOFF_VERDICTS = {"squash-merged", "unknown"}


class Handoff(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


# ---- reload table (pure) -------------------------------------------------------

def reload_action(path: str) -> str:
    if fnmatch.fnmatch(path, "dot_claude/CLAUDE.md*"):
        return "restart sessions"
    if (fnmatch.fnmatch(path, "dot_claude/skills/*")
            or fnmatch.fnmatch(path, "dot_claude/commands/*")
            or fnmatch.fnmatch(path, "dot_claude/agents/*")
            or fnmatch.fnmatch(path, "dot_claude/hooks/*")
            or fnmatch.fnmatch(path, "dot_claude/*settings*")):
        return "/reload-skills"
    if path.startswith("dot_claude/"):
        return "unmapped, no action"
    if path.startswith("tools/"):
        return "new shells pick it up"
    if path.startswith("dot_") or path.endswith(".tmpl"):
        return "restart shells"
    return "unmapped, no action"


def reload_table(files: list[str]) -> list[str]:
    return [f"  {p} → {reload_action(p)}" for p in files if p]


# ---- helpers ---------------------------------------------------------------------

def stamp_phase(phase: str) -> None:
    run_cmd([os.path.join(TOOLS_DIR, "agent-phase.sh"), phase])


def emit(f: fc.Facts, dir_: str, outcome: str, reason: str = "") -> None:
    # An event's run comes from the checkout's branch; once the checkout is
    # gone, read the repo from the base worktree and name the ticket outright.
    target, extra, cwd = dir_, [], None
    if not os.path.isdir(dir_) and f.base_worktree:
        target, cwd = f.base_worktree, f.base_worktree
        if f.ticket_id:
            extra = [f"ticket={f.ticket_id}", f"scheme={f.ticket_scheme}"]
    try:
        run_cmd([os.path.join(TOOLS_DIR, "wf-event.sh"), "--dir", target, "finalize.run",
                 f"outcome={outcome}", f"reason={reason}", *extra], cwd=cwd)
    except OSError:
        pass


def ticket_ref(f: fc.Facts, ticket: str) -> str:
    return f"sc-{ticket}" if f.ticket_scheme == "shortcut" else f"#{ticket}"


def claims_ticket(pr_body: str, ticket: str) -> bool:
    return bool(re.search(rf"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#{ticket}\b",
                          pr_body))


def close_github_tickets(f: fc.Facts, closed: list[str]) -> None:
    """Close every id in chain_ids the PR claimed, appending "#id closed" to
    `closed` as each lands so a mid-chain Handoff can still report them.
    Raises Handoff when state can't be read or a still-open ticket was never
    claimed by the PR (a draft PR from a stopped chain: unfinished, not ours
    to close)."""
    body = None
    for tid in filter(None, f.chain_ids.split(",")):
        r = run_cmd(["gh", "issue", "view", tid, "--json", "state"], cwd=f.worktree)
        if r.returncode != 0 or '"state"' not in r.stdout:
            raise Handoff("ticket-unreadable", f"gh issue view {tid} failed")
        if '"OPEN"' not in r.stdout:
            continue
        if body is None:
            pr = run_cmd(["gh", "pr", "view", f.pr_number, "--json", "body",
                          "--jq", ".body"], cwd=f.worktree)
            if pr.returncode != 0:
                raise Handoff("ticket-unreadable", f"gh pr view {f.pr_number} failed")
            body = pr.stdout
        if not claims_ticket(body, tid):
            raise Handoff("unclaimed-ticket",
                          f"#{tid} is open and PR #{f.pr_number} does not close it")
        c = run_cmd(["gh", "issue", "close", tid, "--comment",
                     f"Landed in {f.pr_merge_commit} (PR #{f.pr_number})."],
                    cwd=f.worktree)
        if c.returncode != 0:
            raise Handoff("ticket-unreadable", f"gh issue close {tid} failed")
        closed.append(f"#{tid} closed")


def pull_base(f: fc.Facts) -> str:
    r = run_cmd(["git", "-C", f.base_worktree, "pull", "--ff-only"])
    return "pulled" if r.returncode == 0 else "needs-pull"


def deploy(f: fc.Facts) -> tuple[str, list[str]]:
    """(status, changed files) for the dotfiles deploy clone; status is
    'updated' | 'up to date' | 'skipped — <reason>'."""
    if not f.deploy_root:
        return "skipped — no deploy clone", []
    if f.deploy_branch != "main":
        return f"skipped — deploy clone is on '{f.deploy_branch}'", []
    if f.deploy_dirty_files not in ("", "0"):
        return "skipped — deploy clone has local changes", []
    if f.deploy_pull_rebase != "true":
        return (f"skipped — pull.rebase is false "
                f"(git -C {f.deploy_root} config pull.rebase true)"), []
    before = git(f.deploy_root, "rev-parse", "HEAD")
    r = run_cmd(["chezmoi", "-S", f.deploy_root, "update"])
    if r.returncode != 0:
        return "skipped — chezmoi update failed", []
    after = git(f.deploy_root, "rev-parse", "HEAD")
    if before == after:
        return "up to date", []
    files = git(f.deploy_root, "diff", "--name-only", f"{before}..{after}").splitlines()
    return "updated", files


def is_locked(base: str, path: str) -> bool:
    for w in pw.list_worktrees(base):
        if os.path.realpath(w.path) == os.path.realpath(path):
            return w.locked
    return False


def own_session(worktree: str) -> bool:
    cwd = os.path.realpath(os.getcwd())
    wt = os.path.realpath(worktree)
    return bool(os.environ.get("CLAUDE_JOB_DIR")) and (cwd == wt or cwd.startswith(wt + os.sep))


def dispose_session(base: str, branch: str, tip: str, delete_branch_after: bool) -> None:
    """Detached `claude rm`, so it runs once this process (and the Bash call
    that launched it) has returned. For a locked agent-view worktree this is
    also the removal; `claude rm` keeps the branch, so it's deleted after."""
    job_id = os.path.basename(os.environ["CLAUDE_JOB_DIR"].rstrip("/"))
    script = 'sleep "$1"; claude rm "$2" >/dev/null 2>&1'
    if delete_branch_after:
        script += (' && git -C "$3" update-ref -d "refs/heads/$4" "$5"'
                   ' && git -C "$3" config --remove-section "branch.$4"')
    subprocess.Popen(
        ["sh", "-c", script, "sh", os.environ.get("FINALIZE_DISPOSE_DELAY", "2"),
         job_id, base, branch, tip],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)


def remove_checkout(f: fc.Facts) -> str:
    """Remove worktree and branch; returns a summary fragment. Raises Handoff
    for dirty/locked/failed so the model decides."""
    dirty = git(f.worktree, "status", "--porcelain")
    if dirty:
        raise Handoff("dirty", dirty)
    in_session = own_session(f.worktree)
    if is_locked(f.base_worktree, f.worktree):
        if not in_session:
            raise Handoff("locked", f"{f.worktree} is locked by an agent-view session")
        stamp_phase("DONE")
        dispose_session(f.base_worktree, f.branch, f.head_oid, delete_branch_after=True)
        return "worktree and branch removal scheduled with session disposal"
    r = run_cmd(["git", "-C", f.base_worktree, "worktree", "remove", f.worktree])
    if r.returncode != 0:
        raise Handoff("remove-failed", r.stderr.strip())
    state, detail = pw.delete_branch(f.base_worktree, f.branch, f.head_oid, force=True)
    if state != "deleted":
        raise Handoff("remove-failed", f"worktree removed; branch {state}: {detail}")
    if in_session:
        stamp_phase("DONE")
        dispose_session(f.base_worktree, f.branch, f.head_oid, delete_branch_after=False)
    return "worktree removed, branch deleted"


# ---- flow -------------------------------------------------------------------------

def print_facts(f: fc.Facts) -> None:
    sys.stdout.write(fc.render(f))


def hand_off(f: fc.Facts, dir_: str, reason: str, detail: str, done: list[str]) -> int:
    print(f"handoff={reason}")
    print(f"detail={detail.replace(chr(10), '; ')}")
    print(f"done={','.join(done)}")
    print_facts(f)
    emit(f, dir_, "handoff", reason)
    return EXIT_HANDOFF


def run(dir_: str, branch: str, ticket_closed: bool) -> int:
    f = fc.collect_facts(branch, dir_)
    fc.emit_telemetry(dir_, f)
    if f.agent_phase:
        stamp_phase(f.agent_phase)
    if f.verdict in STOP_VERDICTS:
        print(f"stopped={f.verdict}")
        print_facts(f)
        emit(f, dir_, "stopped", f.verdict)
        return EXIT_STOP
    if f.verdict != "ready":
        return hand_off(f, dir_, f.verdict, "merge not proven", [])
    if not f.base_worktree:
        return hand_off(f, dir_, "no-base-worktree", "base branch has no worktree", [])

    done: list[str] = []
    parts: list[str] = []
    try:
        if f.ticket_scheme == "shortcut":
            if not ticket_closed:
                raise Handoff("shortcut", f"close sc-{f.ticket_id} via the Shortcut MCP tools")
            if f.ticket_id:
                parts.append("ticket closed")
        elif f.ticket_scheme == "github" and f.ticket_id:
            # Runs even with --ticket-closed: already-closed issues are skipped,
            # so the flag can't leave a still-open GitHub ticket behind.
            parts.append("ticket closed")
            closed: list[str] = []
            try:
                close_github_tickets(f, closed)
            finally:
                done.extend(closed)
            done.append("ticket")
        elif ticket_closed and f.ticket_id:
            parts.append("ticket closed")

        if pull_base(f) != "pulled":
            raise Handoff("needs-pull",
                          f"`git -C {f.base_worktree} pull --ff-only` failed; {f.base} is behind")
        parts.append(f"{f.base} pulled")
        done.append("pull")

        table: list[str] = []
        if f.dotfiles_repo == "dev":
            status, files = deploy(f)
            parts.append(f"deploy clone {status}")
            table = reload_table(files)
            done.append("deploy")

        parts.append(remove_checkout(f))
    except Handoff as h:
        return hand_off(f, dir_, h.reason, h.detail, done)

    stamp_phase("DONE")
    print(f"Finalized {ticket_ref(f, f.ticket_id) if f.ticket_id else f.branch} "
          f"(PR #{f.pr_number}, merged as {f.pr_merge_commit[:7]}): {', '.join(parts)}")
    for line in table:
        print(line)
    emit(f, dir_, "ok")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 13):
        sys.exit("finalize_run: Python 3.13+ required; install with: pyenv install 3.13")
    argv = sys.argv[1:] if argv is None else argv
    branch, dir_, ticket_closed = "", ".", False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            sys.stdout.write(__doc__)
            return EXIT_OK
        if arg == "--ticket-closed":
            ticket_closed, i = True, i + 1
        elif arg in ("--branch", "--dir") and i + 1 < len(argv) and argv[i + 1]:
            if arg == "--branch":
                branch = argv[i + 1]
            else:
                dir_ = argv[i + 1]
            i += 2
        else:
            print(f"finalize-run: bad arg: {arg}", file=sys.stderr)
            return EXIT_USAGE
    if not git_ok(dir_, "rev-parse", "--is-inside-work-tree"):
        print(f"finalize-run: not inside a git repo: {dir_}", file=sys.stderr)
        return EXIT_USAGE
    current = git(dir_, "branch", "--show-current")
    branch = branch or current
    if not branch:
        print("finalize-run: not on a branch (detached HEAD) — pass --branch", file=sys.stderr)
        return EXIT_USAGE
    # The worktree is removed along with the branch, so --dir must be that branch's checkout.
    if current != branch and (
            current or git(dir_, "rev-parse", "HEAD") != git(dir_, "rev-parse", f"refs/heads/{branch}")):
        print(f"finalize-run: {dir_} is not the checkout of '{branch}'", file=sys.stderr)
        return EXIT_USAGE
    return run(dir_, branch, ticket_closed)


if __name__ == "__main__":
    sys.exit(main())
