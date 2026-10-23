## Working agreement (dotfiles repo)

- This repo is the source of `~/.claude` (`dot_claude/` → `~/.claude`) and of `tools/`. Read `CLAUDE.md` for the layout.
- Load `/workflow` before editing `dot_claude/`, `.claude/`, hooks, or settings. Where it says the chezmoi source dir is the working copy, or that the dotfiles repo is never committed, this repo overrides it.
- Edit only in this worktree. Never edit `~/.local/share/chezmoi`; it is the deploy clone, main only.
- Changes go ticket → branch → PR. Commit here, after review.
