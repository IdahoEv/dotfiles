#!/usr/bin/env python3
"""Read-only post-merge verification for a feature branch (port of
finalize-check.sh).

    finalize-check.sh [--branch <name>] [--dir <worktree>]

Answers, in one call, every deterministic question /finalize used to ask the
model to work out command-by-command: which ticket does this branch belong
to, is there a PR, did it merge, did it actually land on the base branch,
are there local commits the PR never saw, and where is the base worktree.

Stdout is 28 key=value lines, one per fact, in the order of the Facts
fields; `verdict` is the one-line summary a caller branches on. Exit 0
whenever the repo could be inspected (read `verdict`, not $?) and 1 only on
usage/precondition errors. Makes NO changes: no pushes, no deletes, no
ticket writes — the judgment calls stay in the command. The one exception
is the finalize.check telemetry event, which never affects the exit status.

choose_verdict() and agent_phase_for() are pure so a later port (#119) can
import the verdict ladder without the fact collection.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # wrapper runs -I
import repo_facts

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HELP = """# finalize-check.sh — read-only post-merge verification for a feature branch.
#
#   finalize-check.sh [--branch <name>] [--dir <worktree>]
#
# Answers, in one call, every deterministic question /finalize used to ask the
# model to work out command-by-command: which ticket does this branch belong
# to, is there a PR, did it merge, did it actually land on the base branch, are
# there local commits the PR never saw, and where is the base worktree.
#
# Makes NO changes: no pushes, no deletes, no ticket writes. The judgment calls
# /finalize still owns — which done-state to set on Shortcut, whether to delete
# a worktree that looks off — stay in the command, same division of labor as
# open-pr.sh vs. /open-pr.
#
# Output (stdout, parseable key=value, one per line):
#   branch=<name>
#   ticket_id=<id>              (empty if unparseable)
#   chain_ids=<id,id>           (every ticket the branch closes, from
#                               <git-dir>/chain; just ticket_id when not a chain)
#   ticket_scheme=shortcut|github|unknown
#   base=<branch>               (the branch the PR targets, falling back to
#                               origin's default; empty if unresolvable)
#   base_source=pr|default|default_pr_base_gone
#                               (which answered; the third means the PR's base
#                               no longer exists on origin — typical for a
#                               merged stacked PR — so the repo default was
#                               used instead)
#   pr_number=<n>               (empty if none found; a MERGED PR is preferred
#                               over a higher-numbered one)
#   pr_state=MERGED|OPEN|CLOSED|none|unknown
#   pr_merge_commit=<sha>
#   pr_head_oid=<sha>
#   pr_count=<n>                (PRs found for this head branch, any state)
#   pr_open_other=<n,n>         (OPEN PRs other than pr_number — a branch with
#                               an undelivered destination; forces not-merged)
#   head_oid=<sha>              (local tip)
#   head_matches=same|behind|ahead|diverged|unknown
#                               (local tip's relationship to the PR head)
#   merged=yes|no|unknown       (branch is an ancestor of origin/<base>)
#   merge_commit_landed=yes|no|unknown
#                               (the PR's merge commit is an ancestor of
#                               origin/<base> — true for squash/rebase merges
#                               where the branch ref itself is not)
#   base_fetch=ok|failed|skipped
#                               (did the refresh of origin/<base> succeed? A
#                               `failed` here means every ancestry answer below
#                               was computed from a possibly-stale base.)
#   shallow=yes|no              (a shallow repo bounds every ancestry answer at
#                               the graft line; suppresses `not-on-base`.)
#   tracking_refspec=ok|missing (remote.origin.fetch present? `missing` means
#                               the repo needs repair; this check compensates
#                               internally but other tooling will read stale
#                               refs. Also warned about on stderr.)
#   base_worktree=<path>        (empty if not found)
#   worktree=<path>             (the worktree being finalized)
#   dotfiles_repo=dev|deploy|no (dev: this repo is the dotfiles source; deploy:
#                               this IS the chezmoi deploy clone; no: any other
#                               repo — /finalize's deploy step is gated on `dev`)
#   deploy_root=<path>          (chezmoi source-path; dotfiles repos only,
#                               empty if unresolvable)
#   deploy_branch=<name>        (dotfiles only; `chezmoi update` requires main)
#   deploy_dirty_files=<n>      (dotfiles only; >0 means someone left local
#                               state in the clone that must not be stomped)
#   deploy_pull_rebase=true|false
#                               (dotfiles only; false means the internal pull
#                               makes merge commits — offer the config fix)
#   verdict=ready|not-merged|no-pr|local-commits|squash-merged|not-on-base|
#           unknown
#   agent_phase=MERGED|REVIEW|  the agent-view phase this verdict implies, for
#               <empty>         the caller to pass to agent-phase.sh. Empty when
#                               the verdict doesn't justify moving the label.
#
# `verdict` is the one-line summary a caller can branch on:
#   ready          PR merged AND branch is an ancestor of origin/<base> AND
#                  local tip == PR head. Safe to clean up.
#   no-pr          no PR found for this branch — nothing to finalize.
#   not-merged     a PR exists but hasn't merged.
#   squash-merged  PR says MERGED, the branch isn't an ancestor of
#                  origin/<base>, AND we could not prove the merge commit
#                  landed either. Evidence is MISSING, not negative: the merge
#                  commit wasn't fetchable, or the base ref couldn't be
#                  refreshed. Caller should confirm before deleting.
#                  (When the merge commit IS provably an ancestor, the work
#                  landed in squashed/rebased form and the verdict is `ready`.)
#   not-on-base    PR says MERGED, but its merge commit is present locally and
#                  provably NOT reachable from a freshly-fetched origin/<base>,
#                  where <base> is the branch the PR itself targets. The base
#                  was rewritten, or the merge was reverted. Stronger than
#                  squash-merged: this is disproof, not absence of proof.
#                  Caller must stop — the branch may hold the only local ref to
#                  work that never reached this base.
#   local-commits  PR merged, but the local branch is ahead of or diverged from
#                  the PR head: there is work here the PR never contained.
#                  Caller must stop. (A branch merely *behind* the PR head is a
#                  stale worktree with nothing to lose — that stays `ready`.)
#   unknown        couldn't determine (no gh/jq, not the right host, no base,
#                  or the PR-head commit isn't available locally).
#
# Exit codes: 0 always when it could inspect the repo (read `verdict`, not $?);
#             1 usage/precondition error (not a repo, detached HEAD).

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


