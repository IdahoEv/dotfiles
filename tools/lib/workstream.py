#!/usr/bin/env python3
"""Workstream record, surface name resolver, and layered settings.

    workstream.py init-ticket --dir <wt> --provider <p> --ids <csv> [--urls <csv>] [--title <t>] [--desc <d>] [--type <ty>] [--tag <tag>]...
    workstream.py show [--dir <wt>]
    workstream.py chain-ids [--dir <wt>] [--fallback <id>]
    workstream.py chain-tag [--dir <wt>]
    workstream.py render <surface> [--dir <wt>]
    workstream.py setting <key> [--dir <wt>] [--env <VAR>] [--default <val>] [--with-source]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repo_facts  # noqa: E402

RECORD_FILENAME = ".workstream.json"
VALID_KINDS = ("ticket", "talk", "iteration")
VALID_FORMS = ("kebab", "words", "Title", "snake")
SURFACES = ("key", "base", "branch", "worktree", "row", "pr", "commit")

DEFAULT_SURFACE_FORMS: dict[str, str] = {
    "branch": "kebab",
    "worktree": "kebab",
    "row": "words",
    "pr": "words",
    "commit": "words",
}

TEMPLATE_KEYS: tuple[str, ...] = (
    "base",
    "branch.form",
    "branch.template",
    "worktree.form",
    "worktree.template",
    "row.form",
    "row.template",
    "pr.form",
    "pr.template",
    "commit.form",
    "commit.template",
    "commit.key_prefix",
    "provider.brief",    "provider.full",
    "provider.form",
    "chain.mode",
    "chain.sep",
    "desc.source",
    "desc.form",
)

PROVIDER_TOKENS: dict[str, dict[str, str]] = {
    "github": {"brief": "Is", "full": "Issue"},
    "shortcut": {"brief": "sc-", "full": "shortcut"},
}


@dataclasses.dataclass
class WorkstreamRecord:
    version: int = 1
    kind: str = "ticket"
    tickets: list[dict[str, str]] = dataclasses.field(default_factory=list)
    ticket_provider: str = ""
    key: str = ""
    key_aliases: list[str] = dataclasses.field(default_factory=list)
    desc: str = ""
    type: str = ""
    template_source: str = "default"
    tags: list[str] = dataclasses.field(default_factory=list)
    pr: dict[str, Any] | None = None
    reviews: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"local": 0, "remote": 0}
    )
    claude_sessions: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "kind": self.kind,
            "tickets": [{"id": str(t.get("id", "")), "url": str(t.get("url", ""))} for t in self.tickets],
            "ticket_provider": self.ticket_provider,
            "key": self.key,
            "key_aliases": list(self.key_aliases),
            "desc": self.desc,
            "type": self.type,
            "template_source": self.template_source,
            "tags": list(self.tags),
            "pr": dict(self.pr) if isinstance(self.pr, dict) else None,
            "reviews": {
                "local": int((self.reviews or {}).get("local", 0)),
                "remote": int((self.reviews or {}).get("remote", 0)),
            },
            "claude_sessions": list(self.claude_sessions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkstreamRecord:
        reviews_raw = data.get("reviews")
        reviews = {"local": 0, "remote": 0}
        if isinstance(reviews_raw, dict):
            reviews["local"] = int(reviews_raw.get("local", 0) or 0)
            reviews["remote"] = int(reviews_raw.get("remote", 0) or 0)
        tickets_raw = data.get("tickets") or []
        tickets = [
            {"id": str(t.get("id", "")), "url": str(t.get("url", ""))}
            for t in tickets_raw
            if isinstance(t, dict) and t.get("id")
        ]
        pr_raw = data.get("pr")
        pr = dict(pr_raw) if isinstance(pr_raw, dict) and pr_raw else None
        return cls(
            version=int(data.get("version", 1) or 1),
            kind=str(data.get("kind", "ticket") or "ticket"),
            tickets=tickets,
            ticket_provider=str(data.get("ticket_provider", "") or ""),
            key=str(data.get("key", "") or ""),
            key_aliases=[str(a) for a in (data.get("key_aliases") or [])],
            desc=str(data.get("desc", "") or ""),
            type=str(data.get("type", "") or ""),
            template_source=str(data.get("template_source", "default") or "default"),
            tags=[str(t) for t in (data.get("tags") or [])],
            pr=pr,
            reviews=reviews,
            claude_sessions=[str(s) for s in (data.get("claude_sessions") or [])],
        )


def resolve_setting(
    key: str,
    dir_: str = ".",
    env_var: str = "",
    default: str = "",
) -> tuple[str, str]:
    """Return (value, source) with precedence env > project > machine > user > default."""
    if env_var:
        env_val = os.environ.get(env_var, "")
        if env_val:
            return (env_val, "env")
    found = repo_facts.conf_get_source(key, dir_)
    if found is not None:
        return found
    return (default, "default")


def detect_template_source(dir_: str = ".") -> str:
    """Highest config tier ('project' | 'machine' | 'user' | 'default') supplying a template key."""
    rank = {"project": 3, "machine": 2, "user": 1, "default": 0}
    best = "default"
    for k in TEMPLATE_KEYS:
        found = repo_facts.conf_get_source(k, dir_)
        if found is not None and rank.get(found[1], 0) > rank[best]:
            best = found[1]
            if best == "project":
                return "project"
    return best


def _worktree_root(dir_: str = ".") -> str:
    top = repo_facts.git(dir_, "rev-parse", "--show-toplevel")
    return top if top else os.path.abspath(dir_)


def ensure_excluded(worktree: str) -> None:
    """Register .workstream.json in the repository's info/exclude file."""
    rel = repo_facts.git(worktree, "rev-parse", "--git-path", "info/exclude")
    if not rel:
        return
    exclude_path = Path(rel if os.path.isabs(rel) else os.path.join(worktree, rel))
    try:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_path.read_text(encoding="utf-8", errors="surrogateescape") if exclude_path.is_file() else ""
        lines = [line.strip() for line in existing.splitlines()]
        if RECORD_FILENAME not in lines and f"/{RECORD_FILENAME}" not in lines:
            prefix = "" if (not existing or existing.endswith("\n")) else "\n"
            with exclude_path.open("a", encoding="utf-8", errors="surrogateescape") as f:
                f.write(f"{prefix}{RECORD_FILENAME}\n")
    except OSError:
        pass


