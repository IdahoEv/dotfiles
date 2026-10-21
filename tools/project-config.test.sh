#!/usr/bin/env bash
# project-config.test.sh — behavioral checks for the per-project config overlay
# (gt::overlay_dir / gt::conf_get / gt::find_doc and project-config.sh).
#
#   project-config.test.sh
#
# Plain script, exits non-zero on failure. HOME is a temp dir so the real
# ~/.config can't leak in.

set -uo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/project-config-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME"
unset GIT_TOOLS_PROJECTS_DIR
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
# shellcheck source=lib/repo-facts.sh
. "$TOOLS/lib/repo-facts.sh"
PC="$TOOLS/project-config.sh"
PROJ="$HOME/.config/git-tools/projects"

# ---- repo_key ----------------------------------------------------------------
check "key: scp ssh"       "o/r" "$(gt::repo_key git@github.com:o/r.git)"
check "key: https .git"    "o/r" "$(gt::repo_key https://github.com/o/r.git)"
check "key: https bare"    "o/r" "$(gt::repo_key https://github.com/o/r)"
check "key: ssh://"        "o/r" "$(gt::repo_key ssh://git@host:22/o/r.git)"
check "key: trailing /"    "o/r" "$(gt::repo_key https://github.com/o/r/)"
check "key: local path"    ""    "$(gt::repo_key /srv/git/r.git)"
check "key: subgroups"     "g/sub/r" "$(gt::repo_key https://gitlab.com/g/sub/r.git)"
check "key: .. rejected"   ""    "$(gt::repo_key 'git@h:../r')"
check "key: dot dir rejected" "" "$(gt::repo_key 'git@h:o/.hidden')"

# ---- fixture: repo with origin, plus a linked worktree -------------------------
git init -q "$ROOT/repo"
git -C "$ROOT/repo" commit -q --allow-empty -m init
git -C "$ROOT/repo" remote add origin git@github.com:acme/widgets.git
git -C "$ROOT/repo" worktree add -q "$ROOT/wt" -b feature
OV="$PROJ/acme/widgets"

check "overlay dir"          "$OV" "$(gt::overlay_dir "$ROOT/repo")"
check "overlay dir, worktree" "$OV" "$(gt::overlay_dir "$ROOT/wt")"
git init -q "$ROOT/bare-less"
check "no origin -> empty"   ""    "$(gt::overlay_dir "$ROOT/bare-less")"
check "GIT_TOOLS_PROJECTS_DIR" "$ROOT/elsewhere/acme/widgets" \
  "$(GIT_TOOLS_PROJECTS_DIR="$ROOT/elsewhere" gt::overlay_dir "$ROOT/repo")"

# ---- conf: repo > overlay > machine, per key -----------------------------------
mkdir -p "$OV" "$HOME/.config/start-ticket"
printf 'provider=shortcut\nlabel_noise=acme\n' > "$OV/start-ticket.conf"
printf 'launcher=bg\nlabel_noise=machine\n'    > "$HOME/.config/start-ticket/config"
check "overlay beats machine"   "acme"     "$(gt::conf_get label_noise "$ROOT/repo")"
check "machine fills the rest"  "bg"       "$(gt::conf_get launcher "$ROOT/repo")"
check "overlay-only key"        "shortcut" "$(gt::conf_get provider "$ROOT/repo")"
printf 'provider=github\n' > "$ROOT/repo/.start-ticket.conf"
check "repo beats overlay"      "github"   "$(gt::conf_get provider "$ROOT/repo")"
check "overlay still fills"     "acme"     "$(gt::conf_get label_noise "$ROOT/repo")"
check "worktree sees main-root conf" "github" "$(gt::conf_get provider "$ROOT/wt")"
check "worktree sees overlay"   "acme"     "$(gt::conf_get label_noise "$ROOT/wt")"
gt::conf_get nosuchkey "$ROOT/repo" >/dev/null; check "unset key -> rc 1" "1" "$?"

