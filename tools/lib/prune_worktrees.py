#!/usr/bin/env python3
"""Find and remove stale worktrees and merged local branches.

    prune-worktrees.sh [--repo <dir>] [--yes] [--delete-remote] [--force-delete]

A worktree is stale when its branch's PR is verified MERGED (via the same
verdict ladder /finalize uses), the tree is clean, and nothing is unpushed.
Everything else is reported with the reason it was kept, never removed.
Default is a dry run; --yes performs the removal.

classify() is pure; remove_candidate() is the one place that deletes, so a
single-ticket finalize can import it instead of re-implementing removal.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # wrapper runs -I
import finalize_check as fc
import repo_facts
from repo_facts import git as _git, git_ok as _git_ok, run_cmd as _run

HELP = """prune-worktrees.sh — find and remove stale worktrees and merged local branches.

  prune-worktrees.sh [--repo <dir>] [--yes] [--delete-remote] [--force-delete]

A worktree/branch is removable only when ALL hold:
  - its PR is MERGED and the work landed on the PR's base (merge-commit,
    squash and rebase merges all count; git ancestry alone does not, so a
    fresh branch with no PR is never removed)
  - the working tree is clean and no commit is unpushed or beyond the PR head
  - no Claude session (`claude agents --json`) is running in it
  - it is not locked, detached, the primary worktree, the base branch's
    worktree, or the chezmoi deploy clone
Anything else is listed under SKIP with the reason. If the session list cannot
be read, every worktree is skipped. Merged local branches that have no
worktree are listed and removed the same way.

Default is a DRY RUN: nothing changes. With --yes each candidate is re-checked,
then `git worktree remove` (never --force) and `git branch -d` run.

`git branch -d` only accepts a branch that is contained in its upstream
(origin/<branch>) or, with no upstream, in HEAD. A squash/rebase-merged
branch, or any branch whose remote copy was auto-deleted before the local main
caught up, is refused even though the PR proof holds. By default such a branch
is kept (its worktree is still removed) and the exact `git branch -D <b>`
command is printed. With --force-delete, or `prune_force_delete=true` in
start-ticket.conf (per project or global), the branch is deleted instead via
`git update-ref -d refs/heads/<b> <verified-tip>`, which fails if the tip moved
since the PR proof. Use it only for projects whose PRs are squash/rebase
merged, or where you accept deleting on the PR's word alone.

Remote branches are listed; they are deleted (`git push origin --delete`) only
with --delete-remote together with --yes.

Options:
  --repo <dir>       any worktree of the repo (default: current directory)
  --yes              perform the removals (default: dry run)
  --delete-remote    also delete origin/<branch> for removed branches
  --force-delete     delete branches `git branch -d` refuses, after PR proof
                     (default from prune_force_delete=true in start-ticket.conf)
  -h, --help

