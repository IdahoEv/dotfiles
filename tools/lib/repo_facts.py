#!/usr/bin/env python3
"""Shared, read-only facts about a repo/branch (port of lib/repo-facts.sh).

    repo_facts.py default-branch [dir]           branch name, or exit 1
    repo_facts.py default-branch-ref [dir]       origin/<branch>, or exit 1
    repo_facts.py ticket-from-branch <branch>    ticket id, or nothing
    repo_facts.py ticket-scheme <branch>         shortcut | github | unknown
    repo_facts.py distill-title <title> [words]  "Short Label Words"
    repo_facts.py slug-title <title> [words]     "short-label-words"
    repo_facts.py sanitize-label <text>
    repo_facts.py label-from-title <title> [words]
    repo_facts.py overlays-root
    repo_facts.py repo-key <url>                 owner/repo, or nothing
    repo_facts.py overlay-dir [dir]  overlay-claude-dir [dir]
    repo_facts.py overlay-claude-files [kind] [dir]
    repo_facts.py main-root [dir]  conf-files [dir]  conf-get <key> [dir]
    repo_facts.py find-doc <name> [dir]          "path<TAB>repo|overlay", or exit 1
    repo_facts.py get <fact> [args…]             dispatcher, dash or underscore names

One subcommand per gt:: function of the sourced repo-facts.sh, so bash
consumers can call the CLI and Python consumers can import the functions.
Single-value subcommands print without a trailing newline (the shell used
printf '%s'); list subcommands print one line per item. Exit codes mirror the
shell: 1 when a fact is unresolved (default-branch, default-branch-ref,
conf-get, find-doc), 0 otherwise. Everything here is pure inspection: the only
network is the host CLI fallback in default_branch; no writes, no side effects.
"""

from __future__ import annotations

import argparse
import json
import locale
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

# Env cannot override these two: the shell version assigned them
# unconditionally at source time, discarding any inherited value.
STOPWORDS = frozenset(
    "a an the to for of in on and or with into from at by be is are as that this it".split()
)
VERBS = frozenset(
    "add build create decide define design document enable fix implement "
    "investigate make migrate port refactor remove survey update write".split()
)
DEFAULT_LABEL_WORDS = 4
DEFAULT_SLUG_WORDS = 5
DEFAULT_MAX_CHARS = 48


# ---- subprocess helpers ------------------------------------------------------

def run_cmd(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    # surrogateescape: git emits raw bytes (ref names, config values) and the
    # shell passed them through; a strict decode would crash instead.
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          errors="surrogateescape", check=False)


def git(dir_: str, *args: str) -> str:
    """git -C stdout, or "" when the command fails (the shell's `|| true`)."""
    r = run_cmd(["git", "-C", dir_, *args])
    return r.stdout.strip() if r.returncode == 0 else ""


def git_ok(dir_: str, *args: str) -> bool:
    return run_cmd(["git", "-C", dir_, *args]).returncode == 0


# ---- default branch ----------------------------------------------------------

