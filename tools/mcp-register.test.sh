#!/usr/bin/env bash
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$tools_dir")"
pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

chezmoi execute-template --init --promptString homeDir=/h < "$repo/dot_claude/modify_private_settings.json.tmpl" > "$tmp/modify.py" 2>/dev/null \
  || sed 's/{{ \.chezmoi\.homeDir }}/\/h/g' "$repo/dot_claude/modify_private_settings.json.tmpl" > "$tmp/modify.py"

old='{"mcpServers":{"notion":{"env":{"T":"Bearer secret-tok"}},"shortcut":{"env":{"SHORTCUT_API_TOKEN":"secret-tok"}}},"theme":"x"}'
out="$(printf '%s' "$old" | python3 "$tmp/modify.py")"
[[ "$out" != *secret-tok* ]] || fail "modify script drops literal tokens from mcpServers"
[[ "$out" != *mcpServers* ]] || fail "empty mcpServers key is removed"
pass "modify script scrubs retired notion/shortcut servers"

out="$(printf '%s' '{"mcpServers":{"other":{"command":"x"}}}' | python3 "$tmp/modify.py")"
[[ "$out" == *'"other"'* ]] || fail "unrelated MCP servers are preserved"
pass "modify script keeps unrelated MCP servers"

mkdir "$tmp/bin"
printf '#!/bin/sh\necho "$@" >> "%s/claude.log"\n' "$tmp" > "$tmp/bin/claude"
printf '#!/bin/sh\n[ "$1" = read ] && [ "${OP_OK:-1}" = 1 ]\n' > "$tmp/bin/op"
chmod +x "$tmp/bin/claude" "$tmp/bin/op"

PATH="$tmp/bin:$PATH" HOME=/h SHORTCUT_OP_REF=op://V/S/f "$repo/run_onchange_after_register-mcp-servers.sh"
log="$(cat "$tmp/claude.log")"
[[ "$log" == *'add-json --scope user shortcut'*'op://V/S/f'* ]] || fail "shortcut registered with op ref, got: $log"
[[ "$log" == *'add-json --scope user notion'*'/h/.local/bin/mcp-notion.sh'*'NOTION_OP_REF'* ]] || fail "notion registered via wrapper, got: $log"
pass "registers both servers with op references only"

rm "$tmp/claude.log"
err="$(PATH="$tmp/bin:$PATH" OP_OK=0 "$repo/run_onchange_after_register-mcp-servers.sh" 2>&1 >/dev/null)"
! grep -q add-json "$tmp/claude.log" || fail "nothing registered when op cannot read items"
grep -q 'mcp remove --scope user notion' "$tmp/claude.log" || fail "retired entries removed even when op is unavailable"
[[ "$err" == *'skipping notion'* && "$err" == *'skipping shortcut'* ]] || fail "skip warns on stderr, got: $err"
pass "unreadable items skip with a warning"

mkdir -p "$tmp/home/.config/chezmoi"
printf '[data]\n  email = "a@b"\n  notion_api_token = "secret-tok"\n  anthropic_api_key = "secret-tok"\n' > "$tmp/home/.config/chezmoi/chezmoi.toml"
PATH="$tmp/bin:$PATH" HOME="$tmp/home" XDG_CONFIG_HOME= "$repo/run_onchange_after_register-mcp-servers.sh" 2>/dev/null
toml="$(cat "$tmp/home/.config/chezmoi/chezmoi.toml")"
[[ "$toml" != *secret-tok* && "$toml" == *'a@b'* ]] || fail "legacy token lines scrubbed from chezmoi.toml, got: $toml"
pass "scrubs legacy tokens from an existing chezmoi.toml"