Exit codes: 0 report produced (or removals done); 1 usage error or a removal
failed.
"""

SKIP_REASONS = {
    "no-pr": "no PR found for this branch",
    "not-merged": "PR not merged (or another PR for the branch is open)",
    "local-commits": "unpushed: commits beyond the PR head",
    "not-on-base": "PR merge commit is not on the base branch",
    "squash-merged": "PR merged but landing could not be proven",
    "unknown": "merge state could not be determined",
}


# ---- model ---------------------------------------------------------------------

@dataclasses.dataclass
class Worktree:
    path: str
    branch: str = ""
    bare: bool = False
    detached: bool = False
    locked: bool = False
    prunable: bool = False
    primary: bool = False


@dataclasses.dataclass
class Candidate:
    path: str  # "" for a branch with no worktree
    branch: str
    protected: str = ""  # reason this must never be touched, or ""
    session: str = "none"  # active | none | unknown
    locked: bool = False
    detached: bool = False
    dirty: bool = False
    ahead_of_upstream: int = 0
    verdict: str = "unknown"
    how: str = ""  # how the merge was proven, for the report
    pr_number: str = ""
    tip: str = ""  # local branch tip the merge proof was computed for
    remote_exists: bool | None = False  # None: lookup failed, state unknown


@dataclasses.dataclass
class Context:
    repo: str
    base_branch: str
    session_dirs: list[str] | None
    cwd: str = ""


# ---- pure core -------------------------------------------------------------------

def parse_worktrees(porcelain: str) -> list[Worktree]:
    """Stanzas of `git worktree list --porcelain`; the first non-bare is the
    primary (a `wm --init` container lists its bare stanza first)."""
    out: list[Worktree] = []
    cur: Worktree | None = None
    for line in porcelain.splitlines() + [""]:
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur = Worktree(path=val)
        elif cur is None:
            continue
        elif key == "branch":
            cur.branch = val.removeprefix("refs/heads/")
        elif key in ("bare", "detached", "locked", "prunable"):
            setattr(cur, key, True)
        elif line == "":
            cur.primary = not cur.bare and not any(not w.bare for w in out)
            out.append(cur)
            cur = None
    return out


def classify(c: Candidate) -> tuple[str, str]:
    """('remove' | 'skip', reason). Safety checks come first, then merge proof."""
    if c.protected:
        return "skip", c.protected
    if c.session == "active":
        return "skip", "active Claude session"
    if c.session == "unknown":
        return "skip", "session check unavailable"
    if c.locked:
        return "skip", "worktree is locked"
    if c.detached:
        return "skip", "detached HEAD"
    if c.dirty:
        return "skip", "uncommitted changes"
    if c.ahead_of_upstream > 0 or c.verdict == "local-commits":
        return "skip", SKIP_REASONS["local-commits"]
    if c.verdict != "ready":
        return "skip", SKIP_REASONS.get(c.verdict, SKIP_REASONS["unknown"])
    return "remove", c.how


# ---- facts -------------------------------------------------------------------------

def list_worktrees(repo: str) -> list[Worktree]:
    return parse_worktrees(_git(repo, "worktree", "list", "--porcelain"))


def active_session_dirs() -> list[str] | None:
    """cwd of every live Claude session, or None when they can't be listed."""
    if not shutil.which("claude"):
        return None
    r = _run(["claude", "agents", "--json"])
    if r.returncode != 0:
        return None
    try:
        sessions = json.loads(r.stdout)
    except ValueError:
        return None
    if not isinstance(sessions, list) or not all(isinstance(s, dict) for s in sessions):
        return None
    if any(s.get("cwd") is not None and not isinstance(s["cwd"], str) for s in sessions):
        return None
    return [os.path.realpath(s["cwd"]) for s in sessions if s.get("cwd")]


def session_state(path: str, session_dirs: list[str] | None) -> str:
    if session_dirs is None:
        return "unknown"
    real = os.path.realpath(path)
    inside = any(d == real or d.startswith(real + os.sep) for d in session_dirs)
    return "active" if inside else "none"