def _branch_from_origin_head(dir_: str) -> str:
    b = git(dir_, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return b.removeprefix("origin/")


def _branch_from_remote_show(dir_: str) -> str:
    r = run_cmd(["git", "-C", dir_, "remote", "show", "origin"])
    if r.returncode != 0:
        return ""
    # Only the FIRST matching line counts (sed | head -1): if it says
    # "(unknown)", later lines are not consulted.
    marker = "HEAD branch: "
    for line in r.stdout.splitlines():
        i = line.rfind(marker)  # sed's .* is greedy: match the last occurrence
        if i != -1:
            b = line[i + len(marker):]
            return b if b and b != "(unknown)" else ""
    return ""


def _branch_from_gh(dir_: str) -> str:
    if not shutil.which("gh"):
        return ""
    if not git_ok(dir_, "rev-parse", "--show-toplevel"):
        return ""
    r = run_cmd(["gh", "repo", "view", "--json", "defaultBranchRef",
              "-q", ".defaultBranchRef.name"], cwd=dir_)
    return r.stdout.strip() if r.returncode == 0 else ""


def default_branch(dir_: str = ".") -> str:
    """Origin's default branch, unprefixed — never assume main/master.

    Order: refs/remotes/origin/HEAD (local) → `git remote show origin`
    (network) → the host CLI (GitHub only). "" when none answer.
    """
    for tier in (_branch_from_origin_head, _branch_from_remote_show, _branch_from_gh):
        b = tier(dir_)
        if b:
            return b
    return ""


def default_branch_ref(dir_: str = ".") -> str:
    """Same, as a verified origin/<branch> ref, probing the usual names.

    LOCAL-ONLY by design: reads refs/remotes/origin/HEAD and probes existing
    remote refs, never `git remote show origin` or a host CLI. Callers run
    this speculatively; staleness only ever over-reports work.
    """
    b = _branch_from_origin_head(dir_)
    if b and git_ok(dir_, "rev-parse", "--verify", "--quiet", f"origin/{b}"):
        return f"origin/{b}"
    for name in ("development", "main", "master"):
        if git_ok(dir_, "rev-parse", "--verify", "--quiet", f"origin/{name}"):
            return f"origin/{name}"
    return ""


# ---- ticket id from branch ---------------------------------------------------

def _record_ticket_info(dir_: str) -> tuple[str, str] | None:
    """Return (head_ticket_id, provider) from .workstream.json when present."""
    if not dir_:
        return None
    root = git(dir_, "rev-parse", "--show-toplevel") or dir_
    path = os.path.join(root, ".workstream.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    tickets = data.get("tickets")
    if not isinstance(tickets, list) or not tickets:
        return None
    first = tickets[0]
    if not isinstance(first, dict) or not first.get("id"):
        return None
    provider = str(data.get("ticket_provider") or "github")
    scheme = "shortcut" if provider == "shortcut" else "github"
    return str(first["id"]), scheme


def ticket_from_branch(branch: str, dir_: str | None = None) -> str:
    """Ticket id from .workstream.json (when dir_ is given) or branch name, or "".

    When parsing a branch:
    1. New resolver key prefix (`^(?:Is|sc-)([0-9]+)(?:\\+[0-9]+)*(?:-|/|$)`),
       returning the head ticket id.
    2. Legacy Shortcut (`sc-<id>`, last match wins).
    3. Legacy GitHub (`^([1-9][0-9]*)-`).
    """
    if dir_:
        info = _record_ticket_info(dir_)
        if info:
            return info[0]
    m = re.match(r"^(?:Is|sc-)([0-9]+)(?:\+[0-9]+)*(?:-|$)", branch)
    if m:
        return m.group(1)
    ids = re.findall(r"sc-([0-9]+)", branch)
    if ids:
        return ids[-1]
    m = re.match(r"([1-9][0-9]*)-", branch)
    return m.group(1) if m else ""


def ticket_scheme(branch: str, dir_: str | None = None) -> str:
    """Which dialect the workstream or branch uses: shortcut | github | unknown."""
    if dir_:
        info = _record_ticket_info(dir_)
        if info:
            return info[1]
    if re.match(r"^sc-[0-9]+(?:\+[0-9]+)*(?:-|$)", branch):
        return "shortcut"
    if re.match(r"^Is[0-9]+(?:\+[0-9]+)*(?:-|$)", branch):
        return "github"
    if re.search(r"sc-[0-9]+", branch):
        return "shortcut"
    if re.match(r"[1-9][0-9]*-", branch):
        return "github"
    return "unknown"


# ---- ticket title → short label ----------------------------------------------

def _ascii_separate(text: str) -> str:
    """Everything outside ASCII alphanumerics becomes a separator.

    Byte-level, like LC_ALL=C tr: each byte of a multibyte character is its
    own separator, so "Café" becomes "Caf  " — the result reaches git refs,
    and this is what keeps a branch name identical no matter the caller's
    locale. A str-level re.sub would leave "Café" one character off.
    """
    raw = text.encode("utf-8", "surrogateescape")
    return re.sub(rb"[^A-Za-z0-9]", b" ", raw).decode("ascii")


def _strip_title(title: str) -> str:
    # Repeatedly, so "[A] [ops] Thing" loses both tags; an inline bracket
    # ("Fix [a] thing") is not a leading tag and survives.
    tag = re.compile(r"^[ \t\n\v\f\r]*\[[^\]]*\](.*)$")
    while True:
        m = tag.match(title)
        if not m:
            break
        title = m.group(1)
    return re.sub(r"\([^)]*\)", "", title)  # parentheticals elaborate; drop them


def _kept_words(title: str) -> list[str]:
    noise = frozenset(os.environ.get("GT_LABEL_NOISE", "").split())
    words = _ascii_separate(_strip_title(title)).split()
    kept = [w for w in words if w.lower() not in STOPWORDS and w.lower() not in noise]
    # Drop a leading activity verb only when something survives it: "what"
    # discriminates better than "how" at a four-word budget.
    if len(kept) > 1 and kept[0].lower() in VERBS:
        kept = kept[1:]
    return kept


def _word_count(arg: str | int | None, env_var: str, default: int) -> int:
    """Explicit argument > env var > default; anything not >= 1 becomes 1.

    The clamp exists because maxw <= 0 would otherwise empty the result; an
    unset/empty/non-numeric value is a caller mistake, not a label choice.
    """
    raw = "" if arg is None else str(arg)
    if raw == "":
        raw = os.environ.get(env_var, "") or str(default)
    try:
        n = int(raw)
    except ValueError:
        n = 1
    return n if n >= 1 else 1


def _title_words(words: list[str]) -> str:
    out = []
    for w in words:  # acronyms (APM, ADR, SQL) keep their case
        out.append(w if re.fullmatch(r"[A-Z0-9]{2,}", w) else w[:1].upper() + w[1:])
    return " ".join(out)


def distill_title(title: str, max_words: int | str | None = None) -> str:
    """Distill a ticket title to the few words that identify the work.

    Keeps the LAST n words, not the first: English puts the head of a noun
    phrase at the end, and the head is what distinguishes one ticket from
    another. GT_LABEL_WORDS (default 4) and GT_LABEL_NOISE tune it per repo.
    """
    kept = _kept_words(title)
    if not kept:
        return ""
    maxw = _word_count(max_words, "GT_LABEL_WORDS", DEFAULT_LABEL_WORDS)
    return _title_words(kept[-maxw:])


def sanitize_label(text: str) -> str:
    """Flatten caller-supplied text to "Safe Label Words", or "".

    A label override reaches a branch name, so it is sanitized rather than
    trusted: word characters only, collapsed, trimmed, capped on a word
    boundary (never mid-word) at GT_LABEL_MAX_CHARS (default 48, validated
    per call so a caller can change it after import).
    """
    words = _ascii_separate(text).split()
    if not words:
        return ""
    s = " ".join(words)
    raw = os.environ.get("GT_LABEL_MAX_CHARS", "")
    maxc = int(raw) if re.fullmatch(r"[1-9][0-9]*", raw) else DEFAULT_MAX_CHARS
    while len(s) > maxc and " " in s:
        s = s[: s.rfind(" ")]
    return s if len(s) <= maxc else ""


def label_from_title(title: str, max_words: int | str | None = None) -> str:
    """The label every consumer should print: override if usable, else distill.

    The override reaches the DISPLAY LABEL only — nothing matches on it — so
    a caller with judgment (/start) may win here. An unset, empty, or
    unusable override silently falls back to the distiller.
    """
    override = os.environ.get("GT_LABEL_OVERRIDE", "")
    if override:
        sanitized = sanitize_label(override)
        if sanitized:
            return sanitized
    return distill_title(title, max_words)


def slug_title(title: str, max_words: int | str | None = None) -> str:
    """The same distillation, lowercased and hyphenated, for a git ref.

    DELIBERATELY ignores GT_LABEL_OVERRIDE: a branch name is matched against
    later (find_ticket_branch, an open PR, the user's shell history), so a
    name that varies between two runs of the same ticket is a defect.
    GT_LABEL_SLUG_OVERRIDE is the escape hatch for a caller that means it;
    slugs get a wider budget (GT_LABEL_SLUG_WORDS, default 5) because a
    branch name is read deliberately, not scanned.
    """
    d = ""
    override = os.environ.get("GT_LABEL_SLUG_OVERRIDE", "")
    if override:
        d = sanitize_label(override)
    if not d:
        d = distill_title(title, _word_count(max_words, "GT_LABEL_SLUG_WORDS",
                                             DEFAULT_SLUG_WORDS))
    return d.lower().replace(" ", "-") if d else ""


# ---- per-project config ------------------------------------------------------

def overlays_root() -> str:
    """Root of the per-machine config overlays, keyed by origin remote."""
    if os.environ.get("PROJECT_OVERLAYS_DIR", ""):
        return os.environ["PROJECT_OVERLAYS_DIR"]
    if os.environ.get("GIT_TOOLS_PROJECTS_DIR", ""):
        print("GIT_TOOLS_PROJECTS_DIR is deprecated; use PROJECT_OVERLAYS_DIR",
              file=sys.stderr)
        return os.environ["GIT_TOOLS_PROJECTS_DIR"]
    return os.path.join(os.path.expanduser("~"), ".config", "project-overlays")


def repo_key(url: str) -> str:
    """<owner>/<repo> (or <group>/<sub>/<repo>) from an origin URL, or "".

    scp-style ssh, ssh:// and https forms; trailing .git and / stripped once;
    the host is not part of the key. A "." or ".." segment is rejected — a
    hostile or typo'd remote ("../r") must not point the overlay outside the
    root. Unparseable is "" (not an error): a local remote has no overlay.
    """
    u = url.removesuffix("/").removesuffix(".git")
    if "://" in u:
        path = u.split("://", 1)[1]
        path = path.split("/", 1)[1] if "/" in path else path
    elif ":" in u:
        path = u.split(":", 1)[1]
    else:
        return ""
    if not re.fullmatch(r"[^/]+(/[^/]+)+", path):  # two or more segments
        return ""
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        # bash's =~ fails on invalid UTF-8, so the shell printed nothing for
        # such a remote; a key that can't round-trip can't name a directory.
        return ""
    if "." in path.split("/") or ".." in path.split("/"):
        return ""
    return path


def overlay_dir(dir_: str = ".") -> str:
    """Overlay directory for the repo containing <dir>; "" without an origin.

    The directory itself may not exist yet — callers test for the files
    they want.
    """
    url = git(dir_, "remote", "get-url", "origin")
    key = repo_key(url) if url else ""
    return f"{overlays_root()}/{key}" if key else ""


def overlay_claude_dir(dir_: str = ".") -> str:
    """<overlay>/claude — personal, project-scoped Claude assets, or ""."""
    ov = overlay_dir(dir_)
    return f"{ov}/claude" if ov else ""


def collated(paths: list[str]) -> list[str]:
    """Glob order: bash sorted each expansion with the caller's strcoll, and
    the listing order is part of the byte-identical output."""
    try:
        prev = locale.setlocale(locale.LC_COLLATE, "")
        try:
            return sorted(paths, key=locale.strxfrm)
        finally:
            locale.setlocale(locale.LC_COLLATE, prev)
    except locale.Error:
        # An un-settable locale falls back to codepoint order, as bash does.
        return sorted(paths)


def overlay_claude_files(kind: str = "", dir_: str = ".") -> list[str]:
    """Every Claude asset file under <overlay>/claude, one path per line.

    <kind> limits the listing to one subdirectory (agents|commands|skills);
    "" (or an explicitly passed empty string, as callers do) lists all three.
    Within skills, */SKILL.md follows the top-level *.md, matching the shell.
    """
    cd = overlay_claude_dir(dir_)
    if not cd:
        return []
    subs = [kind] if kind else ["agents", "commands", "skills"]
    root = Path(cd)
    out: list[str] = []
    for sub in subs:
        # pathlib globs match leading dots; the shell globs never did.
        out += collated([str(p) for p in (root / sub).glob("*.md")
                          if p.is_file() and not p.name.startswith(".")])
        if sub == "skills":
            out += collated(
                [str(p) for p in (root / "skills").glob("*/SKILL.md")
                 if p.is_file() and not p.parent.name.startswith(".")])
    return out


def main_root(dir_: str = ".") -> str:
    """The main checkout's root, even from a linked worktree; "" outside.

    rev-parse --git-common-dir may be relative (to <dir>); canonicalize like
    cd -P so a symlinked path resolves to the real location.
    """
    common = git(dir_, "rev-parse", "--git-common-dir")
    if not common:
        return ""
    p = Path(common) if common.startswith("/") else Path(dir_ or ".") / common
    try:
        return str(p.resolve(strict=True).parent)
    except OSError:
        return ""


def conf_layers(dir_: str = ".") -> list[tuple[str, str]]:
    """Config files with their layer ('project' | 'machine' | 'user'),
    highest precedence first."""
    layers: list[tuple[str, str]] = []
    top = git(dir_, "rev-parse", "--show-toplevel")
    if top:
        layers.append(("project", f"{top}/.start-ticket.conf"))
    main = main_root(dir_)
    if main:
        layers.append(("project", f"{main}/.start-ticket.conf"))
    ov = overlay_dir(dir_)
    if ov:
        layers.append(("project", f"{ov}/start-ticket.conf"))
    home = os.path.expanduser("~")
    layers.append(("machine", os.path.join(home, ".config", "start-ticket", "config")))
    layers.append(("user", f"{overlays_root()}/start-ticket.conf"))
    layers.append(("user", os.path.join(home, ".config", "start-ticket", "user.conf")))
    return layers


def conf_files(dir_: str = ".") -> list[str]:
    """Config files for the repo containing <dir>, highest precedence first:
    project (.start-ticket.conf, overlay), machine (~/.config/start-ticket/config),
    and user (<overlays-root>/start-ticket.conf, ~/.config/start-ticket/user.conf)."""
    return [path for _, path in conf_layers(dir_)]


def conf_get_source(key: str, dir_: str = ".") -> tuple[str, str] | None:
    """First non-empty `key=` across conf_layers as (value, layer); None when unset."""
    for layer, path in conf_layers(dir_):
        p = Path(path)
        if not p.is_file():
            continue
        try:
            # newline="" and split("\n"): sed split on \n only, so a \r from a
            # CRLF file stays in the value, and read_text() would eat it.
            with p.open(newline="", errors="surrogateescape") as f:
                lines = f.read().split("\n")
        except OSError:
            continue
        for line in lines:
            if line.startswith(f"{key}="):
                value = line[len(key) + 1:]
                if value:
                    return (value, layer)
                break
    return None


def conf_get(key: str, dir_: str = ".") -> str | None:
    """First non-empty `key=` across conf_files; None when unset.

    Per file only the first matching line counts (sed | head -1): an empty
    value on it moves the search to the next FILE, not the next line.
    """
    res = conf_get_source(key, dir_)
    return res[0] if res is not None else None


def find_doc(name: str, dir_: str = ".") -> tuple[str, str] | None:
    """Whole-file docs (governor.md, kickoff-preamble.md): the repo's
    .claude/<name> if present, else the overlay's <name> (or claude/<name>).
    No merging — a committed file replaces the overlay's outright.
    Returns (path, "repo"|"overlay"), or None if neither exists."""
    top = git(dir_, "rev-parse", "--show-toplevel")
    if top:
        p = Path(top) / ".claude" / name
        if p.is_file():
            return (str(p), "repo")
    ov = overlay_dir(dir_)
    if ov:
        for candidate in (Path(ov) / name, Path(ov) / "claude" / name):
            if candidate.is_file():
                return (str(candidate), "overlay")
    return None


# ---- CLI ----------------------------------------------------------------------

class _Spec:
    """One subcommand: the function, its positional argument names, the
    exit code when the fact resolves to nothing (1 only where the shell
    returned 1), and whether the shell's output ended with a newline."""

    def __init__(self, name: str, fn: Callable, fields: tuple[str, ...],
                 rc_empty: int = 0, newline: bool = False) -> None:
        self.name = name
        self.fn = fn
        self.fields = fields
        self.rc_empty = rc_empty
        self.newline = newline


SPECS = [
    _Spec("default-branch", default_branch, ("dir",), rc_empty=1),
    _Spec("default-branch-ref", default_branch_ref, ("dir",), rc_empty=1),
    _Spec("ticket-from-branch", ticket_from_branch, ("branch",)),
    _Spec("ticket-scheme", ticket_scheme, ("branch",)),
    _Spec("distill-title", distill_title, ("title", "max_words")),
    _Spec("slug-title", slug_title, ("title", "max_words")),
    _Spec("sanitize-label", sanitize_label, ("text",)),
    _Spec("label-from-title", label_from_title, ("title", "max_words")),
    _Spec("overlays-root", overlays_root, ()),
    _Spec("repo-key", repo_key, ("url",)),
    _Spec("overlay-dir", overlay_dir, ("dir",)),
    _Spec("overlay-claude-dir", overlay_claude_dir, ("dir",)),
    _Spec("overlay-claude-files", overlay_claude_files, ("kind", "dir")),
    _Spec("main-root", main_root, ("dir",), newline=True),  # ended in dirname
    _Spec("conf-files", conf_files, ("dir",)),
    _Spec("conf-get", conf_get, ("key", "dir"), rc_empty=1),
    _Spec("find-doc", find_doc, ("name", "dir"), rc_empty=1),
]

_OPTIONAL_DEFAULTS = {"dir": ".", "kind": "", "max_words": None}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="repo-facts", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for spec in SPECS:
        a = sub.add_parser(spec.name)
        for field in spec.fields:
            if field in _OPTIONAL_DEFAULTS:
                a.add_argument(field, nargs="?", default=_OPTIONAL_DEFAULTS[field])
            else:
                a.add_argument(field)
    g = sub.add_parser("get", help="get <fact> [args…]: dash or underscore names")
    g.add_argument("rest", nargs=argparse.REMAINDER)
    return p


def _emit(value: str | list[str] | tuple[str, str] | None, rc_empty: int,
          newline: bool = False) -> int:
    if isinstance(value, list):
        for item in value:
            sys.stdout.write(f"{item}\n")
        return 0
    if isinstance(value, tuple):
        value = f"{value[0]}\t{value[1]}"
    if value is None or value == "":
        return rc_empty
    sys.stdout.write(value)  # no trailing newline: the shell used printf '%s'
    if newline:
        sys.stdout.write("\n")
    return 0


def run(args: argparse.Namespace) -> int:
    if args.cmd == "get":
        if not args.rest:
            print("repo-facts: get needs a fact name", file=sys.stderr)
            return 2
        fact = args.rest[0].replace("_", "-")
        if fact not in {s.name for s in SPECS}:
            print(f"repo-facts: unknown fact: {args.rest[0]}", file=sys.stderr)
            return 2
        return main([fact, *args.rest[1:]])
    spec = next((s for s in SPECS if s.name == args.cmd), None)
    if spec is None:  # unreachable: argparse validates subcommand names
        return 2
    value = spec.fn(*(getattr(args, f) for f in spec.fields))
    return _emit(value, spec.rc_empty, spec.newline)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 13):
        sys.exit("repo_facts: Python 3.13+ required; install with: pyenv install 3.13")
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) > 1 and argv[0] in {s.name for s in SPECS if s.fields}:
        # The shell functions took "$1" verbatim: a leading-dash value is
        # data, not a flag ("--" ends option parsing for everything after).
        # Only specs with positionals: a bare "--" is itself an unrecognized
        # argument for a subcommand that takes none (overlays-root).
        argv = [argv[0], "--", *argv[1:]]
    # Facts may carry non-UTF-8 bytes from git (surrogateescape in run_cmd);
    # stdout must pass them back through as bytes, as printf did.
    sys.stdout.reconfigure(errors="surrogateescape")
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
