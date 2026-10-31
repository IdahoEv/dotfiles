#!/bin/sh
# One-time migration of the per-project overlay store from its pre-rename home
# ~/.config/git-tools/ to ~/.config/project-overlays/, flattening the redundant
# projects/ level and dot-prefixing the provider dirs so they can't collide
# with an owner key. Moves directories only — no overlay content is read.
# Idempotent: every step is guarded, and a both-roots-exist conflict is
# reported and left for the user rather than merged.
set -eu

old="$HOME/.config/git-tools"
new="$HOME/.config/project-overlays"

[ -d "$old" ] || exit 0

if [ -e "$new" ]; then
  printf 'migrate-project-overlays: both %s and %s exist; not merging — move the rest by hand.\n' "$old" "$new" >&2
  exit 0
fi

mkdir -p "$new"

# Flatten projects/ first: its owner dirs become the new root's children.
if [ -d "$old/projects" ]; then
  for d in "$old/projects"/* "$old/projects"/.[!.]*; do
    [ -e "$d" ] || continue
    [ -e "$new/$(basename "$d")" ] && continue
    mv "$d" "$new/$(basename "$d")"
  done
  rmdir "$old/projects" 2>/dev/null || true
fi

# Provider dirs become hidden, so no owner key can shadow them.
for p in start-ticket-providers open-pr-providers; do
  if [ -d "$old/$p" ]; then mv "$old/$p" "$new/.$p"; fi
done

# Anything else moves across untouched.
for d in "$old"/* "$old"/.[!.]*; do
  [ -e "$d" ] || continue
  [ -e "$new/$(basename "$d")" ] && continue
  mv "$d" "$new/$(basename "$d")"
done

rmdir "$old" 2>/dev/null \
  || printf 'migrate-project-overlays: moved what it could; %s still holds files — finish by hand.\n' "$old" >&2
printf 'migrate-project-overlays: %s -> %s\n' "$old" "$new"
