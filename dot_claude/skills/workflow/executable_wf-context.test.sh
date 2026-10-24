#!/usr/bin/env bash
# wf-context.test.sh — behavioral checks for wf-context.sh.
#
#   wf-context.test.sh
#
# Plain script, exits non-zero on failure. HOME is a temp dir so the real
# ~/.config can't leak in; chezmoi is stubbed on PATH. Run the source copy,
# never the deployed ~/.claude one (that is the version being replaced).

set -uo pipefail
SKILL_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WC="$SKILL_DIR/executable_wf-context.sh"
TOOLS_DIR="$(cd "$SKILL_DIR/../../.." && pwd)/tools"
[ -d "$TOOLS_DIR" ] || TOOLS_DIR="$HOME/.local/share/chezmoi/tools"
pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

has() {  # <description> <text> <fixed string>
  case "$2" in *"$3"*) r=yes ;; *) r=no ;; esac
  check "$1" yes "$r"
}

fact() { printf '%s\n' "$1" | sed -n "s/^$2=//p" | head -1; }

ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/wf-context-test.XXXXXX")" && pwd)"
trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"; mkdir -p "$HOME"
export TMPDIR="$ROOT/tmp"; mkdir -p "$TMPDIR"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
unset GIT_TOOLS_PROJECTS_DIR CLAUDE_JOB_DIR CHEZMOI_BROKEN_SOURCE

# ---- fixtures ---------------------------------------------------------------
ORIGIN="$ROOT/origin.git"
git init -q --bare -b main "$ORIGIN"
WORK="$ROOT/work"
git clone -q "$ORIGIN" "$WORK" 2>/dev/null || {
  git init -q -b main "$WORK"; git -C "$WORK" remote add origin "$ORIGIN"; }
mkdir -p "$WORK/dot_claude/skills/workflow"
printf '# ignored\n' > "$WORK/.chezmoiignore"
printf 'global claude\n' > "$WORK/dot_claude/CLAUDE.md.tmpl"
printf '{}\n' > "$WORK/dot_claude/modify_private_settings.json.tmpl"
printf 'skill\n' > "$WORK/dot_claude/skills/workflow/SKILL.md"
git -C "$WORK" add -A
git -C "$WORK" commit -q -m init
git -C "$WORK" push -q -u origin main

# The deploy clone lives at the path wf-context.sh hard-codes for tools/.
DEPLOY="$HOME/.local/share/chezmoi"
git clone -q "$ORIGIN" "$DEPLOY"
git -C "$DEPLOY" config pull.rebase true
ln -s "$TOOLS_DIR" "$DEPLOY/tools"
printf 'tools\n' >> "$DEPLOY/.git/info/exclude"   # keep the symlink out of dirty counts

# Advance origin so the deploy clone is one behind it.
printf 'later\n' > "$WORK/later.txt"
git -C "$WORK" add -A
git -C "$WORK" commit -q -m later
git -C "$WORK" push -q

# A separate dev clone with a ticket worktree: two commits ahead, no upstream.
DEV="$ROOT/devsrc"
git clone -q "$ORIGIN" "$DEV"
git -C "$DEV" worktree add -q --no-track -b ticket "$ROOT/ticket" origin/main
printf 'a\n' > "$ROOT/ticket/a.txt"
git -C "$ROOT/ticket" add -A
git -C "$ROOT/ticket" commit -q -m a
printf 'b\n' > "$ROOT/ticket/b.txt"
git -C "$ROOT/ticket" add -A
git -C "$ROOT/ticket" commit -q -m b

PLAIN="$ROOT/plain"
git init -q -b main "$PLAIN"
git -C "$PLAIN" commit -q --allow-empty -m init

B="$ROOT/bare"
git clone -q --bare "$ORIGIN" "$B/.bare"
printf 'gitdir: ./.bare\n' > "$B/.git"
git -C "$B" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git -C "$B" worktree add -q "$B/main" main

# ---- chezmoi stub -----------------------------------------------------------
BIN="$ROOT/bin"; mkdir -p "$BIN"
cat > "$BIN/chezmoi" <<'SH'
#!/usr/bin/env bash
src=""; args=()
while [ $# -gt 0 ]; do
  case "$1" in
    -S|--source) src="$2"; shift 2 ;;
    *) args+=("$1"); shift ;;
  esac