def _has_commit(worktree: str, sha: str) -> bool:
    return _git_ok(worktree, "cat-file", "-e", f"{sha}^{{commit}}")


def _canon(path: str) -> str:
    """cd -P && pwd: symlink-resolved, "" when the path is not a directory."""
    real = os.path.realpath(path)
    return real if os.path.isdir(real) else ""


# ---- the report --------------------------------------------------------------

@dataclasses.dataclass
class Facts:
    """The 28 output values, in output order (render pairs them with KEYS)."""

    branch: str
    ticket_id: str
    chain_ids: str
    ticket_scheme: str
    base: str
    base_source: str
    pr_number: str
    pr_state: str
    pr_merge_commit: str
    pr_head_oid: str
    pr_count: str
    pr_open_other: str
    head_oid: str
    head_matches: str
    merged: str
    merge_commit_landed: str
    base_fetch: str
    shallow: str
    tracking_refspec: str
    base_worktree: str
    worktree: str
    verdict: str
    agent_phase: str
    dotfiles_repo: str
    deploy_root: str
    deploy_branch: str
    deploy_dirty_files: str
    deploy_pull_rebase: str


KEYS = tuple(f.name for f in dataclasses.fields(Facts))


@dataclasses.dataclass
class PrFacts:
    number: str = ""
    state: str = "none"
    merge_commit: str = ""
    head_oid: str = ""
    base: str = ""
    count: int = 0
    open_other: str = ""


# ---- PR query -----------------------------------------------------------------

def choose_pr(prs: list[dict]) -> dict | None:
    """A MERGED PR wins over a higher-numbered one, and among equals the
    highest number wins. A branch can carry PRs against several bases, and
    since `base` comes from the chosen PR, taking the newest outright lets an
    open-or-closed PR against a throwaway base supply the base while a merged
    PR supplies the merge facts — the one route to `verdict=ready` on work
    that never reached the branch anyone cares about."""
    merged = sorted((p for p in prs if p.get("state") == "MERGED"),
                    key=lambda p: p.get("number", 0))
    if merged:
        return merged[-1]
    rest = sorted(prs, key=lambda p: p.get("number", 0))
    return rest[-1] if rest else None


