#!/usr/bin/env bash
# Generate or check workflow/manifest.txt: the file list the cloud bootstrap fetches from
# raw.githubusercontent.com when it cannot download the repo archive. One line per file:
#   <sha256>  <mode>  <path>
#
#   workflow-manifest.sh --write   regenerate (run after changing any covered file)
#   workflow-manifest.sh --check   exit 1 if the committed manifest is stale (default)
#
# Covered: dot_claude/{commands,agents,skills}, tools, workflow/adapters, minus tests,
# tools/examples and tools/lib/fixtures. Hashes the staged (index) blobs, which is what a commit
# will contain and what raw.githubusercontent.com will serve, so stage new files first and
# unstaged edits are ignored.

set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:---check}"
case "$mode" in --write|--check) ;; *) echo "usage: $0 [--write|--check]" >&2; exit 2 ;; esac

cd "$repo_root"
python3 -I - "$mode" <<'PY'
import hashlib, os, re, subprocess, sys

mode = sys.argv[1]
roots = ("dot_claude/commands/", "dot_claude/agents/", "dot_claude/skills/", "tools/", "workflow/adapters/")
skip = re.compile(r"(\.test\.sh|_test\.py)$|(^|/)test_[^/]*\.py$|^tools/examples/|^tools/lib/fixtures/")
safe = re.compile(r"^[A-Za-z0-9._/-]+$")

out = subprocess.run(["git", "ls-files", "-s", "-z"], capture_output=True, text=True, check=True).stdout
lines, bad = [], []
for entry in filter(None, out.split("\0")):
    meta, path = entry.split("\t", 1)
    perm, oid = meta.split()[0], meta.split()[1]
    if perm == "120000" or not path.startswith(roots) or skip.search(path):
        continue  # symlinks are never fetched or installed
    if not safe.match(path) or ".." in path.split("/"):
        bad.append(path)
        continue
    blob = subprocess.run(["git", "cat-file", "blob", oid], capture_output=True, check=True).stdout
    lines.append(f"{hashlib.sha256(blob).hexdigest()}  {'755' if perm == '100755' else '644'}  {path}\n")
if bad:
    sys.exit("workflow-manifest: paths not allowed in the manifest (letters, digits, . _ - / only): "
             + ", ".join(repr(b) for b in bad) + "; rename them or add them to the skip list")
text = "".join(sorted(lines, key=lambda l: l.split("  ", 2)[2]))

target = "workflow/manifest.txt"
if mode == "--write":
    os.makedirs("workflow", exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {target} ({len(lines)} files)")
else:
    current = open(target, encoding="utf-8").read() if os.path.exists(target) else ""
    if current != text:
        sys.exit(f"{target} is stale; run tools/workflow-manifest.sh --write")
    print(f"{target} is current ({len(lines)} files)")
PY