# ---- docs: repo file replaces overlay outright ---------------------------------
echo overlay-gov > "$OV/governor.md"
check "doc from overlay" "$OV/governor.md	overlay" "$(gt::find_doc governor.md "$ROOT/repo")"
mkdir -p "$ROOT/repo/.claude"; echo repo-gov > "$ROOT/repo/.claude/governor.md"
check "repo doc wins"    "$ROOT/repo/.claude/governor.md	repo" "$(gt::find_doc governor.md "$ROOT/repo")"
gt::find_doc missing.md "$ROOT/repo" >/dev/null; check "missing doc -> rc 1" "1" "$?"

# ---- project-config.sh -----------------------------------------------------------
git init -q "$ROOT/repo2"
git -C "$ROOT/repo2" remote add origin https://github.com/acme/gadgets.git
OV2="$PROJ/acme/gadgets"
check "dir"  "$OV2" "$(cd "$ROOT/repo2" && "$PC" dir)"
(cd "$ROOT/repo2" && "$PC" find governor.md >/dev/null 2>&1); check "find: absent -> rc 1" "1" "$?"
(cd "$ROOT/repo2" && "$PC" init >/dev/null 2>&1)
check "init writes governor.md" "yes" "$([ -f "$OV2/governor.md" ] && echo yes)"
check "init writes conf"        "yes" "$([ -f "$OV2/start-ticket.conf" ] && echo yes)"
echo mine > "$OV2/governor.md"
(cd "$ROOT/repo2" && "$PC" init >/dev/null 2>&1)
check "init never overwrites" "mine" "$(cat "$OV2/governor.md")"
check "find after init" "$OV2/governor.md	overlay" "$(cd "$ROOT/repo2" && "$PC" find governor.md)"
check "project checkout stays clean" "" "$(git -C "$ROOT/repo2" status --porcelain)"
(cd "$ROOT/bare-less" && "$PC" dir >/dev/null 2>&1); check "dir without origin -> rc 1" "1" "$?"

# ---- store-init ------------------------------------------------------------------
"$PC" store-init git@work.example:me/cfg.git >/dev/null
check "store is a repo"   "yes" "$([ -d "$PROJ/.git" ] && echo yes)"
check "store origin"      "git@work.example:me/cfg.git" "$(git -C "$PROJ" remote get-url origin)"
"$PC" store-init git@other.example:x/y.git >/dev/null
check "origin not replaced" "git@work.example:me/cfg.git" "$(git -C "$PROJ" remote get-url origin)"
check "store has no commits" "0" "$(git -C "$PROJ" rev-list --all --count)"
check "store sees projects"  "yes" "$(git -C "$PROJ" status --porcelain | grep -q acme && echo yes)"

# ---- start-ticket.sh kickoff uses the overlay preamble -----------------------------
STP="$ROOT/stp"; mkdir -p "$STP"
cat > "$STP/fake.sh" <<'P'
provider::available() { return 0; }
provider::fetch() { ST_TITLE="Fake ticket"; ST_BODY="body"; ST_URL=""; ST_PARENT=""; }
provider::create_worktree() { echo "$FAKE_WT"; }
provider::mark_in_progress() { return 0; }
P
echo 'Overlay rules for {{ID}} on {{BRANCH}}.' > "$OV2/kickoff-preamble.md"
run_start() {
  (cd "$ROOT/repo2" && FAKE_WT="$ROOT/repo2" START_TICKET_PROVIDER_DIR="$STP" TMPDIR="$ROOT" \
     "$TOOLS/start-ticket.sh" 7 --provider fake --no-tab) >/dev/null
  cat "$ROOT/gadgets-kickoff-7.md" 2>/dev/null
}
out="$(run_start)"
case "$out" in *"Overlay rules for 7 on "*) r=yes ;; *) r=no ;; esac
check "kickoff includes overlay preamble" "yes" "$r"
mkdir -p "$ROOT/repo2/.claude"; echo 'Repo rules.' > "$ROOT/repo2/.claude/kickoff-preamble.md"
out="$(run_start)"
case "$out" in *"Repo rules."*) a=yes ;; *) a=no ;; esac
case "$out" in *"Overlay rules"*) b=leaked ;; *) b=ok ;; esac
check "repo preamble wins"           "yes" "$a"
check "overlay preamble not merged"  "ok"  "$b"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
