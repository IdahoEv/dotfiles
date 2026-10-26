"""Usage adapter: Claude Code session transcripts -> token usage and test timings.

The only module that reads Claude Code's on-disk formats, so a format change is
fixed here. Transcripts are internal files, not a documented API: fields that
are missing come back as None rather than guessed.

Layout read:
  <projects>/<munged-cwd>/<session_id>.jsonl                      main session
  <projects>/<munged-cwd>/<session_id>/subagents/agent-*.jsonl    subagents
  .../agent-*.meta.json                                           {"agentType": ...}
"""

import glob
import hashlib
import json
import os
import re
from datetime import datetime

# Matches a test runner in command position (start, or after ; && || | or a
# newline, past any VAR=value prefixes), so `grep foo x.test.sh` doesn't count.
DEFAULT_TEST_RE = (
    r"(?:^|[;&|\n])\s*(?:\w+=\S*\s+)*(?:\S*/)?"
    r"(?:pytest|jest|vitest|bats|dotnet test|go test|cargo test|rspec|[\w.-]+\.test\.sh"
    r"|(?:npm|yarn|pnpm|bun) (?:run )?test|npx (?:jest|vitest)|python3? -m (?:unittest|pytest))\b"
)


def projects_root():
    return os.environ.get("WF_CLAUDE_PROJECTS", os.path.expanduser("~/.claude/projects"))


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def transcripts_for_session(session_id, root=None):
    """[(path, agent_type or None)] — main transcript first, then subagents."""
    root = root or projects_root()
    if not re.fullmatch(r"[0-9A-Za-z-]+", session_id or ""):
        return []
    out = [(p, None) for p in glob.glob(os.path.join(root, "*", session_id + ".jsonl"))]
    for p in sorted(glob.glob(os.path.join(root, "*", session_id, "subagents", "agent-*.jsonl"))):
        agent_type = None
        try:
            with open(p[: -len(".jsonl")] + ".meta.json") as fh:
                agent_type = json.load(fh).get("agentType")
        except (OSError, ValueError):
            pass
        out.append((p, agent_type or "unknown"))
    return out


def _entries(path):
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def read_usage(path, agent_type=None):
    """One record per API message; streamed chunks repeat message.id with identical usage."""
    seen = set()
    for e in _entries(path):
        if e.get("type") != "assistant":
            continue
        msg = e.get("message") or {}
        usage = msg.get("usage")
        model = msg.get("model")
        if not usage or not model or model == "<synthetic>":
            continue
        mid = msg.get("id") or e.get("requestId") or e.get("uuid")
        if mid in seen:
            continue
        seen.add(mid)
        cc = usage.get("cache_creation") or {}
        write_total = usage.get("cache_creation_input_tokens") or 0
        write_1h = cc.get("ephemeral_1h_input_tokens") or 0
        yield {
            "id": mid,
            "ts": parse_ts(e.get("timestamp")),
            "model": model,
            "speed": usage.get("speed"),
            "input": usage.get("input_tokens") or 0,
            "output": usage.get("output_tokens") or 0,
            "cache_read": usage.get("cache_read_input_tokens") or 0,
            "cache_write_1h": write_1h,
            "cache_write_5m": max(write_total - write_1h, 0),
            "agent_type": agent_type,
        }


def read_tests(path, pattern=DEFAULT_TEST_RE):
    """Bash calls whose command matches pattern, timed tool_use -> tool_result.

    The command is reduced to a hash (for rerun detection) and never returned.
    """
    rx = re.compile(pattern)
    pending = {}
    for e in _entries(path):
        msg = e.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        ts = parse_ts(e.get("timestamp"))
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                cmd = (block.get("input") or {}).get("command") or ""
                if rx.search(cmd):
                    key = hashlib.sha256(cmd.encode()).hexdigest()[:12]
                    pending[block.get("id")] = (ts, key)
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in pending:
                start, key = pending.pop(block["tool_use_id"])
                yield {
                    "start": start,
                    "end": ts,
                    "seconds": (ts - start).total_seconds() if start and ts else None,
                    "ok": not block.get("is_error"),
                    "key": key,
                }


class Pricing:
    """USD estimates from a pinned list-price table. None means unpriced, never zero."""

    def __init__(self, path):
        with open(path) as fh:
            data = json.load(fh)
        self.models = data["models"]
        self.write_5m = data["cache_write_5m_multiplier"]
        self.write_1h = data["cache_write_1h_multiplier"]
        self.as_of = data.get("as_of")

    def cost(self, rec):
        p = self.models.get(rec["model"])
        if p is None:
            return None
        prompt = rec["input"] + rec["cache_read"] + rec["cache_write_5m"] + rec["cache_write_1h"]
        long_ctx = p.get("long_context")
        if long_ctx and prompt > long_ctx["above"]:
            inp, out = long_ctx["input"], long_ctx["output"]
            read = inp * 0.1
        else:
            inp, out, read = p["input"], p["output"], p["cache_read"]
        mult = p.get("fast_multiplier", 1) if rec.get("speed") == "fast" else 1
        usd = (
            rec["input"] * inp
            + rec["output"] * out
            + rec["cache_read"] * read
            + rec["cache_write_5m"] * inp * self.write_5m
            + rec["cache_write_1h"] * inp * self.write_1h
        )
        return usd * mult / 1_000_000
