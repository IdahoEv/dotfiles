# Bootstrap a fresh macOS machine (#83)

**macOS only. As of 2026-11-06.** Four commands take a blank Mac to a managed zsh shell; `tools/bootstrap-mac.sh` is idempotent and never upgrades what is installed, so re-run it to repair. The package set is `tools/lib/packages.tsv`, shared with the Linux script — see [bootstrap-packages.md](bootstrap-packages.md). Linux/WSL: [bootstrap-linux.md](bootstrap-linux.md).

## Sequence

| # | Command | Why |
| --- | --- | --- |
| 0 | `xcode-select --install` | Provides `git`, `curl`, and the compilers Homebrew needs; the script refuses to run without it |
| 1 | `curl -fsSL https://raw.githubusercontent.com/IdahoEv/dotfiles/main/tools/bootstrap-mac.sh -o /tmp/bootstrap-mac.sh` | Runs before chezmoi, so it can't come from the deploy clone; it fetches `tools/lib/packages.tsv` itself |
| 2 | `bash /tmp/bootstrap-mac.sh` | Installs Homebrew if missing, then the manifest's formulae and casks (`--skip-casks` for formulae only) |
| 3 | `chezmoi init --apply IdahoEv/dotfiles` | Prompts for git email and work-machine flag, then applies |
| 4 | `exec zsh` | Start the managed shell |

macOS already defaults to zsh, so there is no login-shell step.

## What the script does

| Step | Equivalent by hand |
| --- | --- |
| Homebrew | The [brew.sh](https://brew.sh) installer, run with `NONINTERACTIVE=1` |
| Formulae | `brew install` every manifest row whose `brew` column is a package and that is not already installed |
| Casks | `brew install --cask` the `cask` tier rows not already installed |
| Shell environment | `eval "$(brew shellenv)"` for the script's own session; `dot_zshrc.tmpl` does the same after apply |

The Homebrew installer is fetched over HTTPS without checksum verification. Packages the OS ships (`zsh`, `unzip`) are skipped. Casks are Mac apps (iTerm2, a Nerd Font, Hammerspoon, 1Password CLI); machine-specific apps such as Cursor, Godot, and MacTeX are deliberately not in the manifest.

## After the script

- Set iTerm2's font to the installed Meslo Nerd Font so the oh-my-posh theme glyphs render.
