"""Compare closed PR Copilot findings against local /local-review-cycle telemetry.

Joins local review.finding, review.launch, review.round, and pr.open events
with Copilot review comments from `gh` (or logged source=bot events under
--no-gh), matches Copilot-valid findings against local findings, classifies
each miss, and writes a local uncommitted report with improvement proposals.
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repo_facts  # noqa: E402
import wf_backfill  # noqa: E402

MISS_CLASSES = (
    "code not in the diff the reviewer saw",
    "reviewer not selected",
    "outside reviewer scope",
    "reviewer ran and missed",
)

_STOPWORDS = frozenset({
    "the", "and", "for", "that", "this", "with", "from", "are", "was", "were",
    "will", "can", "may", "not", "but", "when", "where", "which", "into",
    "have", "has", "had", "been", "being", "does", "did", "should", "would",
    "could", "there", "their", "them", "then", "than", "also", "only", "use",
    "using", "used", "file", "line", "code", "function", "method", "value",
})

_DEFAULT_REVIEWER_SIGNALS = {
    "security-reviewer": {
        "keywords": ("auth", "token", "secret", "password", "credential", "inject",
                     "sql", "xss", "ssrf", "csrf", "traversal", "sanitize", "escape",
                     "crypto", "permission", "privilege", "idor", "untrusted"),
        "exts": (),
    },
    "supply-chain-reviewer": {
        "keywords": ("workflow", "github-actions", "dockerfile", "dependency",
                     "lockfile", "pin", "sha256", "checksum", "ci", "deploy",
                     "secret", "env", "package"),
        "exts": (".yml", ".yaml", ".toml", ".lock"),
        "paths": (".github/workflows/", "Dockerfile", "package.json", "requirements"),
    },
    "prompt-reviewer": {
        "keywords": ("prompt", "instruction", "frontmatter", "skill", "agent",
                     "ambiguous", "contradict", "rubric", "use_when"),
        "exts": (".md",),
        "paths": ("dot_claude/", ".claude/", "agents/", "skills/", "commands/"),
    },
    "architecture-reviewer": {
        "keywords": ("coupling", "layer", "abstraction", "boundary", "circular",
                     "responsibility", "interface", "module", "dependency", "design"),
        "exts": (),
    },
    "robustness-reviewer": {
        "keywords": ("error", "exception", "retry", "timeout", "cleanup", "leak",
                     "race", "concurrent", "concurr", "lock", "deadlock", "null",
                     "none", "empty", "crash", "panic", "dispose", "resource",
                     "rollback", "partial"),
        "exts": (),
    },
    "correctness-reviewer": {
        "keywords": ("bug", "wrong", "incorrect", "off-by-one", "boundary", "edge",
                     "condition", "return", "logic", "fail", "regression", "stale",
                     "mismatch", "invalid", "missing", "never", "always", "check",
                     "test", "assert"),
        "exts": (),
    },
}

_NON_CODE_EXTS = frozenset({".md", ".txt", ".rst", ".png", ".jpg", ".svg", ".json", ".csv"})
_THEME_PATTERNS = (
    ("null / empty / bounds checks", re.compile(r"\b(null|none|nil|empty|bound|range|index|overflow|zero)\b", re.I)),
    ("error handling / resource cleanup", re.compile(r"\b(error|exception|catch|throw|cleanup|dispose|close|leak|timeout|retry)\b", re.I)),
    ("concurrency / state ordering", re.compile(r"\b(race|lock|async|await|thread|concurr|order|stale|atomic)\b", re.I)),
    ("input validation / security guards", re.compile(r"\b(validat|sanitiz|escape|inject|auth|permission|traversal|untrusted)\b", re.I)),
    ("dead / unreachable / unused code or wiring", re.compile(r"\b(unused|dead|unreachable|never called|no caller|orphan)\b", re.I)),
    ("test coverage / assertions", re.compile(r"\b(test|assert|mock|coverage|spec)\b", re.I)),
)


def norm_path(path):
    p = (path or "").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def tokenize(text):
    words = re.findall(r"[a-z0-9_]{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def claim_similarity(claim_a, claim_b, path=""):
    """Return (shared_token_count, similarity_ratio) between two claims."""
    p_toks = tokenize(path)
    ta = tokenize(claim_a) - p_toks
    tb = tokenize(claim_b) - p_toks
    shared = len(ta & tb)
    union = len(ta | tb)
    jaccard = (shared / union) if union else 0.0
    seq = difflib.SequenceMatcher(None, (claim_a or "").lower(), (claim_b or "").lower()).ratio()
    return shared, max(jaccard, seq)


def _parse_frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta = {}
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
        m = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.*)$", lines[i])
        if m:
            meta[m.group(1)] = m.group(2).strip().strip("\"'")
    body = "\n".join(lines[end + 1:]) if end is not None else text
    return meta, body


def load_project_config(repo_dir="."):
    """Load candidate reviewers and optional overlay config via repo_facts / project-config.sh."""
    overlay = repo_facts.overlay_dir(repo_dir)
    candidates = {}

    def _add_file(path, tier):
        try:
            text = Path(path).read_text(errors="replace")
        except OSError:
            return
        meta, body = _parse_frontmatter(text)
        name = meta.get("name") or Path(path).stem
        if not name.endswith("-reviewer") and "reviewer" not in name:
            return
        if name not in candidates:
            candidates[name] = {
                "name": name,
                "tier": tier,
                "path": str(path),
                "use_when": meta.get("use_when", ""),
                "description": meta.get("description", ""),
                "model": meta.get("model", ""),
                "body": body,
            }

    root = Path(repo_facts.main_root(repo_dir) or repo_dir)
    for p in sorted((root / ".claude" / "agents").glob("*.md")):
        _add_file(p, "project")
    for p in sorted((root / "docs" / "local" / "reviewers").glob("*.md")):
        _add_file(p, "local")
    for p in repo_facts.overlay_claude_files("agents", repo_dir):
        _add_file(p, "overlay")
    for base in (root / "dot_claude" / "agents", Path.home() / ".claude" / "agents"):
        for p in sorted(base.glob("*.md")):
            _add_file(p, "global")

    overlay_cfg = {}
    if overlay:
        cfg_path = Path(overlay) / "review-gaps.json"
        if cfg_path.is_file():
            try:
                overlay_cfg = json.loads(cfg_path.read_text(errors="replace"))
            except (OSError, ValueError):
                overlay_cfg = {}

    return {
        "overlay_dir": overlay,
        "candidates": candidates,
        "overlay_config": overlay_cfg,
    }


def _git_ok(repo_dir, *args):
    try:
        r = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True)
        return r.returncode == 0, r.stdout
    except OSError:
        return False, ""


def _map_line_via_diff(repo_dir, sha_from, sha_to, path, line):
    """Map line number from sha_from to sha_to using git diff -U0 hunk headers."""
    if line is None or not sha_from or not sha_to or sha_from == sha_to:
        return line
    ok, out = _git_ok(repo_dir, "diff", "-U0", sha_from, sha_to, "--", path)
    if not ok or not out:
        return line
    offset = 0
    for raw in out.splitlines():
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", raw)
        if not m:
            continue
        old_start = int(m.group(1))
        old_len = int(m.group(2) or "1")
        new_len = int(m.group(4) or "1")
        if line < old_start:
            break
        if old_start <= line < old_start + max(old_len, 1):
            return int(m.group(3))
        offset += new_len - old_len
    return line + offset


def _changed_in_range(repo_dir, sha_from, sha_to, path, line):
    """Return True if path (and line if given) was modified in sha_from..sha_to."""
    if not sha_from or not sha_to or sha_from == sha_to:
        return False
    ok_anc, _ = _git_ok(repo_dir, "merge-base", "--is-ancestor", sha_from, sha_to)
    if not ok_anc:
        return False
    ok, out = _git_ok(repo_dir, "diff", "-U0", f"{sha_from}..{sha_to}", "--", path)
    if not ok or not out.strip():
        return False
    if line is None:
        return True
    for raw in out.splitlines():
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", raw)
        if not m:
            continue
        new_start = int(m.group(1))
        new_len = max(int(m.group(2) or "1"), 1)
        if new_start - 3 <= line <= new_start + new_len + 3:
            return True
    return False


def _dedupe_local_findings(events):
    """Group local review.finding events by finding_id so multi-reviewer hits count once."""
    groups = {}
    ordered = []
    for e in events:
        if e.get("event") != "review.finding" or e.get("source") == "bot":
            continue
        fid = e.get("finding_id")
        key = ("id", fid) if fid else ("raw", norm_path(e.get("path")), e.get("line"), e.get("claim"))
        if key not in groups:
            item = {
                "path": norm_path(e.get("path")),
                "line": e.get("line"),
                "claim": e.get("claim") or "",
                "round": e.get("round"),
                "sha": e.get("sha") or "",
                "severity": e.get("severity") or "",
                "verdict": e.get("verdict") or "",
                "validity": e.get("validity") or "",
                "reviewers": [],
            }
            groups[key] = item
            ordered.append(item)
        rev = e.get("reviewer")
        if rev and rev not in groups[key]["reviewers"]:
            groups[key]["reviewers"].append(rev)
    return ordered


def _extract_copilot_findings(pr_data, logged_bot_events):
    """Build normalized Copilot findings from gh PR data, enriched by logged bot events."""
    by_cid = {e.get("comment_id"): e for e in logged_bot_events if e.get("comment_id") is not None}
    by_loc = {(norm_path(e.get("path")), e.get("line"), e.get("sha") or ""): e for e in logged_bot_events}

    comments = pr_data.get("comments") or []
    reviews = pr_data.get("reviews") or []
    threads = pr_data.get("threads") or []
    commit_files = pr_data.get("commit_files") or []

    resolved_by_cid = {}
    thread_replies_by_cid = defaultdict(list)
    for th in threads:
        nodes = (th.get("comments") or {}).get("nodes") or []
        if not nodes:
            continue
        root_id = nodes[0].get("databaseId")
        if root_id is not None:
            resolved_by_cid[root_id] = bool(th.get("isResolved"))
            thread_replies_by_cid[root_id].extend(nodes[1:])

    replies_by_parent = defaultdict(list)
    for c in comments:
        pid = c.get("in_reply_to_id")
        if pid is not None:
            replies_by_parent[pid].append(c)

    out = []
    for c in comments:
        login = (c.get("user") or {}).get("login") or ""
        if login not in wf_backfill._COPILOT_LOGINS or c.get("in_reply_to_id") is not None:
            continue
        cid = c["id"]
        path = norm_path(c.get("path"))
        line = c.get("original_line") or c.get("line")
        sha = c.get("original_commit_id") or c.get("commit_id") or ""
        created_at = c.get("created_at") or ""
        logged = by_cid.get(cid) or by_loc.get((path, line, sha))
        if logged:
            verdict = logged.get("verdict") or "deferred"
            validity = logged.get("validity") or "valid"
            reason = logged.get("reason") or ""
            claim = logged.get("claim") or wf_backfill.clean_bot_claim(path, c.get("body"))
            severity = logged.get("severity") or wf_backfill.parse_bot_severity(c.get("body"))
        else:
            replies = replies_by_parent.get(cid) or thread_replies_by_cid.get(cid) or []
            resolved = resolved_by_cid.get(cid, False)
            later = any(ts > created_at and path in files for ts, files in commit_files)
            verdict, validity, reason = wf_backfill.infer_bot_verdict(replies, resolved, later)
            claim = wf_backfill.clean_bot_claim(path, c.get("body"))
            severity = wf_backfill.parse_bot_severity(c.get("body"))
        out.append({
            "comment_id": cid, "path": path, "line": line, "sha": sha,
            "severity": severity, "verdict": verdict, "validity": validity,
            "reason": reason, "claim": claim,
        })

    for rv in reviews:
        login = (rv.get("user") or {}).get("login") or ""
        if login not in wf_backfill._COPILOT_LOGINS:
            continue
        submitted_at = rv.get("submitted_at") or ""
        rv_sha = rv.get("commit_id") or ""
        for item in wf_backfill.parse_suppressed_review_body(rv.get("body")):
            path = norm_path(item["path"])
            line = item["line"]
            logged = by_loc.get((path, line, rv_sha))
            if logged:
                verdict = logged.get("verdict") or "deferred"
                validity = logged.get("validity") or "valid"
                reason = logged.get("reason") or ""
                claim = logged.get("claim") or wf_backfill.clean_bot_claim(path, item["text"])
                severity = logged.get("severity") or wf_backfill.parse_bot_severity(item["text"])
            else:
                later = any(ts > submitted_at and path in files for ts, files in commit_files)
                verdict, validity, reason = wf_backfill.infer_bot_verdict([], item["resolved"], later)
                claim = wf_backfill.clean_bot_claim(path, item["text"])
                severity = wf_backfill.parse_bot_severity(item["text"])
            out.append({
                "comment_id": None, "path": path, "line": line, "sha": rv_sha,
                "severity": severity, "verdict": verdict, "validity": validity,
                "reason": reason, "claim": claim,
            })
    return out


def match_finding(bot_f, local_findings, round_shas, repo_dir=None):
    """Return the best matching local finding dict or None."""
    b_path = norm_path(bot_f.get("path"))
    b_line = bot_f.get("line")
    b_sha = bot_f.get("sha") or ""
    b_claim = bot_f.get("claim") or ""
    best = None
    best_score = 0.0

    for lf in local_findings:
        if lf["path"] != b_path:
            continue
        l_line = lf["line"]
        if repo_dir and l_line is not None and b_sha:
            l_sha = lf["sha"] or round_shas.get(lf["round"], "")
            if l_sha:
                l_line = _map_line_via_diff(repo_dir, l_sha, b_sha, b_path, l_line)
        if b_line is not None and l_line is not None and abs(l_line - b_line) > 12:
            continue
        shared, ratio = claim_similarity(b_claim, lf["claim"], b_path)
        if shared >= 2 or ratio >= 0.35:
            score = shared + ratio
            if score > best_score:
                best_score = score
                best = lf
    return best


def _reviewer_matches_finding(name, candidate, path, claim, overlay_cfg):
    """Return True if reviewer `name` is relevant to (path, claim)."""
    ext = Path(path).suffix.lower()
    lower_claim = (claim or "").lower()
    lower_path = path.lower()

    ext_map = overlay_cfg.get("reviewer_extensions") or {}
    if name in ext_map:
        if ext in [e.lower() for e in ext_map[name]]:
            return True

    kw_map = overlay_cfg.get("reviewer_keywords") or {}
    if name in kw_map:
        if any(k.lower() in lower_claim or k.lower() in lower_path for k in kw_map[name]):
            return True

    sig = _DEFAULT_REVIEWER_SIGNALS.get(name)
    if sig:
        if any(lower_path.startswith(p.lower()) or p.lower() in lower_path for p in sig.get("paths", ())):
            return True
        if ext and ext in sig.get("exts", ()):
            return True
        if name == "correctness-reviewer" and ext not in _NON_CODE_EXTS:
            return True
        if any(k in lower_claim for k in sig["keywords"]):
            return True

    if candidate and candidate.get("use_when"):
        uw_tokens = tokenize(candidate["use_when"])
        finding_tokens = tokenize(f"{path} {claim}")
        if len(uw_tokens & finding_tokens) >= 2:
            return True
    return False


def classify_miss(bot_f, run_info, project_cfg, repo_dir=None):
    """Classify a missed Copilot-valid finding into one of MISS_CLASSES.

    Returns (classification, evidence_str).
    """
    round_shas = run_info["round_shas"]
    ran_reviewers = run_info["ran_reviewers"]
    path = bot_f["path"]
    line = bot_f["line"]
    b_sha = bot_f.get("sha") or ""
    claim = bot_f.get("claim") or ""
    overlay_cfg = project_cfg.get("overlay_config") or {}
    candidates = project_cfg.get("candidates") or {}

    if not ran_reviewers and not round_shas:
        return "code not in the diff the reviewer saw", "no local review rounds/launches recorded for run"

    if round_shas and b_sha and repo_dir:
        last_round = max(round_shas)
        last_sha = round_shas[last_round]
        if last_sha and b_sha != last_sha and _changed_in_range(repo_dir, last_sha, b_sha, path, line):
            return (
                "code not in the diff the reviewer saw",
                f"modified after local R{last_round} SHA {last_sha[:7]} (Copilot saw {b_sha[:7]})",
            )

    for pat in overlay_cfg.get("outside_scope_patterns") or []:
        if re.search(pat, path, re.I) or re.search(pat, claim, re.I):
            return "outside reviewer scope", f"matched overlay outside_scope_patterns ({pat})"

    # Check if an existing candidate reviewer that matches this finding did not run.
    unselected = []
    for name, cand in sorted(candidates.items()):
        if name in ran_reviewers:
            continue
        if name == "correctness-reviewer" and Path(path).suffix.lower() in _NON_CODE_EXTS:
            continue
        if _reviewer_matches_finding(name, cand, path, claim, overlay_cfg):
            # Only flag specialized reviewers (or correctness-reviewer if it didn't run at all)
            if name != "architecture-reviewer" or any(k in claim.lower() for k in _DEFAULT_REVIEWER_SIGNALS["architecture-reviewer"]["keywords"]):
                unselected.append(name)

    if unselected:
        return "reviewer not selected", f"ran={','.join(sorted(ran_reviewers)) or 'none'}; not selected={','.join(unselected)}"

    # Check if any reviewer that ran actually covers this file/defect domain.
    ran_relevant = [
        r for r in sorted(ran_reviewers)
        if _reviewer_matches_finding(r, candidates.get(r), path, claim, overlay_cfg)
    ]
    if not ran_relevant:
        return "outside reviewer scope", f"ran={','.join(sorted(ran_reviewers)) or 'none'}; no running reviewer rubric covers {path}"

    return "reviewer ran and missed", f"ran={','.join(ran_relevant)}"


def _fetch_pr_meta(number, repo):
    return wf_backfill._gh_json([
        "pr", "view", str(number), "--repo", repo,
        "--json", "number,title,url,state,mergedAt,headRefName,baseRefOid,headRefOid",
    ])


def _index_events(events):
    """Group telemetry events by run_id and index pr_number -> run_id."""
    by_run = defaultdict(list)
    pr_to_run = {}
    for e in events:
        rid = e.get("run_id")
        if not rid:
            continue
        by_run[rid].append(e)
        if e.get("event") == "pr.open" and e.get("pr_number") is not None:
            pr_to_run[((e.get("repo") or "").lower(), int(e["pr_number"]))] = rid
    return by_run, pr_to_run


def _build_run_info(run_events):
    round_shas = {}
    ran_reviewers = set()
    launches = []
    for e in run_events:
        ev = e.get("event")
        if ev == "review.round" and e.get("state") == "start" and e.get("round") is not None and e.get("sha"):
            round_shas[int(e["round"])] = e["sha"]
        elif ev == "review.launch" and e.get("reviewer"):
            ran_reviewers.add(e["reviewer"])
            launches.append({
                "reviewer": e["reviewer"],
                "round": e.get("round"),
                "model": e.get("model") or "unknown",
                "effort": e.get("effort") or "default",
            })
        elif ev == "review.result" and e.get("source") != "bot" and e.get("reviewers"):
            for r in str(e["reviewers"]).split(","):
                r = r.strip()
                if r:
                    ran_reviewers.add(r)
    return {
        "round_shas": round_shas,
        "ran_reviewers": ran_reviewers,
        "launches": launches,
        "local_findings": _dedupe_local_findings(run_events),
    }


def analyze_prs(pr_records, events, project_cfg, repo_dir=None):
    """Join PR Copilot findings with local telemetry and classify misses."""
    by_run, pr_to_run = _index_events(events)
    results = []
    model_stats = defaultdict(lambda: {"launches": 0, "runs": set(), "misses": 0})

    for rec in pr_records:
        repo = rec["repo"]
        pr_num = rec["number"]
        branch = rec["branch"]
        run_id = rec.get("run_id")
        if not run_id:
            run_id = pr_to_run.get((repo.lower(), pr_num))
        if not run_id:
            run_id, _, _ = wf_backfill.resolve_run_identity(branch, repo, events)

        run_events = by_run.get(run_id, []) if run_id else []
        run_info = _build_run_info(run_events)
        logged_bot = [e for e in run_events if e.get("event") == "review.finding" and e.get("source") == "bot"]
        bot_findings = rec["bot_findings"] if rec.get("bot_findings") is not None else _extract_copilot_findings(rec["pr_data"], logged_bot)

        valid_bot = [b for b in bot_findings if b.get("validity") in ("valid", "partial")]
        rejected_bot = [b for b in bot_findings if b.get("validity") == "rejected"]

        matched, missed = [], []
        for bf in valid_bot:
            m = match_finding(bf, run_info["local_findings"], run_info["round_shas"], repo_dir=repo_dir)
            if m:
                matched.append({"bot": bf, "local": m})
            else:
                cls, evidence = classify_miss(bf, run_info, project_cfg, repo_dir=repo_dir)
                missed.append({"bot": bf, "classification": cls, "evidence": evidence})

        for ln in run_info["launches"]:
            key = (ln["reviewer"], ln["model"], ln["effort"])
            model_stats[key]["launches"] += 1
            if run_id:
                model_stats[key]["runs"].add(run_id)
            if any(ms["classification"] == "reviewer ran and missed" and ln["reviewer"] in ms["evidence"] for ms in missed):
                model_stats[key]["misses"] += 1

        results.append({
            "repo": repo,
            "pr": pr_num,
            "title": rec.get("title", ""),
            "url": rec.get("url", ""),
            "branch": branch,
            "run_id": run_id,
            "local_finding_count": len(run_info["local_findings"]),
            "ran_reviewers": sorted(run_info["ran_reviewers"]),
            "bot_total": len(bot_findings),
            "bot_valid": len(valid_bot),
            "bot_rejected": len(rejected_bot),
            "matched": matched,
            "missed": missed,
        })

    model_rows = [
        {"reviewer": k[0], "model": k[1], "effort": k[2],
         "launches": v["launches"], "runs": len(v["runs"]), "misses": v["misses"]}
        for k, v in sorted(model_stats.items())
    ]
    return {"prs": results, "model_stats": model_rows}


def build_proposals(analysis):
    """Generate prompt, focus-agent, and model/effort proposals from classified misses."""
    all_misses = [
        (pr, ms) for pr in analysis["prs"] for ms in pr["missed"]
    ]
    ran_missed = [(pr, ms) for pr, ms in all_misses if ms["classification"] == "reviewer ran and missed"]
    not_selected = [(pr, ms) for pr, ms in all_misses if ms["classification"] == "reviewer not selected"]
    out_scope = [(pr, ms) for pr, ms in all_misses if ms["classification"] == "outside reviewer scope"]
    not_in_diff = [(pr, ms) for pr, ms in all_misses if ms["classification"] == "code not in the diff the reviewer saw"]

    prompt_proposals = []
    theme_counts = Counter()
    for _, ms in ran_missed:
        claim = ms["bot"]["claim"]
        matched_theme = False
        for label, pat in _THEME_PATTERNS:
            if pat.search(claim):
                theme_counts[label] += 1
                matched_theme = True
        if not matched_theme:
            theme_counts["general logic / contract verification"] += 1
    for theme, count in theme_counts.most_common():
        prompt_proposals.append(
            f"Add explicit checklist item for **{theme}** ({count} `reviewer ran and missed` finding(s))."
        )
    if not prompt_proposals:
        prompt_proposals.append("No `reviewer ran and missed` findings in this sample; no prompt changes indicated.")

    agent_proposals = []
    if not_selected:
        missing_revs = Counter()
        for _, ms in not_selected:
            m = re.search(r"not selected=([^\s;]+)", ms["evidence"])
            if m:
                for r in m.group(1).split(","):
                    missing_revs[r] += 1
        for rev, count in missing_revs.most_common():
            agent_proposals.append(
                f"Broaden `use_when:` trigger for `{rev}` ({count} `reviewer not selected` miss(es))."
            )
    if out_scope:
        ext_counts = Counter(Path(ms["bot"]["path"]).suffix or "(no ext)" for _, ms in out_scope)
        exts = ", ".join(f"`{ext}` ({n})" for ext, n in ext_counts.most_common(5))
        agent_proposals.append(
            f"Consider a new focus agent (or project overlay reviewer via `project-config.sh`) for {exts} ({len(out_scope)} `outside reviewer scope` miss(es))."
        )
    if not agent_proposals:
        agent_proposals.append("No `reviewer not selected` or `outside reviewer scope` misses in this sample.")

    experiment_proposals = []
    for row in analysis["model_stats"]:
        if row["misses"] > 0:
            experiment_proposals.append(
                f"Test higher effort or a second model family on `{row['reviewer']}` (currently `model={row['model']}`, `effort={row['effort']}`, {row['misses']} missed run(s) across {row['runs']} run(s))."
            )
    if not_in_diff:
        experiment_proposals.append(
            f"Note: {len(not_in_diff)} miss(es) were `code not in the diff the reviewer saw` (post-local-review commits); consider re-running `/local-review-cycle` after late pre-PR edits."
        )
    if not experiment_proposals:
        experiment_proposals.append("No model/effort miss hotspots observed in `review.launch` telemetry.")

    return {
        "prompt_changes": prompt_proposals,
        "new_focus_agents": agent_proposals,
        "model_effort_experiments": experiment_proposals,
    }


def render_markdown(analysis, proposals):
    prs = analysis["prs"]
    total_valid = sum(p["bot_valid"] for p in prs)
    total_matched = sum(len(p["matched"]) for p in prs)
    total_missed = sum(len(p["missed"]) for p in prs)
    miss_rate = f"{(100.0 * total_missed / total_valid):.1f}%" if total_valid else "n/a"

    class_counts = Counter(ms["classification"] for p in prs for ms in p["missed"])
    lines = [
        "# Review-Gap Report (Local Review vs Copilot)",
        "",
        f"- **PRs analyzed:** {len(prs)}",
        f"- **Copilot-valid findings:** {total_valid} (matched locally: {total_matched}, missed: {total_missed}, miss rate: {miss_rate})",
        "",
        "## Miss Classification",
        "",
        "| Classification | Count |",
        "| --- | ---: |",
    ]
    for cls in MISS_CLASSES:
        lines.append(f"| {cls} | {class_counts[cls]} |")

    if analysis["model_stats"]:
        lines += [
            "",
            "## Reviewer Model & Effort Breakdown",
            "",
            "| Reviewer | Model | Effort | Launches | Runs | Missed Runs |",
            "| --- | --- | --- | ---: | ---: | ---: |",
        ]
        for r in analysis["model_stats"]:
            lines.append(f"| {r['reviewer']} | {r['model']} | {r['effort']} | {r['launches']} | {r['runs']} | {r['misses']} |")

    lines += ["", "## Missed Copilot-Valid Findings", ""]
    if total_missed == 0:
        lines.append("None.")
    else:
        lines += [
            "| PR | Location | Severity | Classification | Evidence | Claim |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for p in prs:
            for ms in p["missed"]:
                bf = ms["bot"]
                loc = f"`{bf['path']}:{bf['line']}`" if bf.get("line") else f"`{bf['path']}`"
                claim = (bf.get("claim") or "").replace("|", "\\|")
                ev = ms["evidence"].replace("|", "\\|")
                lines.append(f"| {p['repo']}#{p['pr']} | {loc} | {bf.get('severity', '')} | {ms['classification']} | {ev} | {claim} |")

    lines += [
        "",
        "## Proposals",
        "",
        "### Prompt Changes",
        *[f"- {item}" for item in proposals["prompt_changes"]],
        "",
        "### New Focus Agents",
        *[f"- {item}" for item in proposals["new_focus_agents"]],
        "",
        "### Multi-Model & Effort-Level Experiments",
        *[f"- {item}" for item in proposals["model_effort_experiments"]],
        "",
    ]
    return "\n".join(lines)


def _default_out_path(repo_dir):
    stamp = date.today().isoformat()
    ok, top = _git_ok(repo_dir, "rev-parse", "--show-toplevel")
    if ok and top.strip():
        return str(Path(top.strip()) / ".scratch" / f"review-gaps-{stamp}.md")
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(state, "workflow-telemetry", f"review-gaps-{stamp}.md")


def _collect_pr_records(args, events):
    records = []
    if args.no_gh:
        by_run, _ = _index_events(events)
        target_repos = {r.lower() for r in (args.repo or [])}
        for rid, evs in sorted(by_run.items()):
            bot_evs = [e for e in evs if e.get("event") == "review.finding" and e.get("source") == "bot"]
            if not bot_evs:
                continue
            repo = evs[0].get("repo") or ""
            if target_repos and repo.lower() not in target_repos:
                continue
            pr_nums = [int(e["pr_number"]) for e in evs if e.get("event") == "pr.open" and e.get("pr_number") is not None]
            pr_num = pr_nums[-1] if pr_nums else 0
            if args.pr and pr_num not in args.pr:
                continue
            records.append({
                "repo": repo,
                "number": pr_num,
                "branch": evs[0].get("branch") or "",
                "run_id": rid,
                "bot_findings": [{
                    "comment_id": e.get("comment_id"),
                    "path": norm_path(e.get("path")),
                    "line": e.get("line"),
                    "sha": e.get("sha") or "",
                    "severity": e.get("severity") or "Medium",
                    "verdict": e.get("verdict") or "deferred",
                    "validity": e.get("validity") or "valid",
                    "reason": e.get("reason") or "",
                    "claim": e.get("claim") or "",
                } for e in bot_evs],
            })
        return records

    repos = args.repo or [wf_backfill.resolve_repo_slug()]
    for repo in repos:
        pr_nums = list(args.pr or [])
        if args.since:
            pr_nums = sorted(set(pr_nums) | set(wf_backfill.list_merged_prs_since(repo, args.since)))
        for num in pr_nums:
            meta = _fetch_pr_meta(num, repo)
            if meta.get("state") not in ("CLOSED", "MERGED"):
                continue
            pr_data = wf_backfill.fetch_pr_bot_data(num, repo, with_commit_files=True)
            records.append({
                "repo": repo,
                "number": num,
                "branch": pr_data["branch"],
                "title": meta.get("title", ""),
                "url": meta.get("url", ""),
                "pr_data": pr_data,
                "bot_findings": None,
            })
    return records


def main(argv=None):
    ap = argparse.ArgumentParser(description="Analyze review gaps between local review telemetry and Copilot PR comments.")
    ap.add_argument("--pr", type=int, action="append", help="Closed/merged PR number (repeatable)")
    ap.add_argument("--since", help="Analyze merged PRs on or after YYYY-MM-DD")
    ap.add_argument("--repo", action="append", help="GitHub owner/repo (repeatable; defaults to current repo)")
    ap.add_argument("--dir", default=".", help="Local repo directory for git diff and project-config overlay lookup")
    ap.add_argument("--out", help="Output path for the uncommitted markdown report")
    ap.add_argument("--json", action="store_true", help="Print JSON output to stdout instead of writing markdown")
    ap.add_argument("--no-gh", action="store_true", help="Offline mode: read bot findings from telemetry log only")
    ap.add_argument("--log", help="Override telemetry events.jsonl path")
    args = ap.parse_args(argv)

    if not args.no_gh and not args.pr and not args.since:
        ap.error("pass --pr, --since, or --no-gh")

    log_path = (
        args.log
        or os.environ.get("WF_TELEMETRY_LOG")
        or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                        "workflow-telemetry", "events.jsonl")
    )
    events = wf_backfill.load_log(log_path)
    project_cfg = load_project_config(args.dir)
    records = _collect_pr_records(args, events)
    analysis = analyze_prs(records, events, project_cfg, repo_dir=args.dir if os.path.isdir(args.dir) else None)
    proposals = build_proposals(analysis)

    if args.json:
        print(json.dumps({"analysis": analysis, "proposals": proposals}, indent=2))
        return 0

    out_path = args.out or _default_out_path(args.dir)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    md = render_markdown(analysis, proposals)
    Path(out_path).write_text(md)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