def open_other_numbers(prs: list[dict], chosen: dict | None) -> str:
    """OPEN PRs other than the chosen one — a branch with an undelivered
    destination. Without this, a branch merged into a throwaway base while
    its real PR is still open reports `ready` and /finalize deletes the only
    ref to that work."""
    n = chosen.get("number") if chosen else None
    return ",".join(str(p["number"]) for p in prs
                    if p.get("state") == "OPEN" and p.get("number") != n)


def gh_pr_facts(worktree: str, branch: str) -> PrFacts:
    """PR facts for this head branch from `gh pr list`, or state=unknown.

    Shortcut-tracked repos still host PRs on GitHub, so gh is the right first
    try regardless of which tracker owns the ticket; no gh/jq on PATH leaves
    the verdict `unknown`, which the caller reports rather than acting on."""
    if not (shutil.which("gh") and shutil.which("jq")):
        return PrFacts(state="unknown")
    r = _run(["gh", "pr", "list", "--head", branch, "--state", "all",
              "--json", "number,state,mergedAt,mergeCommit,headRefOid,baseRefName"],
             cwd=worktree)
    if r.returncode != 0:
        # rc != 0 is auth/network/wrong-repo, NOT "no PR": conflating them
        # would report an error as verdict=no-pr, which reads like a clean answer.
        return PrFacts(state="unknown")
    out = r.stdout.strip()
    if out == "":
        return PrFacts()  # query succeeded, printed nothing: no PR
    try:
        prs = json.loads(out)
        if not isinstance(prs, list):
            raise ValueError
    except ValueError:
        # rc 0 does not guarantee JSON (proxy interstitial, upgrade notice).
        return PrFacts(state="unknown")
    chosen = choose_pr(prs)
    facts = PrFacts(count=len(prs))
    if chosen:
        facts.number = str(chosen.get("number") or "")
        facts.state = chosen.get("state") or "unknown"
        merge = chosen.get("mergeCommit") or {}
        facts.merge_commit = merge.get("oid") or ""
        facts.head_oid = chosen.get("headRefOid") or ""
        facts.base = chosen.get("baseRefName") or ""
        facts.open_other = open_other_numbers(prs, chosen)
    return facts


# ---- base branch and ancestry ---------------------------------------------------

def resolve_base(pr_base: str, dir_: str, worktree: str) -> tuple[str, str]:
    """(base, base_source): the PR's OWN base wins over origin's default.

    Every ancestry test asks "did this land on <base>", and for a stacked PR
    or one targeting a release branch the honest answer is about the branch
    the PR actually merged into. With base=<default> a PR merged into
    release/1.0 looks exactly like `not-on-base` — the hardest stop, fired on
    work that landed correctly."""
    if pr_base:
        base, source = pr_base, "pr"
    else:
        base, source = repo_facts.default_branch(dir_), "default"
    if source == "pr":
        # rc 2 specifically ("no matching refs"): 128 is network/auth, and
        # offline, treating 128 as "gone" would swap the base AND label the
        # swap `default_pr_base_gone` — a confident false statement.
        # The full ref path as the pattern: ls-remote --heads origin main
        # matches by trailing component, so refs/heads/foo/main would answer.
        r = _run(["git", "-C", worktree, "ls-remote", "--exit-code", "--heads",
                  "origin", f"refs/heads/{base}"])
        if r.returncode == 2:
            # A merged PR's base is routinely deleted afterwards; fall back to
            # the repo default and say which base was used.
            fallback = repo_facts.default_branch(dir_)
            if fallback and fallback != base:
                base, source = fallback, "default_pr_base_gone"
    return base, source


def merged_status(branch: str, base: str, worktree: str) -> tuple[str, str]:
    """(merged, base_fetch): is the branch an ancestor of origin/<base>?

    The fetch uses an EXPLICIT refspec: a repo converted to the bare-worktree
    layout has no remote.origin.fetch, so `fetch origin <branch>` would
    update FETCH_HEAD only and refs/remotes/origin/* would stay frozen at
    clone time — silently answering every ancestry question from a stale
    ref. base_fetch records whether the refresh worked; against a stale
    base, `no` means nothing."""
    if not base:
        return "unknown", "skipped"
    r = _run(["git", "-C", worktree, "fetch", "--quiet", "origin",
              f"+refs/heads/{base}:refs/remotes/origin/{base}"])
    base_fetch = "ok" if r.returncode == 0 else "failed"
    if not _git_ok(worktree, "rev-parse", "--verify", "--quiet", f"origin/{base}"):
        return "unknown", base_fetch
    # refs/heads/, not a bare name: a same-named TAG outranks a branch in
    # git's disambiguation order and would answer the merged question for it.
    ok = _git_ok(worktree, "merge-base", "--is-ancestor",
                 f"refs/heads/{branch}", f"origin/{base}")
    return ("yes" if ok else "no"), base_fetch