def save_record(worktree: str, record: WorkstreamRecord) -> str:
    """Atomically write .workstream.json in <worktree> and ensure info/exclude entry."""
    root = _worktree_root(worktree)
    ensure_excluded(root)
    target = os.path.join(root, RECORD_FILENAME)
    payload = json.dumps(record.to_dict(), indent=2) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=root, prefix=".workstream.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return target


def _legacy_chain_record(worktree: str) -> WorkstreamRecord | None:
    git_dir = repo_facts.git(worktree, "rev-parse", "--absolute-git-dir")
    if not git_dir:
        return None
    chain_path = Path(git_dir) / "chain"
    if not chain_path.is_file():
        return None
    try:
        text = chain_path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        return None
    ids = [line.strip() for line in text.splitlines() if line.strip()]
    if not ids:
        return None
    branch = repo_facts.git(worktree, "branch", "--show-current")
    scheme = repo_facts.ticket_scheme(branch) if branch else "github"
    provider = scheme if scheme in ("github", "shortcut") else "github"
    tickets = [{"id": tid, "url": ""} for tid in ids]
    rec = WorkstreamRecord(
        kind="ticket",
        tickets=tickets,
        ticket_provider=provider,
        template_source=detect_template_source(worktree),
    )
    rec.key = derive_key(rec, worktree)
    return rec


def load_record(worktree: str = ".") -> WorkstreamRecord | None:
    """Load .workstream.json from <worktree>, falling back to legacy <git-dir>/chain."""
    root = _worktree_root(worktree)
    path = Path(root) / RECORD_FILENAME
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return WorkstreamRecord.from_dict(data)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return _legacy_chain_record(root)


def format_text(text: str, form: str) -> str:
    """Render a phrase in kebab, words, Title, or snake form."""
    words = repo_facts._ascii_separate(text).split()
    if not words:
        return ""
    if form == "kebab":
        return "-".join(w.lower() for w in words)
    if form == "snake":
        return "_".join(w.lower() for w in words)
    if form == "Title":
        return repo_facts._title_words([w.upper() if re.fullmatch(r"[A-Z0-9]{2,}", w) else w.lower() for w in words])
    return " ".join(w.lower() for w in words)


