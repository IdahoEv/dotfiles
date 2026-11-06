# Bootstrap package set (#83)

**As of 2026-11-06.** `tools/lib/packages.tsv` is the single list behind `bootstrap-linux.sh` and `bootstrap-mac.sh`. Each row maps one logical tool to its apt and brew form; `packages.test.sh` checks the file's shape. Add a tool by adding one row.

## Columns

| Column | Values |
| --- | --- |
| `tier` | `core` (the dotfiles and `tools/` call these), `dev` (language runtimes), `search` (viewers/searchers; apt installs best-effort), `cask` (macOS apps) |
| `apt` / `brew` | A package name; `installer:<id>` (apt only, handled in `bootstrap-linux.sh`); `builtin` (the OS ships it); `none` (deliberate gap) |

## Package set

| Tier | Tool | apt | brew |
| --- | --- | --- | --- |
| core | git, curl, jq, fzf, direnv, tmux, tree, shellcheck, wget | same name | same name |
| core | gh | GitHub apt repo | `gh` |
| core | oh-my-posh, chezmoi | release binary → `~/.local/bin` | `oh-my-posh`, `chezmoi` |
| core | zsh | `zsh` | built in |
| core | unzip | `unzip` | built in |
| dev | python3 | `python3` (may be < 3.13) | `python@3.13` |
| dev | uv, fnm | official installers → `~/.local/bin` | `uv`, `fnm` |
| dev | pyenv | none | `pyenv` |
| search | ripgrep, eza | same name | same name |
| search | fd | `fd-find` (binary `fdfind`, shimmed to `fd`) | `fd` |
| search | bat | `bat` (binary `batcat`, shimmed to `bat`) | `bat` |
| search | ag | `silversearcher-ag` | `the_silver_searcher` |
| search | delta | `git-delta` | `git-delta` |
| cask | iterm2, hammerspoon, 1password-cli, font-meslo-lg-nerd-font | none | same name |

## Gaps between platforms

| Gap | Platform lacking it | Why it is acceptable | Option |
| --- | --- | --- | --- |
| `pyenv` | Linux | `dot_shell_modules/python` only initializes it when present; `uv` manages Python versions on both | Leave |
| `eza`, `git-delta` | Older Ubuntu | Not in those releases' apt; reported and skipped | Install from upstream releases if wanted |
| `python3` ≥ 3.13 | Ubuntu LTS | Repo floor is 3.13 | `uv python install 3.13` |
| iTerm2, Hammerspoon | Linux/WSL | Mac-only apps | None |
| `1password-cli` | Linux | Exists for Linux via 1Password's own apt repo; nothing in the dotfiles calls `op` today | Add an installer row when needed |
| Nerd Font | Linux/WSL | Installed on the Windows side for WSL | Document only |

## Left out of both on purpose

| Category | Examples | Why |
| --- | --- | --- |
| Machine-specific `brew leaves` | emacs, exiftool, ffmpeg, go, imagemagick, nano, nmap, poetry, rlwrap, samba, tldr, watchexec | Not called by the dotfiles; add a row if a tool becomes a baseline |
| Project-specific Python | ML libraries (torch and friends) | Installed per project with `uv`; Python itself is the universal part |
| Game and docs tooling | Godot, .NET, MacTeX | Per-project or per-machine |
