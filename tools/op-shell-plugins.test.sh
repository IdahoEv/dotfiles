#!/usr/bin/env bash
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$tools_dir")"
module="$repo/dot_shell_modules/1password.tmpl"
config="$repo/.chezmoi.toml.tmpl"

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
render() { # render <toml data lines>
  printf '[data]\n%s\n' "$1" > "$tmp/chezmoi.toml"
  chezmoi --config "$tmp/chezmoi.toml" --source "$tmp" execute-template < "$module"
}
guarded='if [[ -f ~/.config/op/plugins.sh ]]; then source ~/.config/op/plugins.sh; fi'

out="$(render 'op_shell_plugins = true')"
[[ "$out" == "$guarded" ]] || fail "true renders the file-guarded source line, got: $out"
pass "true renders the file-guarded source line"

out="$(render 'op_shell_plugins = false')"
[[ -z "$out" ]] || fail "false renders nothing, got: $out"
pass "false renders nothing"

out="$(render '')"
[[ -z "$out" ]] || fail "absent key renders nothing, got: $out"
pass "absent key renders nothing"

: > "$tmp/empty.toml"
init_out="$(chezmoi --config "$tmp/empty.toml" --source "$tmp" execute-template --init \
  --promptBool "Enable 1Password CLI shell plugins=true,Is this a work machine=false" \
  --promptString "Git email=a@b.c" < "$config")"
grep -q '^op_shell_plugins = true$' <<< "$init_out" || fail "config template emits op_shell_plugins"
pass "config template emits op_shell_plugins"

rendered="$tmp/rendered.sh"
render 'op_shell_plugins = true' > "$rendered"
mkdir -p "$tmp/home/.config/op"
out="$(HOME="$tmp/home" bash -c 'source "$1"; echo "rc=$?"' _ "$rendered" 2>&1)"
[[ "$out" == "rc=0" ]] || fail "missing plugins.sh sources cleanly with status 0, got: $out"
pass "missing plugins.sh sources cleanly with status 0"

echo 'echo sourced' > "$tmp/home/.config/op/plugins.sh"
out="$(HOME="$tmp/home" bash -c 'source "$1"; echo "rc=$?"' _ "$rendered" 2>&1)"
[[ "$out" == $'sourced\nrc=0' ]] || fail "present plugins.sh is sourced, got: $out"
pass "present plugins.sh is sourced"
