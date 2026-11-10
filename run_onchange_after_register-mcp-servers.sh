#!/bin/sh
# Register the Notion and Shortcut MCP servers with Claude Code. Only op://
# references are stored; `op` resolves them each time the server starts.
# SHORTCUT_OP_REF overrides the default reference.
set -eu

command -v claude >/dev/null 2>&1 || exit 0
command -v op >/dev/null 2>&1 || { echo "register-mcp: op not found; skipping MCP servers" >&2; exit 0; }

notion_ref="${NOTION_OP_REF:-op://Personal/Notion API/credential}"
shortcut_ref="${SHORTCUT_OP_REF:-op://Personal/Shortcut API/credential}"

add() { # add <name> <json>
  claude mcp remove --scope user "$1" >/dev/null 2>&1 || true
  claude mcp add-json --scope user "$1" "$2" >/dev/null
}

has_item() { op read "$1" >/dev/null 2>&1; }

if has_item "$notion_ref"; then
  add notion "{\"command\": \"$HOME/.local/bin/mcp-notion.sh\"}"
fi
if has_item "$shortcut_ref"; then
  add shortcut "{\"command\": \"op\", \"args\": [\"run\", \"--\", \"npx\", \"-y\", \"@shortcut/mcp@latest\"], \"env\": {\"SHORTCUT_API_TOKEN\": \"$shortcut_ref\"}}"
fi
