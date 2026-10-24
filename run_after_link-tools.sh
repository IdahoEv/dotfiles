#!/bin/sh
# Symlink tools/*.sh into ~/.local/bin so they resolve without the zshrc's PATH
# module. Symlinks keep the scripts running in place, so their lib/ and
# provider lookups still work.
set -eu

# Always the deploy clone: a `chezmoi -S <worktree> apply` must not leave
# permanent links pointing at a worktree that /finalize later deletes.
src="$HOME/.local/share/chezmoi/tools"
[ -d "$src" ] || exit 0
bin="$HOME/.local/bin"
mkdir -p "$bin"

for script in "$src"/*.sh; do
  [ -e "$script" ] || continue
  case "$script" in *.test.sh) continue ;; esac
  target="$bin/$(basename "$script")"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    echo "link-tools: $target exists and is not a symlink; skipping" >&2
    continue
  fi
  ln -sfn "$script" "$target"
done

# Drop links to scripts that were renamed or deleted.
for link in "$bin"/*; do
  [ -L "$link" ] || continue
  case "$(readlink "$link")" in
    "$src"/*) [ -e "$link" ] || rm "$link" ;;
  esac
done
