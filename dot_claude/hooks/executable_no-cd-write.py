#!/usr/bin/env python3
"""PreToolUse hook: deny compound `cd` + write/redirect Bash commands.

Claude Code's Bash tool hard-codes an `ask` for any compound command that
combines `cd` with output redirection or a write operation, because it cannot
statically resolve the final working directory. That check runs before the
permission allowlist, so such commands can never be auto-approved -- they
always interrupt with a manual prompt.

An absolute-path rewrite is always available and behaves identically, so
denying here costs nothing and converts a blocking prompt into an immediate
self-correction the model can act on without the user.

Narrow by construction: fires only on the exact shapes the binary would stop
anyway. A plain `cd`, a redirect without `cd`, or a `/dev/null` redirect all
pass through untouched.
"""

import json
import re
import sys

# Mirrors the binary's exemption: `> /dev/null` is not a real write target.
REDIRECT = re.compile(r"(?<![0-9<>&])>>?\s*(?!/dev/null\b)(\S+)")
WRITE_CMD = re.compile(
    r"(?:^|[;&|]|\b(?:then|do|else)\s)\s*"
    r"(?:sudo\s+)?(cp|mv|rm|rmdir|touch|mkdir|tee|dd|ln|install|truncate)\b"
)
# `cd` as the head of a segment, in a command that has more than one segment.
CD_SEGMENT = re.compile(r"(?:^|[;&|]|\b(?:then|do|else)\s)\s*(?:cd|pushd)\s+\S")
COMPOUND = re.compile(r"&&|\|\||[;|]")

GUIDANCE = (
    "Blocked: `cd` combined with a write or output redirection in one compound "
    "command. Claude Code always requires manual approval for this shape (it "
    "cannot statically resolve the final working directory), so it will stall "
    "waiting on the user no matter what the permission allowlist says.\n"
    "Rewrite without `cd` -- every tool here takes absolute paths:\n"
    "  - reading a file or a line range -> use the Read tool with "
    "offset/limit, not `sed -n`/`cat`/`head`/`tail`\n"
    "  - searching code -> use the Grep tool, not `rg`/`grep`\n"
    "  - running a command elsewhere -> pass the absolute path as an argument "
    "(`rg PATTERN /abs/dir`, `yarn --cwd /abs/dir test`)\n"
    "Do not collect output into a /tmp file to read back: that is two blocking "
    "steps where the Read and Grep tools are zero."
)


def should_block(command: str) -> bool:
    if not COMPOUND.search(command) or not CD_SEGMENT.search(command):
        return False
    return bool(REDIRECT.search(command) or WRITE_CMD.search(command))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # Never block on a malformed event.

    if payload.get("tool_name") != "Bash":
        return 0
    command = payload.get("tool_input", {}).get("command", "")
    if not isinstance(command, str) or not should_block(command):
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": GUIDANCE,
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