def merge_proof(branch: str, wt: str) -> tuple[str, str, str, str]:
    """(verdict, pr_number, how, tip): finalize-check's ladder for one branch."""
    pr = fc.gh_pr_facts(wt, branch)
    base, source = fc.resolve_base(pr.base, wt, wt)
    merged, fetch = fc.merged_status(branch, base, wt)
    head = _git(wt, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    landed = fc.merge_commit_landed(pr.merge_commit, base, wt)
    shallow = _git(wt, "rev-parse", "--is-shallow-repository") == "true"
    facts = dataclasses.replace(
        fc.Facts(**{k: "" for k in fc.KEYS}),
        base=base, base_source=source, pr_number=pr.number, pr_state=pr.state,
        pr_open_other=pr.open_other, head_oid=head, merged=merged,
        head_matches=fc.head_matches_status(head, pr.head_oid, wt),
        merge_commit_landed=landed, base_fetch=fetch,
        shallow="yes" if shallow else "no",
    )
    verdict = fc.choose_verdict(facts)
    if merged == "yes":
        how = f"PR #{pr.number} merged; branch is on origin/{base}"
    else:
        how = f"PR #{pr.number} squash/rebase-merged into {base}"
    return verdict, pr.number, how, head


def ahead_of_upstream(wt: str, branch: str) -> int:
    n = _git(wt, "rev-list", "--count", f"{branch}@{{upstream}}..{branch}")
    return int(n) if n.isdigit() else 0


def protected_reason(w: Worktree, ctx: Context) -> str:
    if w.primary:
        return "primary worktree"
    real = os.path.realpath(w.path)
    if real == ctx.repo or ctx.cwd == real or ctx.cwd.startswith(real + os.sep):
        return "worktree the tool is running from"
    if w.branch == ctx.base_branch:
        return f"base branch ({ctx.base_branch})"
    if fc.dotfiles_facts(w.path)[0] == "deploy":
        return "chezmoi deploy clone"
    return ""


def remote_branch_exists(repo: str, branch: str) -> bool | None:
    """--exit-code gives 2 for 'no matching ref'; any other failure is unknown."""
    rc = _run(["git", "-C", repo, "ls-remote", "--exit-code", "--heads",
               "origin", f"refs/heads/{branch}"]).returncode
    return {0: True, 2: False}.get(rc)


def worktree_candidate(w: Worktree, ctx: Context) -> Candidate:
    c = Candidate(path=w.path, branch=w.branch, locked=w.locked,
                  detached=w.detached or not w.branch,
                  protected=protected_reason(w, ctx),
                  session=session_state(w.path, ctx.session_dirs))
    if c.protected or c.detached or not os.path.isdir(w.path):
        return c
    c.dirty = bool(_git(w.path, "status", "--porcelain"))
    c.ahead_of_upstream = ahead_of_upstream(w.path, w.branch)
    c.verdict, c.pr_number, c.how, c.tip = merge_proof(w.branch, w.path)
    return c


def stale_registration(w: Worktree) -> Candidate:
    return Candidate(path=w.path, branch=w.branch,
                     protected="stale registration, directory missing; "
                               "run `git worktree prune`")


def branch_candidate(branch: str, ctx: Context) -> Candidate:
    c = Candidate(path="", branch=branch)
    c.ahead_of_upstream = ahead_of_upstream(ctx.repo, branch)
    c.verdict, c.pr_number, c.how, c.tip = merge_proof(branch, ctx.repo)
    return c


def build_context(repo: str) -> Context:
    return Context(repo=repo, base_branch=repo_facts.default_branch(repo),
                   session_dirs=active_session_dirs(),
                   cwd=os.path.realpath(os.getcwd()))


def find_candidates(repo: str) -> list[Candidate]:
    worktrees = [w for w in list_worktrees(repo) if not w.bare]
    ctx = build_context(repo)
    out = [stale_registration(w) if w.prunable else worktree_candidate(w, ctx)
           for w in worktrees]
    checked_out = {w.branch for w in worktrees}
    if fc.dotfiles_facts(repo)[0] == "deploy":
        return out
    refs = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    for b in refs.splitlines():
        if b and b not in checked_out and b != ctx.base_branch:
            out.append(branch_candidate(b, ctx))
    for c in out:
        if classify(c)[0] == "remove":
            c.remote_exists = remote_branch_exists(repo, c.branch)
    return out


# ---- removal -------------------------------------------------------------------------

def delete_branch(repo: str, branch: str, tip: str, force: bool) -> tuple[str, str]:
    """('deleted' | 'kept' | 'failed', detail). `-d` first; on its "not fully
    merged" refusal the caller's PR proof stands in for it, but only with
    force, and pinned to the verified tip so a branch that moved survives.
    LC_ALL=C: the refusal gate matches git's English text."""
    r = _run(["env", "LC_ALL=C", "git", "-C", repo, "branch", "-d", branch])
    if r.returncode == 0:
        return "deleted", ""
    if "not fully merged" not in r.stderr:
        return "failed", r.stderr.strip()
    if not force:
        return "kept", (f"git -d refuses (PR proof holds); "
                        f"to delete: git branch -D {branch}")
    if not tip:
        return "failed", "verified tip unknown"
    r = _run(["env", "LC_ALL=C", "git", "-C", repo, "update-ref", "-d",
              f"refs/heads/{branch}", tip])
    if r.returncode != 0:
        return "failed", r.stderr.strip()
    _run(["git", "-C", repo, "config", "--remove-section", f"branch.{branch}"])
    return "deleted", ""


def remove_candidate(repo: str, c: Candidate, delete_remote: bool,
                     force_delete: bool = False) -> tuple[str, str]:
    """Remove worktree, then branch. ('removed' | 'partial' | 'failed', msg).
    Never --force on the worktree; see delete_branch for the branch rules.
    'partial' = worktree gone, branch kept for lack of force_delete."""
    if c.verdict != "ready":
        return "failed", "no merge proof"
    if delete_remote and c.remote_exists is None:
        return "failed", "origin lookup failed; nothing removed"
    if c.path:
        r = _run(["git", "-C", repo, "worktree", "remove", c.path])
        if r.returncode != 0:
            return "failed", f"worktree remove failed: {r.stderr.strip()}"
    tip = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{c.branch}")
    state, detail = delete_branch(repo, c.branch, c.tip or tip, force_delete)
    if state == "failed":
        return "failed", f"branch delete failed: {detail}"
    if state == "kept":
        prefix = "worktree removed; branch kept: " if c.path else "branch kept: "
        return "partial", prefix + detail
    if delete_remote and c.remote_exists:
        # Lease on the tip we just deleted locally: follow-up work pushed since survives.
        r = _run(["git", "-C", repo, "push", "origin",
                  f"--force-with-lease=refs/heads/{c.branch}:{tip}",
                  f":refs/heads/{c.branch}"])
        if r.returncode != 0:
            return "failed", f"local branch removed; remote delete failed: {r.stderr.strip()}"
    return "removed", "removed"


def recheck(repo: str, c: Candidate) -> Candidate:
    """Fresh facts for one candidate, so state that changed since listing wins."""
    worktrees = [w for w in list_worktrees(repo) if not w.bare]
    ctx = build_context(repo)
    for w in worktrees:
        if w.path == c.path and c.path:
            if w.branch != c.branch:
                return dataclasses.replace(c, verdict="unknown")
            fresh = worktree_candidate(w, ctx)
            fresh.remote_exists = c.remote_exists
            return fresh
    if not c.path:
        fresh = branch_candidate(c.branch, ctx)
        fresh.remote_exists = c.remote_exists
        return fresh
    return dataclasses.replace(c, verdict="unknown")


# ---- output ----------------------------------------------------------------------------

def render_line(tag: str, c: Candidate, reason: str) -> str:
    where = c.path or "(no worktree)"
    return f"{tag:<7} {c.branch or '(detached)'}\t{where}\t{reason}"


def render_report(cands: list[Candidate], delete_remote: bool) -> list[str]:
    lines: list[str] = []
    removable = 0
    for c in cands:
        action, reason = classify(c)
        if action == "remove":
            removable += 1
            note = f"; origin/{c.branch} exists" if c.remote_exists else ""
            if c.remote_exists is None:
                note = f"; origin/{c.branch} state unknown (lookup failed)"
            lines.append(render_line("REMOVE", c, reason + note))
        else:
            lines.append(render_line("SKIP", c, reason))
    remotes = [c for c in cands if classify(c)[0] == "remove" and c.remote_exists]
    if remotes and not delete_remote:
        lines.append(f"{len(remotes)} remote branch(es) kept; add --delete-remote to delete them.")
    lines.append(f"{removable} removable, {len(cands) - removable} skipped.")
    return lines


# ---- CLI ---------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="prune-worktrees", add_help=False)
    p.add_argument("--repo", default=".")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--delete-remote", action="store_true")
    p.add_argument("--force-delete", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    return p


def apply_removals(repo: str, cands: list[Candidate], delete_remote: bool,
                   force_delete: bool) -> int:
    failures = 0
    for c in cands:
        if classify(c)[0] != "remove":
            continue
        fresh = recheck(repo, c)
        action, reason = classify(fresh)
        if action != "remove":
            print(render_line("KEPT", c, f"changed since listing: {reason}"))
            continue
        status, msg = remove_candidate(repo, fresh, delete_remote, force_delete)
        print(render_line(status.upper(), c, msg))
        failures += status == "failed"
    return failures


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 13):
        sys.exit("prune_worktrees: Python 3.13+ required; "
                 "install with: pyenv install 3.13")
    try:
        args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return 1
    if args.help:
        sys.stdout.write(HELP)
        return 0
    if args.delete_remote and not args.yes:
        print("prune-worktrees: --delete-remote needs --yes", file=sys.stderr)
        return 1
    repo = os.path.realpath(_git(args.repo, "rev-parse", "--show-toplevel") or args.repo)
    if not _git_ok(repo, "rev-parse", "--git-dir"):
        print("prune-worktrees: not inside a git repo", file=sys.stderr)
        return 1
    force_delete = args.force_delete or repo_facts.conf_get(
        "prune_force_delete", repo) == "true"
    cands = find_candidates(repo)
    sys.stdout.reconfigure(errors="surrogateescape")
    if not args.yes:
        print("DRY RUN: nothing will change. Re-run with --yes to remove.")
        print(f"force-delete: {'on' if force_delete else 'off'} "
              "(branches git -d refuses are " +
              ("deleted after PR proof)" if force_delete else "kept with a -D hint)"))
        print("\n".join(render_report(cands, args.delete_remote)))
        return 0
    return 1 if apply_removals(repo, cands, args.delete_remote, force_delete) else 0


if __name__ == "__main__":
    sys.exit(main())
