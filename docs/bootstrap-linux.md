# Bootstrap a fresh Linux/WSL machine (#83)

**Debian/Ubuntu/WSL only. As of 2026-11-02.** Four commands take a blank machine to a managed zsh shell; `tools/bootstrap-linux.sh` is idempotent, so re-run it to repair.

## Sequence

| # | Command | Why |
| --- | --- | --- |
| 0 | `sudo apt update && sudo apt install -y curl git` | Needed to fetch the script and for chezmoi itself |
| 1 | `curl -fsSL https://raw.githubusercontent.com/IdahoEv/dotfiles/main/tools/bootstrap-linux.sh -o /tmp/bootstrap-linux.sh` | Runs before chezmoi, so it can't come from the deploy clone |
| 2 | `bash /tmp/bootstrap-linux.sh` | Installs packages, `gh`, `oh-my-posh`, `chezmoi`; sets zsh as login shell |
| 3 | `exec zsh` | Pick up `~/.local/bin` and the new shell (a full WSL restart makes `chsh` take effect for new terminals) |
| 4 | `~/.local/bin/chezmoi init --apply IdahoEv/dotfiles` | Prompts for git email and work-machine flag, then applies |

Step 4 writes `~/.config/chezmoi/chezmoi.toml` from `.chezmoi.toml.tmpl`. Machines that already have that file are not re-prompted.

## What the script does

| Step | Equivalent by hand |
| --- | --- |
| Baseline packages | `sudo apt-get install -y zsh fzf direnv unzip tmux git curl` |
| `gh` | [GitHub's apt repo instructions](https://github.com/cli/cli/blob/trunk/docs/install_linux.md); skip with `--skip-gh` |
| `oh-my-posh` | Download `posh-linux-<arch>` from the latest [release](https://github.com/JanDeDobbeleer/oh-my-posh/releases) to `~/.local/bin/oh-my-posh`, `chmod +x` |
| `chezmoi` | Download `chezmoi-linux-<arch>` from the latest [release](https://github.com/twpayne/chezmoi/releases) to `~/.local/bin/chezmoi`, `chmod +x` |
| Login shell | `sudo chsh -s "$(command -v zsh)" "$USER"` |

Release binaries are fetched over HTTPS without checksum verification. Only `amd64` and `arm64` are supported.

## WSL notes

- **Bash default:** WSL launches the `/etc/passwd` login shell, so `chsh` to zsh bypasses the distro's unmanaged `~/.bashrc`.
- **IPv6 stalls:** if outbound calls (including this script's downloads) hang on an unrouted IPv6 path, prefer IPv4:

  ```sh
  echo 'precedence ::ffff:0:0/96  100' | sudo tee -a /etc/gai.conf
  ```

  This is a system-wide resolver setting, so the script does not change it.
- **No `oh-my-posh`:** zsh falls back to a plain `user@host dir %` prompt rather than the inherited bash `PS1`.