def head_matches_status(head_oid: str, pr_head_oid: str, worktree: str) -> str:
    """Local tip's relationship to the PR head: same|behind|ahead|diverged|
    unknown. ANCESTRY, not OID equality: if someone else pushed the final
    commit and this worktree never pulled, the local tip is behind — nothing
    to lose — while ahead/diverged mean real local-only commits."""
    if not pr_head_oid:
        return "unknown"
    if head_oid == pr_head_oid:
        return "same"
    if not _has_commit(worktree, pr_head_oid):
        # Not fetched (or garbage-collected after a merged branch was deleted).
        # Try once, then give up rather than guessing.
        _run(["git", "-C", worktree, "fetch", "--quiet", "origin", pr_head_oid])
        if not _has_commit(worktree, pr_head_oid):
            return "unknown"
    if _git_ok(worktree, "merge-base", "--is-ancestor", head_oid, pr_head_oid):
        return "behind"
    if _git_ok(worktree, "merge-base", "--is-ancestor", pr_head_oid, head_oid):
        return "ahead"
    return "diverged"


def merge_commit_landed(pr_merge_commit: str, base: str, worktree: str) -> str:
    """Is the PR's merge commit an ancestor of origin/<base>?

    `merged` is false for a squash or rebase merge even though the work
    landed; the merge commit is the more direct question, and it
    disambiguates squash-merged from a merely stale origin/<base>."""
    if not (pr_merge_commit and base):
        return "unknown"
    if not _git_ok(worktree, "rev-parse", "--verify", "--quiet", f"origin/{base}"):
        return "unknown"
    if not _has_commit(worktree, pr_merge_commit):
        _run(["git", "-C", worktree, "fetch", "--quiet", "origin", pr_merge_commit])
    if not _has_commit(worktree, pr_merge_commit):
        return "unknown"
    ok = _git_ok(worktree, "merge-base", "--is-ancestor",
                 pr_merge_commit, f"origin/{base}")
    return "yes" if ok else "no"


