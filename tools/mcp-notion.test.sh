#!/usr/bin/env bash
set -euo pipefail

tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
printf '#!/bin/sh\n[ "$1" = read ] && echo "tok-from-op:$2"\n' > "$tmp/op"
printf '#!/bin/sh\necho "$OPENAPI_MCP_HEADERS"\n' > "$tmp/npx"
chmod +x "$tmp/op" "$tmp/npx"

out="$(PATH="$tmp:$PATH" NOTION_OP_REF=op://V/I/f "$tools_dir/mcp-notion.sh")"
[[ "$out" == *'"Bearer tok-from-op:op://V/I/f"'* ]] || fail "header carries the token read via op, got: $out"
pass "header carries the token read via op"

printf '#!/bin/sh\nexit 1\n' > "$tmp/op"
if PATH="$tmp:$PATH" "$tools_dir/mcp-notion.sh" >/dev/null 2>&1; then
  fail "server must not start when op read fails"
fi
pass "op failure aborts before launching the server"