def _provider_token(record: WorkstreamRecord, style: str = "", dir_: str = ".") -> str:
    provider = record.ticket_provider
    if not provider:
        return ""
    mode = style or resolve_setting("provider.form", dir_, default="brief")[0]
    if mode not in ("brief", "full"):
        mode = "brief"
    defaults = PROVIDER_TOKENS.get(provider, {"brief": f"{provider}-", "full": provider})
    custom = resolve_setting(f"provider.{mode}", dir_, default="")[0]
    return custom if custom else defaults[mode]


def _chain_token(record: WorkstreamRecord, option: str = "", dir_: str = ".") -> str:
    ids = [t["id"] for t in record.tickets if t.get("id")]
    if not ids:
        return ""
    sep = resolve_setting("chain.sep", dir_, default="+")[0] or "+"
    mode = option or resolve_setting("chain.mode", dir_, default="all")[0]
    if mode == "first":
        return ids[0]
    if mode == "last":
        return ids[-1]
    return sep.join(ids)


def derive_key(record: WorkstreamRecord, dir_: str = ".") -> str:
    """Compute deterministic key: {provider}{chain} for tickets, or stored key for talk/iteration."""
    if record.kind in ("talk", "iteration") and not record.tickets:
        return record.key
    prov = _provider_token(record, "", dir_)
    chain = _chain_token(record, "", dir_)
    if prov or chain:
        return f"{prov}{chain}"
    return record.key


def _phase_token(record: WorkstreamRecord) -> str:
    tags = list(record.tags)
    if record.kind == "talk" and "TALK" not in tags:
        tags.insert(0, "TALK")
    elif record.kind == "iteration" and "ITERATE" not in tags:
        tags.insert(0, "ITERATE")
    out = []
    for t in tags:
        t_clean = t.strip()
        if not t_clean:
            continue
        out.append(t_clean if (t_clean.startswith("[") and t_clean.endswith("]")) else f"[{t_clean}]")
    return "".join(out)


def _clean_rendered(text: str, form: str) -> str:
    """Collapse empty optional prefixes/separators left by empty tokens like {type} or {phase}."""
    s = text.strip()
    # Strip leading '/', ':', '-', '_' left when a prefix token such as {type} is empty
    s = re.sub(r"^[/:\-_]+\s*", "", s)
    # Strip trailing '-', '_', ':' left when {desc} is empty
    s = re.sub(r"[\s:\-_]+$", "", s)
    if form == "kebab":
        s = re.sub(r"\s+", "-", s)
        s = re.sub(r"-{2,}", "-", s)
    elif form == "snake":
        s = re.sub(r"\s+", "_", s)
        s = re.sub(r"_{2,}", "_", s)
    else:
        s = re.sub(r" {2,}", " ", s)
    return s.strip()


def render_base(record: WorkstreamRecord, form: str, dir_: str = ".") -> str:
    """Render the base template (default '{key} {desc}') in <form>."""
    base_tmpl, _ = resolve_setting("base", dir_, default="{key} {desc}")
    return render_template(base_tmpl, record, form=form, dir_=dir_, _in_base=True)


def render_template(
    template: str,
    record: WorkstreamRecord,
    form: str = "words",
    dir_: str = ".",
    _in_base: bool = False,
) -> str:
    """Render a template string containing {provider}, {chain}, {desc}, {type}, {base}, {phase}/{tags}, {key}."""
    key_val = derive_key(record, dir_)

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        opt = match.group(2) or ""
        if name == "key":
            return key_val
        if name == "provider":
            return _provider_token(record, opt, dir_)
        if name == "chain":
            return _chain_token(record, opt, dir_)
        if name == "desc":
            target_form = opt if opt in VALID_FORMS else form
            return format_text(record.desc, target_form)
        if name == "type":
            if not record.type:
                return ""
            target_form = opt if opt in VALID_FORMS else form
            return format_text(record.type, target_form)
        if name in ("phase", "tags"):
            return _phase_token(record)
        if name == "base":
            if _in_base:
                return f"{key_val} {format_text(record.desc, form)}".strip()
            return render_base(record, form=form, dir_=dir_)
        return match.group(0)

    rendered = re.sub(r"\{([a-z]+)(?::([A-Za-z0-9_+-]+))?\}", repl, template)
    return _clean_rendered(rendered, form)


