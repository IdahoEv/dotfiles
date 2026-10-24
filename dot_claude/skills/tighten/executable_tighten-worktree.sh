#!/usr/bin/env bash
# Create or reuse an isolated worktree for /tighten.
#
#   tighten-worktree.sh ROOT BRANCH [--base REF]
#
# Prints key=value: worktree, branch, mode (wm|plain|reused), reused, head.
# Non-zero with a reason on stderr when it cannot produce a clean worktree.

set -uo pipefail

usage() {
    echo "usage: tighten-worktree.sh ROOT BRANCH [--base REF]" >&2
    exit 2
}

[ $# -ge 2 ] || usage
root="$1"
branch="$2"
shift 2

base=""
while [ $# -gt 0 ]; do
    case "$1" in
        --base) [ $# -ge 2 ] || usage; base="$2"; shift 2 ;;
        *) usage ;;
    esac
done

git -C "$root" rev-parse --git-dir >/dev/null 2>&1 || {
    echo "not a git repository: $root" >&2
    exit 1
}
root="$(git -C "$root" rev-parse --show-toplevel 2>/dev/null || echo "$root")"

find_worktree() {
    git -C "$root" worktree list --porcelain | awk -v target="refs/heads/$branch" '
        !found && /^worktree / { path = substr($0, 10); ref = "" }
        !found && /^branch /   { ref = substr($0, 8) }
        !found && /^$/         { if (ref == target) { print path; found = 1 } }
        END                    { if (!found && ref == target) print path }
    '
}

resolve_sha() {
    git -C "$root" rev-parse --verify "$1^{commit}" 2>/dev/null
}

if [ -n "$base" ]; then
    base_sha="$(resolve_sha "$base")" || {
        echo "unknown base ref: $base" >&2
        exit 1
    }
else
    base_sha="$(git -C "$root" rev-parse HEAD 2>/dev/null)"
fi

if git -C "$root" rev-parse --verify "refs/heads/$branch" >/dev/null 2>&1; then
    branch_sha="$(git -C "$root" rev-parse "refs/heads/$branch")"
    if [ -n "$base_sha" ] && [ "$branch_sha" != "$base_sha" ]; then
        echo "branch $branch exists at $branch_sha, not the scanned $base_sha" >&2
        exit 1
    fi
fi

existing="$(find_worktree)"
if [ -n "$existing" ] && [ ! -d "$existing" ]; then
    git -C "$root" worktree prune >/dev/null 2>&1 || true
    existing=""
fi
if [ -n "$existing" ]; then
    if [ -n "$(git -C "$existing" status --porcelain 2>/dev/null)" ]; then
        echo "existing worktree is dirty: $existing" >&2
        exit 1
    fi
    head="$(git -C "$existing" rev-parse HEAD)"
    if [ -n "$base_sha" ] && [ "$head" != "$base_sha" ]; then
        echo "existing worktree is at $head, not the scanned $base_sha: $existing" >&2
        exit 1
    fi
    printf 'worktree=%s\nbranch=%s\nmode=reused\nreused=yes\nhead=%s\n' \
        "$existing" "$branch" "$head"
    exit 0
fi

mode="plain"
config_root="$(git -C "$root" config --get worktreeManager.configRoot 2>/dev/null || true)"
if [ -n "$config_root" ] && [ -d "$config_root" ] \
        && command -v worktree-manager.sh >/dev/null 2>&1; then
    mode="wm"
    ( cd "$root" && worktree-manager.sh "$branch" >/dev/null ) || true
fi

worktree="$(find_worktree)"
if [ -z "$worktree" ] && [ "$mode" = "wm" ]; then
    mode="plain"
fi

if [ -z "$worktree" ]; then
    parent="$(dirname "$root")"
    name="$(basename "$root")"
    worktree="$parent/$name-tighten-$(date +%Y-%m-%d-%H%M)"
    if [ -e "$worktree" ]; then
        echo "target already exists: $worktree" >&2
        exit 1
    fi
    if git -C "$root" rev-parse --verify "refs/heads/$branch" >/dev/null 2>&1; then
        git -C "$root" worktree add "$worktree" "$branch" >/dev/null || exit 1
    else
        git -C "$root" worktree add -b "$branch" "$worktree" "$base_sha" >/dev/null || exit 1
    fi
else
    head="$(git -C "$worktree" rev-parse HEAD 2>/dev/null || true)"
    if [ -n "$base_sha" ] && [ "$head" != "$base_sha" ]; then
        git -C "$worktree" reset --hard "$base_sha" >/dev/null || exit 1
    fi
fi

head="$(git -C "$worktree" rev-parse HEAD)"
printf 'worktree=%s\nbranch=%s\nmode=%s\nreused=no\nhead=%s\n' \
    "$worktree" "$branch" "$mode" "$head"