done
[ -n "$src" ] || src="${CHEZMOI_DEPLOY:-}"
printf 'src=%s args=%s\n' "$src" "${args[*]-}" >> "$CHEZMOI_LOG"
set -- ${args[@]+"${args[@]}"}
cmd="${1:-}"; shift || true
case "$cmd" in
  source-path)
    [ "${CHEZMOI_BROKEN_SOURCE:-}" = "$src" ] && [ $# -gt 0 ] && exit 1
    if [ $# -eq 0 ]; then printf '%s\n' "$src"; exit 0; fi
    [ "${1:-}" = -- ] && shift
    rel="${1:-}"; rel="${rel#"$HOME"/.claude/}"
    case "$rel" in
      CLAUDE.md)      cand="dot_claude/CLAUDE.md.tmpl" ;;
      settings.json)  cand="dot_claude/modify_private_settings.json.tmpl" ;;
      *)              cand="dot_claude/$rel" ;;
    esac
    [ -e "$src/$cand" ] && { printf '%s\n' "$src/$cand"; exit 0; }
    exit 1 ;;
  managed)
    [ "${CHEZMOI_BROKEN_SOURCE:-}" = "$src" ] && exit 1
    printf '.claude\n'; exit 0 ;;
esac
exit 1
SH
chmod +x "$BIN/chezmoi"
export CHEZMOI_DEPLOY="$DEPLOY" CHEZMOI_LOG="$ROOT/chezmoi.log"

run_facts()       { (cd "$1" && PATH="$BIN:$PATH" "$WC" 2>/dev/null); }
run_srcpath()     { (cd "$1" && PATH="$BIN:$PATH" "$WC" srcpath "$2" 2>&1); }
run_srcpath_rc()  { (cd "$1" && PATH="$BIN:$PATH" "$WC" srcpath "$2" >/dev/null 2>&1); echo $?; }
PURE_PATH="/usr/bin:/bin:/usr/sbin:/sbin"
run_nochezmoi()      { (cd "$1" && PATH="$PURE_PATH" "$WC" 2>/dev/null); }
run_nochezmoi_rc()   { (cd "$1" && PATH="$PURE_PATH" "$WC" srcpath "$2" >/dev/null 2>&1); echo $?; }

# ---- dev worktree -----------------------------------------------------------
out="$(run_facts "$ROOT/ticket")"
check "dev: source kind"          dev             "$(fact "$out" dotfiles_source)"
check "dev: source root"          "$ROOT/ticket"  "$(fact "$out" chezmoi_source_root)"
check "dev: deploy root"          "$DEPLOY"       "$(fact "$out" chezmoi_deploy_root)"
check "dev: compare ref"          origin/main     "$(fact "$out" chezmoi_source_compare_ref)"
check "dev: ahead (no upstream)"  2               "$(fact "$out" chezmoi_source_ahead_origin)"
check "dev: behind"               0               "$(fact "$out" chezmoi_source_behind_origin)"
check "dev: deploy behind"        1               "$(fact "$out" chezmoi_deploy_behind_origin)"
check "dev: deploy branch"        main            "$(fact "$out" chezmoi_deploy_branch)"
check "dev: claude md source"     "$ROOT/ticket/dot_claude/CLAUDE.md.tmpl" \
  "$(fact "$out" chezmoi_claude_md_source)"
check "dev: settings source kind" modify          "$(fact "$out" chezmoi_settings_source_kind)"

mkdir -p "$ROOT/ticket/sub"
out="$(run_facts "$ROOT/ticket/sub")"
check "subdir: still dev"   dev            "$(fact "$out" dotfiles_source)"
check "subdir: worktree root" "$ROOT/ticket" "$(fact "$out" chezmoi_source_root)"

printf 'x\n' > "$ROOT/ticket/untracked.txt"
out="$(run_facts "$ROOT/ticket")"
check "dev dirty only"      1 "$(fact "$out" chezmoi_source_dirty_files)"
check "deploy still clean"  0 "$(fact "$out" chezmoi_deploy_dirty_files)"
rm "$ROOT/ticket/untracked.txt"
printf 'y\n' > "$DEPLOY/untracked.txt"
out="$(run_facts "$ROOT/ticket")"
check "deploy dirty only"   1 "$(fact "$out" chezmoi_deploy_dirty_files)"
check "source still clean"  0 "$(fact "$out" chezmoi_source_dirty_files)"
rm "$DEPLOY/untracked.txt"