def render_surface(record: WorkstreamRecord, surface: str, dir_: str = ".") -> str:
    """Render a named surface ('key' | 'base' | 'branch' | 'worktree' | 'row' | 'pr' | 'commit')."""
    if surface == "key":
        return derive_key(record, dir_)
    default_form = DEFAULT_SURFACE_FORMS.get(surface, "words")
    form, _ = resolve_setting(f"{surface}.form", dir_, default=default_form)
    if form not in VALID_FORMS:
        form = default_form

    if surface == "base":
        return render_base(record, form=form, dir_=dir_)

    tmpl, _ = resolve_setting(f"{surface}.template", dir_, default="")
    if not tmpl:
        if surface == "worktree":
            branch_tmpl, _ = resolve_setting("branch.template", dir_, default="")
            tmpl = branch_tmpl if branch_tmpl else "{base}"
        elif surface == "row":
            tmpl = "{phase} {base}"
        elif surface == "pr":
            _, base_src = resolve_setting("base", dir_, default="{key} {desc}")
            tmpl = "{base}" if base_src != "default" else "{key}: {desc}"
        elif surface == "commit":
            prefix_on, _ = resolve_setting("commit.key_prefix", dir_, default="false")
            tmpl = "{key}: {desc}" if prefix_on.lower() == "true" else "{desc}"
        else:
            tmpl = "{base}"

    out = render_template(tmpl, record, form=form, dir_=dir_)
    if surface == "worktree":
        out = out.replace("/", "-")
    return out


def init_ticket_record(
    worktree: str,
    provider: str,
    tickets: list[dict[str, str]],
    title: str = "",
    desc: str = "",
    type_: str = "",
    tags: list[str] | None = None,
) -> WorkstreamRecord:
    """Create or update .workstream.json in <worktree> for a ticket or chain."""
    root = _worktree_root(worktree)
    existing = load_record(root)

    # Single-ticket re-run on an existing chain worktree keeps the chain membership
    merged_tickets = list(tickets)
    if (
        existing is not None
        and len(tickets) == 1
        and len(existing.tickets) > 1
        and existing.tickets[0].get("id") == tickets[0].get("id")
    ):
        merged_tickets = [dict(t) for t in existing.tickets]
        if tickets[0].get("url"):
            merged_tickets[0]["url"] = tickets[0]["url"]

    if existing is not None and (
        not existing.tickets
        or not merged_tickets
        or existing.tickets[0].get("id") != merged_tickets[0].get("id")
    ):
        existing = None

    if not desc:
        if existing and existing.desc and not title and not os.environ.get("GT_LABEL_OVERRIDE"):
            desc = existing.desc
        else:
            raw_label = repo_facts.label_from_title(title) if title or os.environ.get("GT_LABEL_OVERRIDE") else ""
            desc = format_text(raw_label, "words")

    rec = WorkstreamRecord(
        version=1,
        kind="ticket",
        tickets=merged_tickets,
        ticket_provider=provider,
        key="",
        key_aliases=list(existing.key_aliases) if existing else [],
        desc=desc,
        type=type_ or (existing.type if existing else ""),
        template_source=detect_template_source(root),
        tags=list(tags) if tags is not None else (list(existing.tags) if existing else ["PLAN"]),
        pr=existing.pr if existing else None,
        reviews=dict(existing.reviews) if existing else {"local": 0, "remote": 0},
        claude_sessions=list(existing.claude_sessions) if existing else [],
    )
    rec.key = derive_key(rec, root)
    save_record(root, rec)
    return rec


def chain_ids(worktree: str = ".", fallback_ticket_id: str = "") -> list[str]:
    """Return ordered ticket IDs from .workstream.json or legacy <git-dir>/chain."""
    rec = load_record(worktree)
    if rec and rec.tickets:
        ids = [t["id"] for t in rec.tickets if t.get("id")]
        if ids:
            return ids
    return [fallback_ticket_id] if fallback_ticket_id else []


