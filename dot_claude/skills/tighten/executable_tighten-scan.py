#!/usr/bin/env python3
"""Read-only comment and documentation bloat scan for /tighten."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tighten_lib import (  # noqa: E402
    DOC_EXTENSIONS,
    GENERATED_MARKERS,
    GENERATED_NAMES,
    NON_PROSE_DOC_NAMES,
    VENDORED_SEGMENTS,
    block_kind,
    count_words,
    git_root,
    is_doc,
    markdown_prose,
    ref_counts,
    scan_code,
    spec_for,
)

MAX_BYTES = 1_048_576
PROMPT_BASENAMES = {"claude.md", "agents.md", "skill.md", ".cursorrules"}


@dataclass
class SkipCounts:
    vendored: int = 0
    generated: int = 0
    excluded: int = 0
    prompt: int = 0
    binary: int = 0
    large: int = 0
    unsupported: int = 0
    symlink: int = 0

    def as_dict(self) -> dict:
        return {
            "vendored": self.vendored, "generated": self.generated,
            "excluded": self.excluded, "prompt": self.prompt,
            "binary": self.binary, "large": self.large,
            "unsupported": self.unsupported, "symlink": self.symlink,
        }


@dataclass
class FileStats:
    path: str
    kind: str
    language: str
    comment_words: int = 0
    comment_lines: int = 0
    comment_blocks: int = 0
    max_block_lines: int = 0
    long_blocks: int = 0
    code_lines: int = 0
    history_refs: int = 0
    ticket_refs: int = 0
    doc_prose_words: int = 0
    doc_total_words: int = 0
    headings: int = 0
    license_header: bool = False
    parse_error: bool = False
    signal: bool = False
    blocks: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "path": self.path, "kind": self.kind, "language": self.language,
            "comment_words": self.comment_words, "comment_lines": self.comment_lines,
            "comment_blocks": self.comment_blocks, "max_block_lines": self.max_block_lines,
            "long_blocks": self.long_blocks, "code_lines": self.code_lines,
            "history_refs": self.history_refs, "ticket_refs": self.ticket_refs,
            "doc_prose_words": self.doc_prose_words, "doc_total_words": self.doc_total_words,
            "headings": self.headings, "license_header": self.license_header,
            "parse_error": self.parse_error, "signal": self.signal, "blocks": self.blocks,
        }


def _is_vendored(rel: str) -> bool:
    return any(part.lower() in VENDORED_SEGMENTS for part in rel.split("/")[:-1])


def _matches(name: str, patterns: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, pattern) for pattern in patterns)


def _is_prompt_file(rel: str) -> bool:
    parts = rel.split("/")
    if any(part in (".claude", "dot_claude") for part in parts[:-1]):
        return True
    return os.path.basename(rel).lower() in PROMPT_BASENAMES


def _git_files(root: str, paths: list[str], include_untracked: bool) -> list[str] | None:
    args = ["git", "-C", root, "ls-files", "-z", "--cached"]
    if include_untracked:
        args.extend(["--others", "--exclude-standard"])
    args.append("--")
    if paths:
        relative: list[str] = []
        for path in paths:
            absolute = os.path.abspath(path)
            if os.path.commonpath([absolute, root]) != root:
                return None
            relative.append(os.path.relpath(absolute, root))
        args.extend(relative)
    try:
        out = subprocess.run(args, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [entry for entry in out.decode("utf-8", "replace").split("\0") if entry]


def _walk_files(root: str, paths: list[str]) -> list[str]:
    results: list[str] = []
    bases = [os.path.abspath(path) for path in paths] or [root]
    for base in bases:
        if os.path.isfile(base):
            results.append(os.path.relpath(base, root))
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [name for name in dirnames if name.lower() not in VENDORED_SEGMENTS]
            for name in filenames:
                results.append(os.path.relpath(os.path.join(dirpath, name), root))
    return results


def _tracked_under(root: str, path: str) -> bool:
    try:
        rel = os.path.relpath(os.path.abspath(path), root)
        out = subprocess.run(["git", "-C", root, "ls-files", "--cached", "--", rel],
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return True
    return bool(out.strip())


def discover(root: str, paths: list[str], explicit_files: set[str], include_untracked: bool,
             include: list[str], exclude: list[str], skips: SkipCounts) -> list[tuple[str, str]]:
    git_files = _git_files(root, paths, include_untracked)
    files = git_files if git_files is not None else _walk_files(root, paths)
    found: list[tuple[str, str]] = []

    for rel in sorted(set(files)):
        rel = rel.replace(os.sep, "/")
        absolute = os.path.join(root, rel)
        if os.path.islink(absolute):
            skips.symlink += 1
            continue
        if _is_vendored(rel):
            skips.vendored += 1
            continue
        name = os.path.basename(rel)
        if _matches(name, GENERATED_NAMES):
            skips.generated += 1
            continue
        if _matches(name, NON_PROSE_DOC_NAMES) and is_doc(rel):
            skips.excluded += 1
            continue
        if _is_prompt_file(rel) and os.path.realpath(absolute) not in explicit_files:
            skips.prompt += 1
            continue
        if include and not any(fnmatch.fnmatch(rel, pattern) for pattern in include):
            continue
        if any(fnmatch.fnmatch(rel, pattern) for pattern in exclude):
            continue
        if not os.path.isfile(absolute):
            continue
        found.append((rel, absolute))
    return found


def _read_text(path: str) -> tuple[str | None, str]:
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, "binary"
    if size > MAX_BYTES:
        return None, "large"
    try:
        with open(path, "rb") as handle:
            head = handle.read(8192)
            if b"\0" in head:
                return None, "binary"
            handle.seek(0)
            return handle.read().decode("utf-8"), ""
    except (OSError, UnicodeDecodeError):
        return None, "binary"


def _block_dicts(blocks: list[list[tuple[int, str]]]) -> list[dict]:
    result = []
    for block in blocks:
        text = "\n".join(piece for _line, piece in block)
        result.append({
            "start": block[0][0], "end": block[-1][0],
            "words": count_words(text), "protected": block_kind(text),
        })
    return result


def scan_file(rel: str, absolute: str, skips: SkipCounts) -> FileStats | None:
    text, reason = _read_text(absolute)
    if text is None:
        setattr(skips, reason, getattr(skips, reason) + 1)
        return None
    ext = os.path.splitext(rel)[1].lower()
    if ext in DOC_EXTENSIONS:
        first = text.splitlines()[0].lower() if text.splitlines() else ""
        if any(marker in first for marker in GENERATED_MARKERS):
            skips.generated += 1
            return None
        prose, total, headings = markdown_prose(text)
        history, tickets = ref_counts(text)
        mdx = ext == ".mdx"
        stats = FileStats(rel, "doc", "rst" if ext == ".rst" else "markdown",
                          doc_prose_words=prose, doc_total_words=total, headings=headings,
                          history_refs=history, ticket_refs=tickets, parse_error=mdx)
        stats.signal = prose >= 100 and not mdx
        return stats

    head = text[:2048].lower()
    if any(marker in head for marker in GENERATED_MARKERS):
        skips.generated += 1
        return None

    spec = spec_for(rel)
    if spec is None:
        skips.unsupported += 1
        return None
    language = "python" if ext in (".py", ".pyi") else (ext.lstrip(".") or rel.lower())
    blocks, code_lines, license_header, parsed = scan_code(text, language, spec)
    block_data = _block_dicts(blocks)
    joined = "\n".join(piece for block in blocks for _line, piece in block)
    history, tickets = ref_counts(joined)
    stats = FileStats(
        rel, "code", language, code_lines=code_lines, history_refs=history,
        ticket_refs=tickets, license_header=license_header, parse_error=not parsed,
        blocks=block_data,
    )
    stats.comment_words = sum(entry["words"] for entry in block_data)
    stats.comment_lines = sum(len(block) for block in blocks)
    stats.comment_blocks = len(blocks)
    stats.max_block_lines = max((block[-1][0] - block[0][0] + 1 for block in blocks), default=0)
    stats.long_blocks = sum(1 for block in blocks if block[-1][0] - block[0][0] + 1 > 3)
    stats.signal = (stats.comment_words >= 20 or stats.long_blocks > 0
                    or stats.history_refs > 0 or stats.ticket_refs > 0)
    return stats


def detect_commands(root: str) -> dict[str, str]:
    package_json = os.path.join(root, "package.json")
    if os.path.isfile(package_json):
        try:
            with open(package_json, encoding="utf-8") as handle:
                script = json.load(handle).get("scripts", {})
        except (OSError, ValueError):
            script = {}
        runner = "npm run"
        if os.path.isfile(os.path.join(root, "pnpm-lock.yaml")):
            runner = "pnpm"
        elif os.path.isfile(os.path.join(root, "yarn.lock")):
            runner = "yarn"
        elif os.path.isfile(os.path.join(root, "bun.lockb")):
            runner = "bun run"
        result: dict[str, str] = {}
        if "build" in script:
            result["build"] = f"{runner} build"
        if "test" in script:
            result["test"] = "npm test" if runner == "npm run" else f"{runner} test"
        if result:
            result["source"] = "package.json"
            return result

    for name in ("Makefile", "makefile", "GNUmakefile"):
        makefile = os.path.join(root, name)
        if not os.path.isfile(makefile):
            continue
        try:
            with open(makefile, encoding="utf-8", errors="replace") as handle:
                body = handle.read()
        except OSError:
            body = ""
        result = {}
        if re.search(r"^build\s*:", body, re.MULTILINE):
            result["build"] = "make build"
        if re.search(r"^test\s*:", body, re.MULTILINE):
            result["test"] = "make test"
        if result:
            result["source"] = os.path.basename(makefile)
            return result

    result = {}
    pyproject = os.path.join(root, "pyproject.toml")
    if os.path.isfile(pyproject):
        try:
            with open(pyproject, encoding="utf-8", errors="replace") as handle:
                body = handle.read()
        except OSError:
            body = ""
        if "[tool.pytest" in body or re.search(r"^pytest\b", body, re.MULTILINE):
            result["test"] = "pytest"
        elif os.path.isdir(os.path.join(root, "tests")):
            result["test"] = "pytest"
        if "[build-system]" in body:
            result["build"] = "python -m build"
    if result:
        result["source"] = "pyproject.toml"
        return result
    if os.path.isfile(os.path.join(root, "pytest.ini")) or os.path.isfile(os.path.join(root, "conftest.py")):
        return {"test": "pytest", "source": "pytest config"}
    if os.path.isfile(os.path.join(root, "Cargo.toml")):
        return {"build": "cargo build", "test": "cargo test", "source": "Cargo.toml"}
    if os.path.isfile(os.path.join(root, "go.mod")):
        return {"build": "go build ./...", "test": "go test ./...", "source": "go.mod"}
    if os.path.isfile(os.path.join(root, "Gemfile")):
        test = "bundle exec rspec" if os.path.isdir(os.path.join(root, "spec")) else "bundle exec rake test"
        return {"test": test, "source": "Gemfile"}
    if os.path.isfile(os.path.join(root, "mix.exs")):
        return {"build": "mix compile", "test": "mix test", "source": "mix.exs"}
    if os.path.isfile(os.path.join(root, "pom.xml")):
        return {"build": "mvn package", "test": "mvn test", "source": "pom.xml"}
    for gradle in ("build.gradle", "build.gradle.kts"):
        if os.path.isfile(os.path.join(root, gradle)):
            prefix = "./gradlew" if os.path.isfile(os.path.join(root, "gradlew")) else "gradle"
            return {"build": f"{prefix} build", "test": f"{prefix} test", "source": gradle}
    return {}


def aggregate(files: list[FileStats]) -> list[dict]:
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for stats in files:
        directory = os.path.dirname(stats.path) or "."
        entry = groups.setdefault(directory, {
            "directory": directory, "files": 0, "comment_words": 0,
            "doc_prose_words": 0, "long_blocks": 0, "history_refs": 0,
        })
        entry["files"] += 1
        entry["comment_words"] += stats.comment_words
        entry["doc_prose_words"] += stats.doc_prose_words
        entry["long_blocks"] += stats.long_blocks
        entry["history_refs"] += stats.history_refs
    return sorted(groups.values(),
                  key=lambda item: (-(item["comment_words"] + item["doc_prose_words"]),
                                    item["directory"]))


def _commit(root: str) -> str:
    try:
        return subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build_report(files: list[FileStats], skips: SkipCounts, top: int, root: str,
                 mode: str) -> dict:
    by_comment = sorted((f for f in files if f.kind == "code"),
                        key=lambda f: (-f.comment_words, f.path))
    by_doc = sorted((f for f in files if f.kind == "doc"),
                    key=lambda f: (-f.doc_prose_words, f.path))
    return {
        "version": 1,
        "root": root,
        "commit": _commit(root),
        "mode": mode,
        "files_scanned": len(files),
        "code_files": sum(1 for f in files if f.kind == "code"),
        "doc_files": sum(1 for f in files if f.kind == "doc"),
        "comment_words": sum(f.comment_words for f in files),
        "doc_prose_words": sum(f.doc_prose_words for f in files),
        "signals": {
            "files": sum(1 for f in files if f.signal),
            "history_refs": sum(f.history_refs for f in files),
            "ticket_refs": sum(f.ticket_refs for f in files),
            "long_blocks": sum(f.long_blocks for f in files),
            "parse_errors": sum(1 for f in files if f.parse_error),
        },
        "skipped": skips.as_dict(),
        "files": [f.as_dict() for f in files],
        "directories": aggregate(files),
        "top_comment": [f.as_dict() for f in by_comment[:top]],
        "top_docs": [f.as_dict() for f in by_doc[:top]],
    }


def print_table(report: dict) -> None:
    print(f"root={report['root']} commit={report['commit'] or '-'} mode={report['mode']}")
    print(f"files={report['files_scanned']} code={report['code_files']} docs={report['doc_files']} "
          f"comment_words={report['comment_words']} doc_prose_words={report['doc_prose_words']}")
    print("skipped=" + " ".join(f"{key}:{value}" for key, value in report["skipped"].items()))

    if report["directories"]:
        print("\nDirectory rollup")
        print("| directory | files | comment words | doc prose words | long blocks | history refs |")
        print("| --- | --- | --- | --- | --- | --- |")
        for entry in report["directories"]:
            print(f"| {entry['directory']} | {entry['files']} | {entry['comment_words']} | "
                  f"{entry['doc_prose_words']} | {entry['long_blocks']} | {entry['history_refs']} |")

    if report["top_comment"]:
        print("\nTop comment offenders")
        print("| file | comment words | lines | blocks | longest | history | tickets |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for entry in report["top_comment"]:
            print(f"| {entry['path']} | {entry['comment_words']} | {entry['comment_lines']} | "
                  f"{entry['comment_blocks']} | {entry['max_block_lines']} | "
                  f"{entry['history_refs']} | {entry['ticket_refs']} |")

    if report["top_docs"]:
        print("\nTop doc offenders")
        print("| file | prose words | total words | headings | history | tickets |")
        print("| --- | --- | --- | --- | --- | --- |")
        for entry in report["top_docs"]:
            print(f"| {entry['path']} | {entry['doc_prose_words']} | {entry['doc_total_words']} | "
                  f"{entry['headings']} | {entry['history_refs']} | {entry['ticket_refs']} |")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Comment and documentation bloat scan.")
    parser.add_argument("paths", nargs="*", help="files or directories; default is the repo root")
    parser.add_argument("--root", help="scan root; default is the git root of the first path")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--top", type=int, default=10, help="offenders to list (default 10)")
    parser.add_argument("--commands", action="store_true", help="print detected build/test commands")
    parser.add_argument("--include-untracked", action="store_true",
                        help="include untracked files (report only; they do not exist in a worktree)")
    parser.add_argument("--include", action="append", default=[], metavar="GLOB")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--comments-only", action="store_true")
    group.add_argument("--docs-only", action="store_true")
    args = parser.parse_args(argv)

    if args.root:
        root = os.path.abspath(args.root)
    elif args.paths:
        first = os.path.abspath(args.paths[0])
        base = first if os.path.isdir(first) else os.path.dirname(first)
        root = git_root(base) or base
    else:
        root = git_root(os.getcwd()) or os.getcwd()
    root = os.path.realpath(root)

    commands = detect_commands(root)
    if args.commands:
        print(f"root={root}")
        for key in ("build", "test", "source"):
            if key in commands:
                print(f"{key}={commands[key]}")
        return 0

    paths = [os.path.abspath(path) for path in args.paths]
    real_root = os.path.realpath(root)
    for path in paths:
        try:
            inside = os.path.commonpath([os.path.realpath(path), real_root]) == real_root
        except ValueError:
            inside = False
        if not inside:
            print(f"path outside root: {path} (root {root})", file=sys.stderr)
            return 1
    git_files = _git_files(root, paths, args.include_untracked)
    mode = "git" if git_files is not None else "walk"
    skips = SkipCounts()
    explicit_files = {os.path.realpath(path) for path in paths if os.path.isfile(path)}
    candidates = discover(root, paths, explicit_files, args.include_untracked,
                          args.include, args.exclude, skips)
    files: list[FileStats] = []
    for rel, absolute in candidates:
        stats = scan_file(rel, absolute, skips)
        if stats is None:
            continue
        if args.comments_only and stats.kind != "code":
            continue
        if args.docs_only and stats.kind != "doc":
            continue
        files.append(stats)

    if not files:
        hint = ""
        if args.paths and not args.include_untracked:
            untracked = [path for path in args.paths
                         if os.path.exists(path) and not _tracked_under(root, path)]
            if untracked:
                hint = (f" (untracked, not in the index: {', '.join(untracked)}; "
                        "pass --include-untracked to scan them)")
        print("no files in scope" + hint, file=sys.stderr)
        return 2

    report = build_report(files, skips, args.top, root, mode)
    if commands:
        report["commands"] = commands
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_table(report)
        if commands:
            print("\ncommands")
            for key in ("build", "test", "source"):
                if key in commands:
                    print(f"  {key}={commands[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