# ---- deploy, plain, bare ----------------------------------------------------
out="$(run_facts "$DEPLOY")"
check "deploy: source kind" deploy   "$(fact "$out" dotfiles_source)"
check "deploy: source root" "$DEPLOY" "$(fact "$out" chezmoi_source_root)"

out="$(run_facts "$PLAIN")"
check "plain: source kind"       none    "$(fact "$out" dotfiles_source)"
check "plain: source is deploy"  "$DEPLOY" "$(fact "$out" chezmoi_source_root)"

out="$(run_facts "$B/main")"
check "bare main: source kind" dev      "$(fact "$out" dotfiles_source)"
check "bare main: root"        "$B/main" "$(fact "$out" chezmoi_source_root)"
out="$(run_facts "$B")"
check "bare container: none"   none     "$(fact "$out" dotfiles_source)"

# ---- srcpath ----------------------------------------------------------------
check "srcpath rc 0"   0 "$(run_srcpath_rc "$ROOT/ticket" "$HOME/.claude/CLAUDE.md")"
check "srcpath worktree path" "$ROOT/ticket/dot_claude/CLAUDE.md.tmpl" \
  "$(run_srcpath "$ROOT/ticket" "$HOME/.claude/CLAUDE.md")"
check "srcpath settings" "$ROOT/ticket/dot_claude/modify_private_settings.json.tmpl" \
  "$(run_srcpath "$ROOT/ticket" "$HOME/.claude/settings.json")"

printf 'deploy only\n' > "$DEPLOY/dot_claude/deploy-only.md"
check "srcpath rc 1 elsewhere" 1 "$(run_srcpath_rc "$ROOT/ticket" "$HOME/.claude/deploy-only.md")"
out="$(run_srcpath "$ROOT/ticket" "$HOME/.claude/deploy-only.md")"
has "rc 1 names the deploy path" "$out" "$DEPLOY/dot_claude/deploy-only.md"
rm "$DEPLOY/dot_claude/deploy-only.md"

export CHEZMOI_BROKEN_SOURCE="$ROOT/ticket"
out="$(run_facts "$ROOT/ticket")"
check "broken worktree: unhealthy"      no  "$(fact "$out" chezmoi_healthy)"
check "broken worktree: deploy healthy" yes "$(fact "$out" chezmoi_deploy_healthy)"
check "broken worktree: srcpath rc 3"   3 "$(run_srcpath_rc "$ROOT/ticket" "$HOME/.claude/CLAUDE.md")"
unset CHEZMOI_BROKEN_SOURCE

out="$(run_nochezmoi "$ROOT/ticket")"
check "no chezmoi: available"   no  "$(fact "$out" chezmoi_available)"
check "no chezmoi: markers say dev" dev "$(fact "$out" dotfiles_source)"
check "no chezmoi: srcpath rc 2" 2 "$(run_nochezmoi_rc "$ROOT/ticket" "$HOME/.claude/CLAUDE.md")"

# Dev-mode checkout with no origin: the source itself has nothing to compare to
# (in `none` mode the source is the deploy clone, which does have one).
NOORIG="$ROOT/no-origin-dotfiles"
git init -q -b main "$NOORIG"
mkdir -p "$NOORIG/dot_claude"
printf '# x\n' > "$NOORIG/.chezmoiignore"
printf 'x\n' > "$NOORIG/dot_claude/CLAUDE.md.tmpl"
git -C "$NOORIG" add -A
git -C "$NOORIG" commit -q -m x
out="$(run_facts "$NOORIG")"
check "no origin: source kind" dev "$(fact "$out" dotfiles_source)"
case "$out" in *"chezmoi_source_ahead_origin="*) r=yes ;; *) r=no ;; esac
check "no origin: counts absent, not zero" no "$r"
check "no origin: pull.rebase still reported" unset "$(fact "$out" chezmoi_source_pull_rebase)"

# ---- help and read-only -----------------------------------------------------
has "help documents srcpath" "$("$WC" --help)" "srcpath"
before="$(git -C "$DEPLOY" status --porcelain)"
run_facts "$ROOT/ticket" >/dev/null
check "facts run leaves deploy worktree clean" "$before" "$(git -C "$DEPLOY" status --porcelain)"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