def chain_tag(worktree: str = ".") -> str:
    """Return '12+13' (or 'first+last' for 4+ tickets) for a chain worktree; '' for single ticket."""
    ids = chain_ids(worktree)
    if len(ids) < 2:
        return ""
    if len(ids) >= 4:
        return f"{ids[0]}+{ids[-1]}"
    return "+".join(ids)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workstream", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-ticket")
    p_init.add_argument("--dir", default=".")
    p_init.add_argument("--provider", required=True)
    p_init.add_argument("--ids", required=True, help="Comma-separated ticket IDs")
    p_init.add_argument("--urls", default="", help="Comma-separated ticket URLs")
    p_init.add_argument("--title", default="")
    p_init.add_argument("--desc", default="")
    p_init.add_argument("--type", dest="type_", default="")
    p_init.add_argument("--tag", dest="tags", action="append")

    p_show = sub.add_parser("show")
    p_show.add_argument("--dir", default=".")

    p_cids = sub.add_parser("chain-ids")
    p_cids.add_argument("--dir", default=".")
    p_cids.add_argument("--fallback", default="")

    p_ctag = sub.add_parser("chain-tag")
    p_ctag.add_argument("--dir", default=".")

    p_ren = sub.add_parser("render")
    p_ren.add_argument("surface", choices=SURFACES)
    p_ren.add_argument("--dir", default=".")
    p_ren.add_argument("--provider", default="")
    p_ren.add_argument("--ids", default="")
    p_ren.add_argument("--title", default="")
    p_ren.add_argument("--desc", default="")
    p_ren.add_argument("--type", dest="type_", default="")

    p_set = sub.add_parser("setting")
    p_set.add_argument("key")
    p_set.add_argument("--dir", default=".")
    p_set.add_argument("--env", default="")
    p_set.add_argument("--default", default="")
    p_set.add_argument("--with-source", action="store_true")

    return p


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        sys.exit("workstream: Python 3.11+ required")
    args = build_parser().parse_args(argv)

    if args.cmd == "init-ticket":
        ids = [i.strip() for i in args.ids.split(",") if i.strip()]
        urls = [u.strip() for u in args.urls.split(",")] if args.urls else []
        tickets = [
            {"id": tid, "url": urls[idx] if idx < len(urls) else ""}
            for idx, tid in enumerate(ids)
        ]
        init_ticket_record(
            args.dir,
            provider=args.provider,
            tickets=tickets,
            title=args.title,
            desc=args.desc,
            type_=args.type_,
            tags=args.tags,
        )
        return 0

    if args.cmd == "show":
        rec = load_record(args.dir)
        if rec is None:
            return 1
        sys.stdout.write(json.dumps(rec.to_dict(), indent=2) + "\n")
        return 0

    if args.cmd == "chain-ids":
        ids = chain_ids(args.dir, args.fallback)
        if ids:
            sys.stdout.write(",".join(ids))
        return 0

    if args.cmd == "chain-tag":
        tag = chain_tag(args.dir)
        if tag:
            sys.stdout.write(tag)
        return 0

    if args.cmd == "render":
        if args.ids:
            ids = [i.strip() for i in args.ids.split(",") if i.strip()]
            if args.desc:
                desc = format_text(repo_facts.sanitize_label(args.desc), "words")
            elif args.title or os.environ.get("GT_LABEL_OVERRIDE"):
                desc = format_text(repo_facts.label_from_title(args.title), "words")
            else:
                desc = ""
            rec = WorkstreamRecord(
                version=1,
                kind="ticket",
                tickets=[{"id": tid, "url": ""} for tid in ids],
                ticket_provider=args.provider or "github",
                desc=desc,
                type=args.type_,
                tags=["PLAN"],
            )
            rec.key = derive_key(rec, args.dir)
        else:
            rec = load_record(args.dir)
            if rec is None:
                return 1
        sys.stdout.write(render_surface(rec, args.surface, args.dir))
        return 0

    if args.cmd == "setting":
        val, src = resolve_setting(args.key, args.dir, env_var=args.env, default=args.default)
        if args.with_source:
            sys.stdout.write(f"{val}\t{src}")
        else:
            sys.stdout.write(val)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
