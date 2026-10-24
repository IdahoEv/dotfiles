#!/usr/bin/env python3
"""Validate and apply /tighten proposals by exact text match. Never guesses."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tighten_lib import (  # noqa: E402
    PROTECTED_RE,
    comment_ranges,
    count_words,
    doc_protected_ranges,
    git_root,
    is_doc,
    line_ending,
    normalize_newlines,
    rst_protected_ranges,
    spec_for,
)


def _load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    proposals = data.get("proposals", []) if isinstance(data, dict) else data
    return [dict(item) for item in proposals]


def _resolve(root: str, file: str) -> str | None:
    absolute = os.path.abspath(file if os.path.isabs(file) else os.path.join(root, file))
    try:
        if os.path.commonpath([absolute, root]) != root:
            return None
    except ValueError:
        return None
    return absolute


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _touches(ranges: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(start < other_end and other_start < end for other_start, other_end in ranges)


def _code_outside(text: str, ranges: list[tuple[int, int]], start: int, end: int) -> bool:
    for index in range(start, end):
        if text[index].isspace():
            continue
        if not any(begin <= index < finish for begin, finish in ranges):
            return True
    return False


def _editable_prose(text: str, rel: str) -> tuple[list[tuple[int, int]], bool]:
    """Protected doc regions and whether the language is parsed at all."""
    if rel.lower().endswith(".rst"):
        return rst_protected_ranges(text), True
    if rel.lower().endswith(".mdx"):
        return [], False
    if rel.lower().endswith((".md", ".markdown")):
        return doc_protected_ranges(text), True
    return [], True


def validate(root: str, proposals: list[dict]) -> tuple[list[dict], list[dict]]:
    accepted: list[dict] = []
    rejected: list[dict] = []
    per_file: dict[str, list[tuple[int, int]]] = {}
    texts: dict[str, str] = {}
    code_cache: dict[str, tuple[list[tuple[int, int]], bool]] = {}
    doc_cache: dict[str, tuple[list[tuple[int, int]], bool]] = {}

    for index, proposal in enumerate(proposals):
        file = str(proposal.get("file", ""))
        old = normalize_newlines(str(proposal.get("old", "")))
        new = normalize_newlines(str(proposal.get("new", "")))
        entry = {"index": index, "file": file}

        if not file or not old:
            rejected.append({**entry, "reason": "missing_file_or_old"})
            continue
        absolute = _resolve(root, file)
        if absolute is None or not os.path.isfile(absolute) or os.path.islink(absolute):
            rejected.append({**entry, "reason": "not_a_file_in_root"})
            continue
        rel = os.path.relpath(absolute, root).replace(os.sep, "/")
        if rel not in texts:
            try:
                with open(absolute, encoding="utf-8", newline="") as handle:
                    raw = handle.read()
            except (OSError, UnicodeDecodeError):
                rejected.append({**entry, "reason": "unreadable"})
                continue
            pairs = raw.count("\r\n")
            lone = raw.count("\r") - pairs
            if lone or ("\r" in raw and pairs != raw.count("\n")):
                rejected.append({**entry, "reason": "mixed_line_endings"})
                continue
            texts[rel] = normalize_newlines(raw)
        text = texts[rel]

        if old.strip() == text.strip():
            rejected.append({**entry, "reason": "whole_file"})
            continue
        if any(PROTECTED_RE.search(line) or line.lstrip().startswith((">>>", "..."))
               for line in old.splitlines()):
            rejected.append({**entry, "reason": "protected_directive"})
            continue
        if count_words(new) > count_words(old):
            rejected.append({**entry, "reason": "word_growth"})
            continue

        offsets = [match.start() for match in re.finditer(re.escape(old), text)]
        if not offsets:
            rejected.append({**entry, "reason": "not_found"})
            continue
        start_line = proposal.get("start_line")
        if len(offsets) > 1:
            if not isinstance(start_line, int):
                rejected.append({**entry, "reason": "ambiguous"})
                continue
            offsets = [offset for offset in offsets
                       if abs(_line_at(text, offset) - start_line) <= 3]
            if len(offsets) != 1:
                rejected.append({**entry, "reason": "ambiguous"})
                continue
        offset = offsets[0]
        start = offset
        end = offset + len(old)
        if any(not (end <= other_start or start >= other_end)
               for other_start, other_end in per_file.get(rel, [])):
            rejected.append({**entry, "reason": "overlap"})
            continue

        if not is_doc(rel):
            if spec_for(rel) is None:
                rejected.append({**entry, "reason": "unsupported"})
                continue
            if rel not in code_cache:
                code_cache[rel] = comment_ranges(text, rel)
            ranges, parsed = code_cache[rel]
            if not parsed:
                rejected.append({**entry, "reason": "parse_error_file"})
                continue
            if not _touches(ranges, start, end):
                rejected.append({**entry, "reason": "not_in_comment"})
                continue
            if _code_outside(text, ranges, start, end):
                rejected.append({**entry, "reason": "code_touch"})
                continue

        if is_doc(rel):
            if rel not in doc_cache:
                doc_cache[rel] = _editable_prose(text, rel)
            ranges, parsed = doc_cache[rel]
            if not parsed or _touches(ranges, start, end):
                rejected.append({**entry, "reason": "doc_structural"})
                continue
            if re.search(r"^\s*(```|~~~|---\s*$|\[[^\]]+\]:\s|<!--)", old, re.MULTILINE):
                rejected.append({**entry, "reason": "doc_structural"})
                continue
            old_structural = set(re.findall(r"^\s*(?:#{1,6}\s|```|~~~|\|).*$", old, re.MULTILINE))
            new_structural = set(re.findall(r"^\s*(?:#{1,6}\s|```|~~~|\|).*$", new, re.MULTILINE))
            if new_structural - old_structural:
                rejected.append({**entry, "reason": "doc_structural"})
                continue

        per_file.setdefault(rel, []).append((start, end))
        accepted.append({
            "index": index,
            "file": rel,
            "absolute": absolute,
            "offset": start,
            "start_line": _line_at(text, start),
            "end_line": _line_at(text, max(start, end - 1)),
            "words_before": count_words(old),
            "words_after": count_words(new),
            "old": old,
            "new": new,
            "reason": proposal.get("reason", ""),
        })
    return accepted, rejected


def _write(absolute: str, text: str, original_ending: str) -> None:
    if original_ending == "\r\n":
        text = text.replace("\n", "\r\n")
    mode = stat.S_IMODE(os.stat(absolute).st_mode)
    temporary = f"{absolute}.tighten-tmp"
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    os.chmod(temporary, mode)
    os.replace(temporary, absolute)


def apply(root: str, accepted: list[dict]) -> tuple[int, int]:
    by_file: dict[str, list[dict]] = {}
    for item in accepted:
        by_file.setdefault(item["file"], []).append(item)

    files_changed = 0
    words_before = 0
    words_after = 0
    for rel, items in by_file.items():
        absolute = items[0]["absolute"]
        with open(absolute, encoding="utf-8", newline="") as handle:
            original = handle.read()
        ending = line_ending(original)
        text = normalize_newlines(original)
        for item in sorted(items, key=lambda entry: -entry["offset"]):
            position = item["offset"]
            if text[position:position + len(item["old"])] != item["old"]:
                raise RuntimeError(f"proposal for {rel} no longer matches")
            text = text[:position] + item["new"] + text[position + len(item["old"]):]
        _write(absolute, text, ending)
        files_changed += 1
        words_before += sum(item["words_before"] for item in items)
        words_after += sum(item["words_after"] for item in items)
    return files_changed, words_before, words_after


def _filter_dirs(proposals: list[dict], directories: list[str]) -> list[dict]:
    selected: list[dict] = []
    for proposal in proposals:
        rel = str(proposal.get("file", ""))
        if rel.startswith("./"):
            rel = rel[2:]
        parent = os.path.dirname(rel) or "."
        for directory in directories:
            directory = directory.strip("/")
            if directory.startswith("./"):
                directory = directory[2:]
            if directory in ("", "."):
                directory = "."
            if directory == parent:
                selected.append(proposal)
                break
    return selected


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate or apply /tighten proposals.")
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("proposals")
    parser.add_argument("--root", default=".")
    parser.add_argument("--dir", action="append", default=[],
                        help="only proposals whose file sits directly in this directory (repeatable)")
    parser.add_argument("--write-accepted", metavar="PATH",
                        help="write the accepted proposals for a later apply")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stage", action="store_true",
                        help="git add exactly the changed files after applying")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    root = git_root(root) or root
    proposals = _load(args.proposals)
    if args.dir:
        proposals = _filter_dirs(proposals, args.dir)
    if not proposals:
        print("no proposals", file=sys.stderr)
        return 2

    accepted, rejected = validate(root, proposals)
    result = {
        "accepted": [{key: item[key] for key in
                      ("file", "start_line", "end_line", "words_before", "words_after", "reason")}
                     for item in accepted],
        "rejected": rejected,
        "words_before": sum(item["words_before"] for item in accepted),
        "words_after": sum(item["words_after"] for item in accepted),
    }
    if args.write_accepted:
        with open(args.write_accepted, "w", encoding="utf-8") as handle:
            json.dump({"proposals": [proposals[item["index"]] for item in accepted]},
                      handle, indent=2)

    if args.command == "apply" and not args.dry_run:
        if rejected:
            print(json.dumps(result, indent=2) if args.json else
                  "\n".join(f"rejected: {item['file']}: {item['reason']}" for item in rejected),
                  file=sys.stderr)
            print("refusing to apply: fix or drop rejected proposals first", file=sys.stderr)
            return 3
        try:
            files_changed, before, after = apply(root, accepted)
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 5
        except OSError as error:
            print(f"write failed: {error}", file=sys.stderr)
            return 6
        result["files_changed"] = files_changed
        result["words_before"] = before
        result["words_after"] = after
        if args.stage:
            changed = sorted({item["file"] for item in accepted})
            staged = subprocess.run(["git", "-C", root, "add", "--", *changed])
            if staged.returncode != 0:
                print("failed to stage changed files", file=sys.stderr)
                return 4
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"applied={len(accepted)} files={files_changed} "
                  f"words_before={before} words_after={after} delta={after - before}")
        return 0

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for item in result["accepted"]:
            print(f"ok {item['file']}:{item['start_line']} "
                  f"words={item['words_before']}->{item['words_after']} {item['reason']}")
        for item in rejected:
            print(f"rejected {item['file']}: {item['reason']}")
        print(f"accepted={len(accepted)} rejected={len(rejected)} "
              f"words_before={result['words_before']} words_after={result['words_after']}")
    return 0 if not rejected else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
