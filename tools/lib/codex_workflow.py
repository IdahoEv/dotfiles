"""Launch, discover, and revisit local Codex workstreams."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repo_facts
import workstream
from codex_rpc import Daemon, RpcError

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
COMMANDS = ("governor", "groom", "pick", "start", "discuss", "local-review-cycle",
            "open-pr", "github-review-comments", "finalize", "merge", "land", "sync")


def child_environment():
    return {key: value for key, value in os.environ.items() if key != "MEM_GUARD_OVERRIDE"}


def check_memory(directory, label):
    try:
        result = subprocess.run(
            [str(TOOLS / "mem-guard.sh"), "check", "--context", f"codex {label}"],
            cwd=directory, env=dict(os.environ), capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"codex-workflow: mem-guard unavailable ({exc}); launching without a memory check", file=sys.stderr)
        return
    if result.stdout:
        print(result.stdout, file=sys.stderr, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode == 3:
        raise RpcError("launch blocked by mem-guard; stop remaining groups and let the user decide whether to override")
    if result.returncode != 0:
        print(f"codex-workflow: mem-guard failed (exit {result.returncode}); launching without a memory check", file=sys.stderr)


def context():
    return (
        f"Local Codex CLI workflow. Read {ROOT / 'workflow/adapters/codex-local.md'} "
        "and apply its mappings to every workflow command and delegated agent. "
        f"Workflow root: {ROOT}. Workflow tools: {TOOLS}. "
        "Read the project's AGENTS.md and CLAUDE.md. "
        "Propose an implementation plan and wait for explicit approval before editing."
    )


def launch(rpc, directory, kickoff, name="", kind="ticket"):
    directory = str(Path(directory).resolve(strict=True))
    prompt = Path(kickoff).read_text(encoding="utf-8")
    record = workstream.load_record(directory) if kind == "ticket" else None
    if kind == "ticket" and record is None:
        raise RpcError("ticket launch requires .workstream.json; run start-ticket.sh first")
    if record and record.codex_sessions:
        thread_id = record.codex_sessions[-1]
        thread = rpc.call("thread/read", {"threadId": thread_id})["thread"]
        if Path(thread["cwd"]).resolve() != Path(directory):
            raise RpcError(f"recorded thread {thread_id} belongs to another directory")
        return {"thread_id": thread_id, "worktree": directory, "reused": True,
                "resume": f"codex resume {thread_id}",
                "note": "existing session; kickoff was not resubmitted"}
    row_record = dataclasses.replace(record, desc=(repo_facts.sanitize_label(
        os.environ.get("GT_LABEL_OVERRIDE", "")) or record.desc)) if record else None
    label = name or (workstream.render_surface(row_record, "row", directory) if row_record else "[TALK] Discussion")
    check_memory(directory, "session launch")
    response = rpc.call("thread/start", {"cwd": directory, "ephemeral": False})
    thread_id = response["thread"]["id"]
    try:
        if record:
            record.codex_sessions.append(thread_id)
            workstream.save_record(directory, record)
        rpc.call("thread/name/set", {"threadId": thread_id, "name": label})
        rpc.call("turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": context() + "\n\n" + prompt}],
            "collaborationMode": {"mode": "plan", "settings": {
                "model": response["model"],
                "reasoning_effort": response.get("reasoningEffort"),
                "developer_instructions": None,
            }},
        })
    except Exception as exc:
        raise RpcError(
            f"launch incomplete for thread {thread_id}: {exc}. "
            f"Inspect codex resume {thread_id} before retrying; it may already be running."
        ) from exc
    return {"thread_id": thread_id, "worktree": directory, "name": label,
            "reused": False, "resume": f"codex resume {thread_id}"}


def parse_groups(groups):
    if not groups:
        raise ValueError("supply at least one ticket group")
    seen = set()
    for group in groups:
        if not re.fullmatch(r"[0-9]+(?:,[0-9]+)*", group):
            raise ValueError(f"invalid ticket group: {group}")
        for ticket in group.split(","):
            normalized = str(int(ticket))
            if normalized in seen:
                raise ValueError(f"ticket {ticket} occurs more than once")
            seen.add(normalized)
    return groups


def prepare(arguments, directory):
    result = subprocess.run([str(TOOLS / "start-ticket.sh"), *arguments],
                            cwd=directory, env=child_environment(), text=True, capture_output=True, check=True)
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def start_groups(rpc, groups, directory):
    for group in parse_groups(groups):
        check_memory(directory, f"ticket {group}")
        setup = prepare([group, "--no-tab"], directory)
        try:
            result = launch(rpc, setup["worktree"], setup["kickoff"])
        except RpcError as exc:
            raise RpcError(f"{exc}. Setup already completed: {json.dumps(setup)}") from exc
        result.update(group=group, ticket_state=setup.get("ticket_state", "unknown"),
                      ticket_in_progress=setup.get("ticket_in_progress", "unknown"))
        print(json.dumps(result), flush=True)


def list_threads(rpc):
    cursor = None
    threads = []
    while True:
        result = rpc.call("thread/list", {"cursor": cursor, "limit": 100, "modelProviders": []})
        threads.extend(result["data"])
        cursor = result.get("nextCursor")
        if not cursor:
            return threads


def status(rpc, directory):
    listing = subprocess.run(["git", "-C", directory, "worktree", "list", "--porcelain"],
                             capture_output=True, text=True, check=True).stdout
    directories = [line.removeprefix("worktree ") for line in listing.splitlines() if line.startswith("worktree ")]
    threads = list_threads(rpc)
    for path in directories:
        record = workstream.load_record(path)
        matching = [t for t in threads if Path(t["cwd"]).resolve() == Path(path).resolve()]
        print(json.dumps({"worktree": path, "workstream": record.to_dict() if record else None,
                          "sessions": [{k: t.get(k) for k in ("id", "name", "status", "parentThreadId")}
                                       for t in matching]}))
    print("Visibility: local daemon's non-archived interactive sessions only; Claude/AGY activity, "
          "remote daemons and unsaved sessions are not observed. Missing sessions are not proof of idle worktrees.",
          file=sys.stderr)


def instructions(command):
    if command not in COMMANDS:
        raise ValueError(f"unsupported command: {command}")
    return (f"Read {ROOT / 'workflow/adapters/codex-local.md'}, then follow "
            f"{ROOT / 'dot_claude/commands' / (command + '.md')} step by step using its mappings.")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("groups", nargs="+")
    start.add_argument("--dir", default=os.getcwd())
    launch_p = sub.add_parser("launch")
    launch_p.add_argument("--dir", required=True)
    launch_p.add_argument("--kickoff", required=True)
    launch_p.add_argument("--name", default="")
    launch_p.add_argument("--kind", choices=("ticket", "talk"), default="ticket")
    talk = sub.add_parser("discuss")
    talk.add_argument("topic", nargs="?", default="")
    talk.add_argument("--about", default="")
    talk.add_argument("--dir", default=os.getcwd())
    state = sub.add_parser("status")
    state.add_argument("--dir", default=os.getcwd())
    resume = sub.add_parser("resume")
    resume.add_argument("thread")
    send = sub.add_parser("send")
    send.add_argument("thread")
    send.add_argument("message")
    send.add_argument("--implement", action="store_true", help="switch an approved plan to default mode")
    name = sub.add_parser("name")
    name.add_argument("thread")
    name.add_argument("name")
    command = sub.add_parser("instructions")
    command.add_argument("name", choices=COMMANDS)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "instructions":
            print(instructions(args.name))
            return 0
        if args.command == "resume":
            return subprocess.call(["codex", "resume", args.thread], env=child_environment())
        if args.command == "start":
            parse_groups(args.groups)
        with Daemon() as rpc:
            if args.command == "start":
                start_groups(rpc, args.groups, args.dir)
            elif args.command == "launch":
                print(json.dumps(launch(rpc, args.dir, args.kickoff, args.name, args.kind)))
            elif args.command == "discuss":
                check_memory(args.dir, "discussion setup")
                setup = prepare(["--session", args.topic, "--about", args.about, "--launcher", "none"], args.dir)
                print(json.dumps(launch(rpc, setup["dir"], setup["kickoff"], setup["label"], "talk")))
            elif args.command == "status":
                status(rpc, args.dir)
            elif args.command == "name":
                rpc.call("thread/name/set", {"threadId": args.thread, "name": args.name})
            elif args.command == "send":
                resumed = rpc.call("thread/resume", {"threadId": args.thread, "excludeTurns": True})
                params = {"threadId": args.thread, "input": [{"type": "text", "text": args.message}]}
                if args.implement:
                    params["collaborationMode"] = {"mode": "default", "settings": {
                        "model": resumed["model"], "reasoning_effort": resumed.get("reasoningEffort"),
                        "developer_instructions": None,
                    }}
                result = rpc.call("turn/start", params)
                print(json.dumps({"thread_id": args.thread, "turn": result["turn"]}))
        return 0
    except (RpcError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"codex-workflow: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
