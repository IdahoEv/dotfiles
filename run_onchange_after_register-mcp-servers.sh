#!/bin/sh
# Register the Notion and Shortcut MCP servers with Claude Code. Only op://
# references are stored; `op` resolves them each time the server starts.
# NOTION_OP_REF and SHORTCUT_OP_REF override the default references.
set -eu

notion_ref="${NOTION_OP_REF:-op://Personal/Notion API/credential}"
shortcut_ref="${SHORTCUT_OP_REF:-op://Personal/Shortcut API/credential}"

remove() { claude mcp remove --scope user "$1" >/dev/null 2>&1 || true; }

add() { # add <name> <json>
  remove "$1"
  claude mcp add-json --scope user "$1" "$2" >/dev/null
}

# Earlier versions stored literal tokens; scrub them whether or not op works.
cfg="${XDG_CONFIG_HOME:-$HOME/.config}/chezmoi/chezmoi.toml"
if [ -f "$cfg" ] && grep -Eq '^[[:space:]]*(notion_api_token|shortcut_api_token|anthropic_api_key)[[:space:]]*=' "$cfg"; then
  grep -Ev '^[[:space:]]*(notion_api_token|shortcut_api_token|anthropic_api_key)[[:space:]]*=' "$cfg" > "$cfg.tmp"
  cat "$cfg.tmp" > "$cfg" && rm -f "$cfg.tmp"
  echo "register-mcp: removed legacy token values from $cfg; rotate those tokens" >&2
fi
command -v claude >/dev/null 2>&1 || exit 0
remove notion
remove shortcut

command -v op >/dev/null 2>&1 || { echo "register-mcp: op not found; skipping MCP servers" >&2; exit 0; }

has_item() { op read "$1" >/dev/null 2>&1; }

# Runs only when this file changes; to retry after op signin or creating the
# item: chezmoi state delete-bucket --bucket=scriptState
if has_item "$notion_ref"; then
  add notion "{\"command\": \"$HOME/.local/bin/mcp-notion.sh\", \"env\": {\"NOTION_OP_REF\": \"$notion_ref\"}}"
else
  echo "register-mcp: cannot read $notion_ref; skipping notion" >&2
fi
if has_item "$shortcut_ref"; then
  add shortcut "{\"command\": \"op\", \"args\": [\"run\", \"--\", \"npx\", \"-y\", \"@shortcut/mcp@latest\"], \"env\": {\"SHORTCUT_API_TOKEN\": \"$shortcut_ref\"}}"
else
  echo "register-mcp: cannot read $shortcut_ref; skipping shortcut" >&2
fi
