#!/usr/bin/env bash
# Launch the Notion MCP server with its token read from 1Password at start-up,
# so the token never lands in ~/.claude.json or the chezmoi data.
# NOTION_OP_REF overrides the default op:// reference.
set -euo pipefail

ref="${NOTION_OP_REF:-op://Personal/Notion API/credential}"
token="$(op read "$ref")"
OPENAPI_MCP_HEADERS="$(printf '{"Authorization": "Bearer %s", "Notion-Version": "2022-06-28"}' "$token")"
export OPENAPI_MCP_HEADERS
exec npx -y @notionhq/notion-mcp-server