def base_worktree_of(base: str, worktree: str) -> str:
    """The base branch's worktree, found by branch not name: the
    worktree-manager layout puts every worktree as a sibling under the repo
    family dir, so the base branch has one too."""
    if not base:
        return ""
    wt = ""
    for line in _git(worktree, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            wt = line[len("worktree "):]
        elif line == f"branch refs/heads/{base}":
            return wt
    return ""


# ---- repo health ----------------------------------------------------------------

def tracking_refspec(worktree: str) -> str:
    """remote.origin.fetch present (with a refs/remotes destination)?

    Without it refs/remotes/origin/* never advance on fetch. Reported, never
    fatal: this check compensates with explicit refspecs, but every other
    tool reads stale refs. --get-all, not a bare existence test: the key is
    multi-valued, and a repo whose only refspec fetches notes has one while
    origin/* still never advance."""
    r = _run(["git", "-C", worktree, "config", "--get-all", "remote.origin.fetch"])
    if r.returncode == 0 and any(":refs/remotes/" in l for l in r.stdout.splitlines()):
        return "ok"
    if _git_ok(worktree, "remote", "get-url", "origin"):
        print(f"finalize-check: WARNING: remote.origin.fetch is unset in this repo.\n"
              "  refs/remotes/origin/* never advance on fetch, so origin/<base> is\n"
              "  frozen at clone time. This check compensates with explicit\n"
              "  refspecs, but other tooling does not. Repair with:\n"
              f"    git -C {worktree} config remote.origin.fetch "
              f"'+refs/heads/*:refs/remotes/origin/*' && git -C {worktree} fetch origin",
              file=sys.stderr)
        return "missing"
    return "ok"


def chain_ids(ticket_id: str, worktree: str) -> str:
    """Every ticket the branch closes, from <git-dir>/chain; just the ticket
    when not a chain (empty file counts as not a chain)."""
    path = os.path.join(_git(worktree, "rev-parse", "--absolute-git-dir"), "chain")
    try:
        text = open(path, newline="", errors="surrogateescape").read()
    except OSError:
        return ticket_id
    if text == "":
        return ticket_id
    # paste -sd,: join every line, dropping only the final record separator.
    return text[:-1].replace("\n", ",") if text.endswith("\n") else text.replace("\n", ",")


def dotfiles_facts(worktree: str) -> tuple[str, str, str, str, str]:
    """(dotfiles_repo, deploy_root, deploy_branch, deploy_dirty_files,
    deploy_pull_rebase): /finalize's deploy step runs only in the dotfiles
    source repo (dev), so the caller needs this answered with everything
    else. The two clones are SEPARATE, so common-dir equality cannot
    identify a dev worktree; the .chezmoiignore + dot_claude/ markers do.
    The deploy clone is identified by chezmoi's own source-path."""
    source = ""
    if shutil.which("chezmoi"):
        source = _run(["chezmoi", "source-path"]).stdout.strip()
    if not source:
        default = os.path.join(os.path.expanduser("~"), ".local", "share", "chezmoi")
        source = os.environ.get("CHEZMOI_SOURCE_DIR") or default
    dotfiles_repo, deploy_root = "no", ""
    if source and _canon(source) == _canon(worktree):
        dotfiles_repo, deploy_root = "deploy", _canon(worktree)
    elif (os.path.isfile(os.path.join(worktree, ".chezmoiignore"))
          and os.path.isdir(os.path.join(worktree, "dot_claude"))):
        dotfiles_repo, deploy_root = "dev", _canon(source)
    branch = dirty = pull_rebase = ""
    if (dotfiles_repo != "no" and deploy_root and os.path.isdir(deploy_root)
            and _git_ok(deploy_root, "rev-parse", "--git-dir")):
        branch = _git(deploy_root, "branch", "--show-current")
        status = _run(["git", "-C", deploy_root, "status", "--porcelain"])
        dirty = str(len(status.stdout.splitlines()))
        pull_rebase = ("true"
                       if _git(deploy_root, "config", "--get", "pull.rebase") == "true"
                       else "false")
    return dotfiles_repo, deploy_root, branch, dirty, pull_rebase


# ---- verdict --------------------------------------------------------------------

def choose_verdict(f: Facts) -> str:
    """The one-line summary a caller branches on. Pure: takes the collected
    facts, consults nothing else.

      ready          PR merged AND branch on origin/<base> AND local tip
                     matches the PR head (a provably-landed squash also
                     qualifies) — safe to clean up.
      no-pr          no PR found for this branch.
      not-merged     a PR exists but hasn't merged (or another PR for the
                     branch is still open: an undelivered destination).
      local-commits  PR merged, but the local branch is ahead of or diverged
                     from the PR head — work here the PR never contained.
      not-on-base    PR merged, merge commit present locally and provably
                     NOT reachable from a freshly-fetched origin/<base> the
                     PR itself targeted. Disproof, not absence of proof.
      squash-merged  PR says MERGED but landing could not be proven —
                     evidence is MISSING; confirm before deleting.
      unknown        couldn't determine.
    """
    if f.head_oid == "":
        return "unknown"  # no local ref: ancestry above answered `no` for want of a ref
    if f.pr_number == "" and f.pr_state != "unknown":
        return "no-pr"
    if f.pr_state == "unknown" or f.merged == "unknown":
        return "unknown"
    if f.pr_state != "MERGED":
        return "not-merged"
    # Only ahead/diverged mean local work the PR never contained; `behind` is
    # a stale worktree with nothing to lose, so it stays cleanable.
    if f.head_matches in ("ahead", "diverged"):
        return "local-commits"
    if f.head_matches == "unknown":
        return "unknown"
    if f.pr_open_other:
        return "not-merged"
    if f.merged == "yes":
        return "ready"
    if f.merged == "no" and f.merge_commit_landed == "yes":
        return "ready"  # squash/rebase merge: the work landed, the ref didn't
    if (f.merged == "no" and f.merge_commit_landed == "no"
            and f.base_fetch == "ok" and f.shallow == "no"
            and f.base_source != "default_pr_base_gone"):
        # base_fetch/shallow/base_source each turn this `no` into
        # "unprovable": a stale base, a graft boundary, or a swapped base
        # (deleted PR base) where `no` is the routine end state of a stack.
        return "not-on-base"
    if f.merged == "no":
        return "squash-merged"
    return "unknown"


def agent_phase_for(verdict: str) -> str:
    """The agent-view phase this verdict implies, for the caller to pass to
    agent-phase.sh. DONE is deliberately absent: it means cleanup actually
    ran, which is the caller's job. Stop-and-look verdicts leave it empty —
    a wrong label on a branch that needs attention is worse than no change
    (squash-merged included: offline, genuine not-on-base facts degrade
    there, and stamping MERGED would mislabel work that never landed)."""
    if verdict == "ready":
        return "MERGED"
    if verdict == "not-merged":
        return "REVIEW"
    return ""


# ---- assembly -------------------------------------------------------------------

def collect_facts(branch: str, dir_: str) -> Facts:
    worktree = _canon(_git(dir_, "rev-parse", "--show-toplevel"))
    shallow = ("yes"
               if _git(worktree, "rev-parse", "--is-shallow-repository") == "true"
               else "no")
    ticket_id = repo_facts.ticket_from_branch(branch)
    pr = gh_pr_facts(worktree, branch)
    base, base_source = resolve_base(pr.base, dir_, worktree)
    merged, base_fetch = merged_status(branch, base, worktree)
    head_oid = _git(worktree, "rev-parse", "--verify", "--quiet",
                    f"refs/heads/{branch}")
    f = Facts(
        branch=branch,
        ticket_id=ticket_id,
        chain_ids=chain_ids(ticket_id, worktree),
        ticket_scheme=repo_facts.ticket_scheme(branch),
        base=base,
        base_source=base_source,
        pr_number=pr.number,
        pr_state=pr.state,
        pr_merge_commit=pr.merge_commit,
        pr_head_oid=pr.head_oid,
        pr_count=str(pr.count),
        pr_open_other=pr.open_other,
        head_oid=head_oid,
        head_matches=head_matches_status(head_oid, pr.head_oid, worktree),
        merged=merged,
        merge_commit_landed=merge_commit_landed(pr.merge_commit, base, worktree),
        base_fetch=base_fetch,
        shallow=shallow,
        tracking_refspec=tracking_refspec(worktree),
        base_worktree=base_worktree_of(base, worktree),
        worktree=worktree,
        verdict="",
        agent_phase="",
        dotfiles_repo="",
        deploy_root="",
        deploy_branch="",
        deploy_dirty_files="",
        deploy_pull_rebase="",
    )
    (f.dotfiles_repo, f.deploy_root, f.deploy_branch,
     f.deploy_dirty_files, f.deploy_pull_rebase) = dotfiles_facts(worktree)
    f.verdict = choose_verdict(f)
    f.agent_phase = agent_phase_for(f.verdict)
    return f


def render(f: Facts) -> str:
    return "".join(f"{k}={v}\n" for k, v in zip(KEYS, dataclasses.astuple(f)))


def emit_telemetry(dir_: str, f: Facts) -> None:
    """The one write this script makes; telemetry never changes the exit
    status (wf-event.sh exits 0 unconditionally, and OSError is swallowed)."""
    try:
        _run([os.path.join(TOOLS_DIR, "wf-event.sh"), "--dir", dir_,
              "finalize.check",
              f"ticket={f.ticket_id}", f"scheme={f.ticket_scheme}",
              f"verdict={f.verdict}", f"pr_number={f.pr_number}",
              f"pr_state={f.pr_state}"])
    except OSError:
        pass


# ---- CLI ------------------------------------------------------------------------

def _die(msg: str) -> None:
    print(f"finalize-check: {msg}", file=sys.stderr)
    sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 13):
        sys.exit("finalize_check: Python 3.13+ required; "
                 "install with: pyenv install 3.13")
    if argv is None:
        argv = sys.argv[1:]
    branch, dir_ = "", "."
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            sys.stdout.write(HELP)
            return 0
        if arg in ("--branch", "--dir"):
            if i + 1 >= len(argv) or argv[i + 1] == "":
                _die(f"{arg} needs a value")
            if arg == "--branch":
                branch = argv[i + 1]
            else:
                dir_ = argv[i + 1]
            i += 2
        else:
            _die(f"unknown arg: {arg}")
    if not _git_ok(dir_, "rev-parse", "--is-inside-work-tree"):
        _die(f"not inside a git repo: {dir_}")
    if not branch:
        branch = _git(dir_, "branch", "--show-current")
    if not branch:
        _die("not on a branch (detached HEAD) — pass --branch")
    f = collect_facts(branch, dir_)
    # Values may carry non-UTF-8 bytes from git (surrogateescape in _run);
    # stdout must pass them back through as bytes, as printf did.
    sys.stdout.reconfigure(errors="surrogateescape")
    sys.stdout.write(render(f))
    emit_telemetry(dir_, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
