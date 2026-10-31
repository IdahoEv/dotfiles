#!/usr/bin/env bash
# finalize-check.sh — read-only post-merge verification for a feature branch.
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

set -euo pipefail

die() { printf 'finalize-check: %s\n' "$*" >&2; exit 1; }

# ---- resolve our own dir (following symlinks) -----------------------------
_src="${BASH_SOURCE[0]}"
while [ -h "$_src" ]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [ "${_src#/}" = "$_src" ] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_src")" && pwd)"
# shellcheck source=lib/repo-facts.sh
. "$SCRIPT_DIR/lib/repo-facts.sh"

# ---- args -------------------------------------------------------------------
branch="" dir="."
while [ $# -gt 0 ]; do
  case "$1" in
    --branch) branch="${2:?--branch needs a value}"; shift 2 ;;
    --dir)    dir="${2:?--dir needs a value}"; shift 2 ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0 ;;
    *)        die "unknown arg: $1" ;;
  esac
done

git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repo: $dir"
[ -n "$branch" ] || branch="$(git -C "$dir" branch --show-current)"
[ -n "$branch" ] || die "not on a branch (detached HEAD) — pass --branch"

worktree="$(cd -P "$(git -C "$dir" rev-parse --show-toplevel)" && pwd)"

# In a shallow repo, ancestry answers are bounded by the graft line: a `no` may
# only mean "the connecting history isn't here". Used to keep `not-on-base`,
# which asserts proof, from firing on a truncated graph.
shallow="no"
if [ "$(git -C "$worktree" rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
  shallow="yes"
fi

# ---- remote-tracking health -------------------------------------------------
# Without remote.origin.fetch, `git fetch origin` never advances
# refs/remotes/origin/*, so every ancestry test here would be answered from
# refs frozen at clone time. The fetches below pass explicit refspecs so this
# script is correct anyway, but the repo is still misconfigured for every other
# tool (and for the caller's own `git log origin/<base>`), so say so on stderr.
# Reported, never fatal: the verdict remains trustworthy.
#
# --get-all plus a grep for the destination, not a bare existence test: the key
# is multi-valued, and a repo whose only refspec fetches notes or PR refs has
# one while refs/remotes/origin/* still never advance.
tracking_refspec="ok"
if ! git -C "$worktree" config --get-all remote.origin.fetch 2>/dev/null \
      | grep -q ':refs/remotes/' \
   && git -C "$worktree" remote get-url origin >/dev/null 2>&1; then
  tracking_refspec="missing"
  printf 'finalize-check: WARNING: remote.origin.fetch is unset in this repo.\n' >&2
  printf '  refs/remotes/origin/* never advance on fetch, so origin/<base> is frozen\n' >&2
  printf '  at clone time. This check compensates with explicit refspecs, but other\n' >&2
  printf '  tooling does not. Repair with:\n' >&2
  printf "    git -C %s config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*' && git -C %s fetch origin\n" \
    "$worktree" "$worktree" >&2
fi

# ---- ticket -----------------------------------------------------------------
ticket_id="$(gt::ticket_from_branch "$branch")"
ticket_scheme="$(gt::ticket_scheme "$branch")"
_chain="$(git -C "$worktree" rev-parse --absolute-git-dir 2>/dev/null)/chain"
if [ -s "$_chain" ]; then chain_ids="$(paste -sd, "$_chain")"; else chain_ids="$ticket_id"; fi

# ---- PR ---------------------------------------------------------------------
# Shortcut-tracked repos still host their PRs on GitHub, so `gh` is the right
# first try regardless of which tracker owns the ticket. A non-GitHub host
# leaves these empty and the verdict `unknown`, which the caller reports rather
# than acting on.
pr_number="" pr_state="none" pr_merge_commit="" pr_head_oid="" pr_base=""
pr_count=0 pr_open_other=""
if command -v gh >/dev/null && command -v jq >/dev/null; then
  # Distinguish "query succeeded, no PR" from "query failed": both yield an
  # empty string, but conflating them would report an auth/network/wrong-repo
  # error as verdict=no-pr — i.e. "nothing to finalize", which reads like a
  # clean answer. Only a zero exit may leave pr_state at "none".
  # A MERGED PR wins over a higher-numbered one. A branch can carry several
  # PRs against different bases, and since `base` now comes from the chosen
  # PR, the choice decides which question gets asked. Taking the newest
  # outright lets an open-or-closed PR against a throwaway base supply the
  # base while a merged PR supplies the merge facts — the one route found to
  # `verdict=ready` on work that never reached the branch anyone cares about.
  if pr_all="$(cd "$worktree" && gh pr list --head "$branch" --state all \
      --json number,state,mergedAt,mergeCommit,headRefOid,baseRefName \
      2>/dev/null)"; then
    # A zero exit does not guarantee JSON (a proxy interstitial, an upgrade
    # notice). Unguarded, jq's parse failure would kill the script under
    # `set -e` with no `verdict=` line at all — and a caller parsing stdout
    # for a verdict it never finds is a caller with no stop signal.
    if ! pr_count="$(printf '%s' "$pr_all" | jq -r 'length' 2>/dev/null)"; then
      pr_count=0
      pr_state="unknown"
      pr_all=""
    fi
    pr_count="${pr_count:-0}"   # jq on empty input prints nothing, not 0
    pr_json="$(printf '%s' "$pr_all" | jq -c \
      '(map(select(.state == "MERGED")) | sort_by(.number) | last)
       // (sort_by(.number) | last) // empty' 2>/dev/null || true)"
    if [ -n "$pr_json" ]; then
      pr_number="$(printf '%s' "$pr_json"      | jq -r '.number // empty')"
      pr_state="$(printf '%s' "$pr_json"       | jq -r '.state // "unknown"')"
      pr_merge_commit="$(printf '%s' "$pr_json"| jq -r '.mergeCommit.oid // empty')"
      pr_head_oid="$(printf '%s' "$pr_json"    | jq -r '.headRefOid // empty')"
      pr_base="$(printf '%s' "$pr_json"        | jq -r '.baseRefName // empty')"
      # An OPEN PR other than the one chosen is the signal that this branch's
      # work has a destination it has not reached. Without it, a branch merged
      # into a throwaway base while its real PR is still open reports `ready`
      # and /finalize deletes the only ref to that work.
      pr_open_other="$(printf '%s' "$pr_all" | jq -r \
        --argjson n "${pr_number:-0}" \
        '[.[] | select(.state == "OPEN" and .number != $n) | .number]
         | join(",")')"
    fi
  else
    pr_state="unknown"
  fi
else
  pr_state="unknown"
fi

# ---- base branch ------------------------------------------------------------
# The PR's OWN base wins over origin's default. Every ancestry test below asks
# "did this land on <base>", and for a stacked PR or one targeting a release
# branch the honest answer is about the branch the PR actually merged into. Use
# the repo default only when there is no PR to ask (or no gh/jq).
#
# Resolved AFTER the PR query for that reason. Getting this wrong is not
# cosmetic: with base=<default> a PR merged into release/1.0 yields merged=no,
# merge_commit_landed=no and base_fetch=ok, which is exactly the `not-on-base`
# signature — the script's hardest stop, fired on work that landed correctly.
if [ -n "$pr_base" ]; then
  base="$pr_base"
  base_source="pr"
else
  base="$(gt::default_branch "$dir" || true)"
  base_source="default"
fi

# A merged PR's base is routinely deleted afterwards — the normal end state for
# a stacked PR's intermediate branch. origin/<base> then can't be fetched or
# resolved, every ancestry test answers `unknown`, and the verdict degrades to
# `unknown` for a branch whose work reached the default branch transitively.
# Fall back to the repo default in that case, and say which base was used.
#
# Two details keep this from firing on things that aren't a deleted branch:
#   - rc 2 specifically, not any failure. --exit-code reserves 2 for "no
#     matching refs"; a network/auth failure is 128. Offline, treating 128 as
#     "gone" would swap the base AND label the swap `default_pr_base_gone` in
#     the report -- a confident false statement about the remote.
#   - the full ref path as the pattern. `ls-remote --heads origin main` matches
#     by trailing component, so refs/heads/foo/main would answer for `main`.
if [ "$base_source" = "pr" ]; then
  git -C "$worktree" ls-remote --exit-code --heads origin \
      "refs/heads/${base}" >/dev/null 2>&1 || ls_rc=$?
  if [ "${ls_rc:-0}" = "2" ]; then
    fallback="$(gt::default_branch "$dir" || true)"
    if [ -n "$fallback" ] && [ "$fallback" != "$base" ]; then
      base="$fallback"
      base_source="default_pr_base_gone"
    fi
  fi
fi

# ---- merged? ----------------------------------------------------------------
# Always compare against origin/<base>: the local base ref is frequently stale.
#
# Fetch an EXPLICIT refspec rather than `fetch origin "$base"`. The bare form
# relies on remote.origin.fetch to decide what to update, and a repo converted
# to the bare-worktree layout by worktree-manager.sh may not have that config:
# `git clone --bare` writes no refspec, so `fetch origin <branch>` updates
# FETCH_HEAD only and refs/remotes/origin/* stays frozen at clone time --
# silently, forever. The ancestry test below would then be answered from a
# stale ref and report merged=no for a branch that merged days ago.
#
# sibling-worktrees.sh carries a note about the same hazard and deliberately
# tolerates it: there, a stale ref only ever OVER-reports work, costing a
# confirmation. That reasoning does not transfer here. Staleness in this
# direction UNDER-reports merged-ness and feeds a verdict that gates
# `git branch -D`, so it must be correct even in an unrepaired repo.
#
# Keep the fetch's exit status. It must not be fatal — the script still answers
# from whatever refs it has — but discarding it entirely would recreate the
# ambiguity this fix exists to kill, one level up: a caller reading `merged=no`
# could not tell "we refreshed the base and the work really isn't there" from
# "we're offline and origin/<base> is last week's". `base_fetch` makes that
# explicit, and it is the precondition for asserting `not-on-base` below.
merged="unknown"
base_fetch="skipped"
if [ -n "$base" ]; then
  if git -C "$worktree" fetch --quiet origin \
      "+refs/heads/${base}:refs/remotes/origin/${base}" 2>/dev/null; then
    base_fetch="ok"
  else
    base_fetch="failed"
  fi
  if git -C "$worktree" rev-parse --verify --quiet "origin/$base" >/dev/null; then
    # refs/heads/, not a bare name: a TAG of the same name outranks a branch in
    # git's disambiguation order and would answer the merged question for it.
    if git -C "$worktree" merge-base --is-ancestor \
        "refs/heads/${branch}" "origin/$base" 2>/dev/null; then
      merged="yes"
    else
      merged="no"
    fi
  fi
fi

# ---- local tip vs PR head ---------------------------------------------------
# The PR only proves its *remote head* merged. Commits added locally after the
# last push are invisible to it and would be destroyed by a branch delete.
#
# What matters is ANCESTRY, not OID equality: a mismatch alone doesn't mean
# local work exists. If someone else pushed the final commit and this worktree
# never pulled, the local tip is *behind* the PR head — nothing to lose, and
# treating it as local work would block cleanup for no reason.
#   same     local tip == PR head
#   behind   local tip is an ancestor of the PR head (stale worktree, safe)
#   ahead    PR head is an ancestor of local tip (real local-only commits)
#   diverged both sides have commits the other lacks (also unsafe)
#   unknown  the PR-head object isn't present locally, so ancestry is unprovable
#
# Resolve the BRANCH, not the worktree's HEAD. Every other fact here is about
# $branch, and with --branch (or after the `cd <base_worktree>` that step 4 of
# /finalize tells you to do) HEAD is a different ref entirely. Answering the
# local-commits guard about the wrong branch is the one way left to report
# `ready` for a branch carrying unpushed commits -- the exact thing this block
# exists to prevent.
head_oid="$(git -C "$worktree" rev-parse --verify --quiet \
  "refs/heads/${branch}" || true)"
head_matches="unknown"
if [ -n "$pr_head_oid" ]; then
  if [ "$head_oid" = "$pr_head_oid" ]; then
    head_matches="same"
  elif ! git -C "$worktree" cat-file -e "${pr_head_oid}^{commit}" 2>/dev/null; then
    # Not fetched (or garbage-collected after a merged branch was deleted).
    # Try once, then give up rather than guessing.
    git -C "$worktree" fetch --quiet origin "$pr_head_oid" 2>/dev/null || true
    git -C "$worktree" cat-file -e "${pr_head_oid}^{commit}" 2>/dev/null \
      || head_matches="unknown"
  fi
  if [ "$head_matches" = "unknown" ] && git -C "$worktree" cat-file -e "${pr_head_oid}^{commit}" 2>/dev/null; then
    if git -C "$worktree" merge-base --is-ancestor "$head_oid" "$pr_head_oid" 2>/dev/null; then
      head_matches="behind"
    elif git -C "$worktree" merge-base --is-ancestor "$pr_head_oid" "$head_oid" 2>/dev/null; then
      head_matches="ahead"
    else
      head_matches="diverged"
    fi
  fi
fi

# ---- base worktree ----------------------------------------------------------
# worktree-manager.sh's layout puts every worktree as a sibling under the repo
# family dir, so the base branch has one too. Find it by branch, not by name.
base_worktree=""
if [ -n "$base" ]; then
  base_worktree="$(git -C "$worktree" worktree list --porcelain \
    | awk -v b="refs/heads/$base" '
        /^worktree /{wt=substr($0,10)}
        $0=="branch "b{print wt; exit}')"
fi

# ---- did the merge commit itself land? --------------------------------------
# `merged` asks whether the BRANCH is an ancestor of origin/<base>, which is
# false for a squash or rebase merge even though the work landed. The merge
# commit is the more direct question: if GitHub gave us one and it's an
# ancestor of origin/<base>, the PR demonstrably landed on the base branch
# whatever shape the merge took.
#
# This disambiguates the squash-merged verdict, which otherwise cannot tell
# "squashed, so the branch ref isn't an ancestor" from "ordinary merge, but
# our origin/<base> is stale". Those want opposite responses and the evidence
# a caller would reach for to confirm is the same ref that was stale.
merge_commit_landed="unknown"
if [ -n "$pr_merge_commit" ] && [ -n "$base" ] \
   && git -C "$worktree" rev-parse --verify --quiet "origin/$base" >/dev/null; then
  if ! git -C "$worktree" cat-file -e "${pr_merge_commit}^{commit}" 2>/dev/null; then
    git -C "$worktree" fetch --quiet origin "$pr_merge_commit" 2>/dev/null || true
  fi
  if git -C "$worktree" cat-file -e "${pr_merge_commit}^{commit}" 2>/dev/null; then
    if git -C "$worktree" merge-base --is-ancestor "$pr_merge_commit" "origin/$base" 2>/dev/null; then
      merge_commit_landed="yes"
    else
      merge_commit_landed="no"
    fi
  fi
fi

# ---- verdict ----------------------------------------------------------------
# No local branch by that name -- only reachable via --branch. Every ancestry
# test above silently answered `no` for want of a ref rather than for want of
# the commits, so none of them mean anything. Say so instead of ruling.
if   [ -z "$head_oid" ]; then verdict="unknown"
elif [ -z "$pr_number" ] && [ "$pr_state" != "unknown" ]; then verdict="no-pr"
elif [ "$pr_state" = "unknown" ] || [ "$merged" = "unknown" ]; then verdict="unknown"
elif [ "$pr_state" != "MERGED" ]; then verdict="not-merged"
# Only ahead/diverged mean there is local work the PR never contained. `behind`
# is a stale worktree with nothing to lose, so it's safe to clean up.
elif [ "$head_matches" = "ahead" ] || [ "$head_matches" = "diverged" ]; then verdict="local-commits"
elif [ "$head_matches" = "unknown" ]; then verdict="unknown"
# Another PR for this branch is still open. Whatever the chosen PR proves, the
# branch has an undelivered destination -- stop before deleting it.
elif [ -n "$pr_open_other" ]; then verdict="not-merged"
elif [ "$merged" = "yes" ]; then verdict="ready"
# The branch isn't an ancestor. If the PR's own merge commit IS on
# origin/<base>, the work landed and the branch ref simply doesn't reflect it
# (squash/rebase) -- that's `ready`, no confirmation needed. Only fall through
# to squash-merged when we couldn't prove it, which is the honest "stop and
# look" case rather than a guess.
elif [ "$merged" = "no" ] && [ "$merge_commit_landed" = "yes" ]; then verdict="ready"
# The merge commit is present locally and provably NOT reachable from a base we
# just refreshed: the PR merged somewhere else, or the base was rewritten. This
# is disproof, not absence of proof, and it must not read as the routine
# squash-merge case -- that path ends in `git branch -D` on the only local ref
# to work that never reached this base. Requires base_fetch=ok: against a stale
# base, `no` means nothing.
# The shallow guard matters: past a graft boundary `merge-base --is-ancestor`
# answers `no` for want of connecting history, not because the commit is
# absent from the base. That is unprovable, not false, and `not-on-base`
# claims proof.
# base_source=default_pr_base_gone is excluded for the same reason. There the
# base being tested is NOT the branch the PR targeted -- that one is deleted --
# so a `no` is the expected answer whenever the parent PR was squash-merged:
# the child's merge commit is reachable from the default branch only if the
# parent merged with a merge commit. That's the routine end state of a stack,
# not evidence of a rewritten base.
elif [ "$merged" = "no" ] && [ "$merge_commit_landed" = "no" ] \
     && [ "$base_fetch" = "ok" ] && [ "$shallow" = "no" ] \
     && [ "$base_source" != "default_pr_base_gone" ]; then verdict="not-on-base"
elif [ "$merged" = "no" ]; then verdict="squash-merged"
else verdict="unknown"
fi

# ---- dotfiles repo? ----------------------------------------------------------
# /finalize's deploy step (chezmoi update in the deploy clone + reload report)
# runs only in the dotfiles source repo, so the caller needs that answered here
# with everything else. Mirrors wf::resolve_dotfiles_source() in
# dot_claude/skills/workflow/executable_wf-context.sh, but local: tools/ runs
# in place from the deploy clone and cannot depend on dot_claude/ paths being
# deployed on the machine.
#
# The two clones are SEPARATE, so common-dir equality cannot identify a dev
# worktree; the .chezmoiignore + dot_claude/ markers do. The deploy clone is
# identified by chezmoi's own source-path, or the conventional path when
# chezmoi is not installed.
dotfiles_repo="no" deploy_root="" deploy_branch="" deploy_dirty_files=""
deploy_pull_rebase=""
canon_dir() { (cd -P "$1" 2>/dev/null && pwd -P) || true; }
chezmoi_source=""
if command -v chezmoi >/dev/null; then
  chezmoi_source="$(command chezmoi source-path 2>/dev/null || true)"
fi
[ -n "$chezmoi_source" ] || chezmoi_source="${CHEZMOI_SOURCE_DIR:-$HOME/.local/share/chezmoi}"
if [ -n "$chezmoi_source" ] && [ "$(canon_dir "$chezmoi_source")" = "$(canon_dir "$worktree")" ]; then
  dotfiles_repo="deploy"
  deploy_root="$(canon_dir "$worktree")"
elif [ -f "$worktree/.chezmoiignore" ] && [ -d "$worktree/dot_claude" ]; then
  dotfiles_repo="dev"
  deploy_root="$(canon_dir "$chezmoi_source")"
fi
# Deploy-clone health for the caller's `chezmoi update` preflight. Read-only:
# status/rev-parse/config only. Empty keys when there is nothing to preflight.
if [ "$dotfiles_repo" != "no" ] && [ -n "$deploy_root" ] && [ -d "$deploy_root" ] \
   && git -C "$deploy_root" rev-parse --git-dir >/dev/null 2>&1; then
  deploy_branch="$(git -C "$deploy_root" branch --show-current 2>/dev/null || true)"
  deploy_dirty_files="$(git -C "$deploy_root" status --porcelain 2>/dev/null | wc -l | tr -d ' ' || true)"
  deploy_pull_rebase="false"
  if [ "$(git -C "$deploy_root" config --get pull.rebase 2>/dev/null || true)" = "true" ]; then
    deploy_pull_rebase="true"
  fi
fi

printf 'branch=%s\nticket_id=%s\nchain_ids=%s\nticket_scheme=%s\nbase=%s\nbase_source=%s\n' \
  "$branch" "$ticket_id" "$chain_ids" "$ticket_scheme" "$base" "$base_source"
printf 'pr_number=%s\npr_state=%s\npr_merge_commit=%s\npr_head_oid=%s\n' \
  "$pr_number" "$pr_state" "$pr_merge_commit" "$pr_head_oid"
printf 'pr_count=%s\npr_open_other=%s\n' "$pr_count" "$pr_open_other"
printf 'head_oid=%s\nhead_matches=%s\nmerged=%s\n' \
  "$head_oid" "$head_matches" "$merged"
printf 'merge_commit_landed=%s\nbase_fetch=%s\nshallow=%s\ntracking_refspec=%s\n' \
  "$merge_commit_landed" "$base_fetch" "$shallow" "$tracking_refspec"
# ---- implied agent-view phase -----------------------------------------------
# Which workflow phase the agent-view row should show, derived from the verdict
# so /finalize doesn't re-reason about it. This script stays read-only (it
# reports, it does not stamp) — the caller runs agent-phase.sh with this value.
#
# DONE is deliberately absent: it means "/finalize has finished and the session
# is safe to kill", which is only true after cleanup actually ran, and cleanup
# is the caller's job. Verdicts that mean "stop and look" (local-commits,
# not-on-base, squash-merged, unknown, no-pr) leave this empty rather than
# guessing — a wrong label on a branch that needs attention is worse than no
# change.
#
# squash-merged is in that list because it no longer means "normal squash
# merge": a provably-landed squash now reports `ready` on its own, so reaching
# squash-merged means a check did NOT complete. Offline, a branch with genuine
# not-on-base facts degrades to squash-merged — stamping MERGED there would
# label a branch whose work demonstrably never reached the base.
case "$verdict" in
  ready)      agent_phase="MERGED" ;;
  not-merged) agent_phase="REVIEW" ;;
  *)          agent_phase="" ;;
esac

printf 'base_worktree=%s\nworktree=%s\nverdict=%s\nagent_phase=%s\n' \
  "$base_worktree" "$worktree" "$verdict" "$agent_phase"
printf 'dotfiles_repo=%s\ndeploy_root=%s\ndeploy_branch=%s\n' \
  "$dotfiles_repo" "$deploy_root" "$deploy_branch"
printf 'deploy_dirty_files=%s\ndeploy_pull_rebase=%s\n' \
  "$deploy_dirty_files" "$deploy_pull_rebase"

# The one write this script makes; telemetry never changes its exit status.
# shellcheck source=lib/telemetry.sh
{ . "$SCRIPT_DIR/lib/telemetry.sh" \
  && wf::emit --dir "$dir" finalize.check "ticket=$ticket_id" "scheme=$ticket_scheme" \
       "verdict=$verdict" "pr_number=$pr_number" "pr_state=$pr_state"; } || true
