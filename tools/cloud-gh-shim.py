#!/usr/bin/env python3
"""gh shim for Claude Code cloud sessions.

Those sessions block GitHub GraphQL, which `gh issue view`, `gh pr view`,
`gh pr list`, `gh pr create` and `gh repo view` all use. The workflow scripts
call exactly those, so this wrapper answers them over REST (`gh api`) and hands
everything else to the real gh. Installed as `gh` in a directory that precedes
the real one on PATH by cloud-workflow-bootstrap.sh (WORKFLOW_INSTALL=claude).

Covered, with the flags the workflow uses:
  auth status
  repo view [--json owner,name,defaultBranchRef] [-q|--jq EXPR]
  issue view N [--json number,title,body,state,url,assignees,parent,
                subIssuesSummary,subIssues]
  issue edit N --add-assignee @me|LOGIN     issue comment N --body|--body-file
  issue close N [--comment TEXT]
  pr list [--head B] [--state open|closed|merged|all] --json F
  pr view [N] --json number,url,title,id,headRefName,headRefOid,baseRefName,commits
  pr create --title T --head B [--base B] [--body T|--body-file F] [--draft]
  pr comment [N] --body T|--body-file F
  pr edit N [--title T] [--body T|--body-file F]
Anything else, including `gh api`, runs the real gh unchanged. Set GH_SHIM_REAL
to the real binary; otherwise the first other `gh` on PATH is used.
"""
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import sys


def find_real():
    real = os.environ.get("GH_SHIM_REAL")
    if real:
        return real
    me = os.path.realpath(__file__)
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not os.path.isabs(d):  # "" and "." would resolve against the cwd
            continue
        cand = os.path.join(d, "gh")
        if os.path.isfile(cand) and os.access(cand, os.X_OK) and os.path.realpath(cand) != me:
            return cand
    sys.exit("gh shim: no real gh found on PATH")


REAL = find_real()


def passthrough(argv):
    os.execv(REAL, [REAL] + argv)


class ApiError(Exception):
    pass


def api(path, method="GET", fields=None, paginate=False, quiet=False):
    cmd = [REAL, "api", "-X", method, path]
    if paginate:
        cmd.append("--paginate")
    for k, v in (fields or {}).items():
        cmd += ["-f" if isinstance(v, str) else "-F", f"{k}={v if isinstance(v, str) else json.dumps(v).strip(chr(34))}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        if quiet:
            raise ApiError(r.stderr or r.stdout)
        sys.stderr.write(r.stderr or r.stdout)
        sys.exit(r.returncode)
    if paginate:
        # --paginate prints one JSON document per page; merge arrays.
        out, dec, text, i = [], json.JSONDecoder(), r.stdout, 0
        while i < len(text):
            while i < len(text) and text[i].isspace():
                i += 1
            if i >= len(text):
                break
            obj, i = dec.raw_decode(text, i)
            out.extend(obj) if isinstance(obj, list) else out.append(obj)
        return out
    return json.loads(r.stdout) if r.stdout.strip() else {}


def try_api(path, paginate=False):
    """The resource, or None when it does not exist (404); any other failure is fatal."""
    try:
        return api(path, paginate=paginate, quiet=True)
    except ApiError as e:
        if "404" in str(e):
            return None
        sys.exit(f"gh shim: {path}: {e}")


def split_repo(args):
    """Return (owner/repo, args without -R/--repo)."""
    rest, slug, i = [], "", 0
    while i < len(args):
        if args[i] in ("-R", "--repo") and i + 1 < len(args):
            slug = re.sub(r"^(https?://)?github\.com/", "", args[i + 1])
            i += 2
        else:
            rest.append(args[i])
            i += 1
    slug = slug or default_slug()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", slug):
        sys.exit(f"gh shim: invalid repository '{slug}'")
    return slug, rest


def num0(pos):
    return number(pos[0] if pos else "")


def number(value):
    if not re.fullmatch(r"\d+", value or ""):
        sys.exit(f"gh shim: expected a number, got '{value}'")
    return value


def default_slug():
    if os.environ.get("GH_REPO"):
        return os.environ["GH_REPO"]
    r = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True)
    m = re.search(r"([^/:]+)/([^/]+?)(?:\.git)?/?$", r.stdout.strip())
    if r.returncode != 0 or not m:
        sys.exit("gh shim: cannot work out owner/repo from origin; pass -R owner/repo")
    return f"{m.group(1)}/{m.group(2)}"


def opts(args, valued, flags=()):
    """Split args into (positionals, {opt: value}, {flag}); unknown options are an error."""
    pos, vals, seen, i = [], {}, set(), 0
    while i < len(args):
        a = args[i]
        if a in valued:
            if i + 1 >= len(args):
                sys.exit(f"gh shim: {a} needs a value")
            vals[a] = args[i + 1]
            i += 2
        elif a in flags:
            seen.add(a)
            i += 1
        elif a.startswith("-"):
            sys.exit(f"gh shim: unsupported option {a} (the shim only covers the workflow's flags)")
        else:
            pos.append(a)
            i += 1
    return pos, vals, seen


def emit(obj, vals):
    fields = vals.get("--json")
    if fields:
        want = [f for f in fields.split(",") if f]
        sample = obj if isinstance(obj, dict) else (obj[0] if obj else None)
        unknown = [f for f in want if sample is not None and f not in sample]
        if unknown:
            sys.exit("gh shim: unsupported --json field(s): " + ", ".join(unknown))
        obj = {k: obj.get(k) for k in want if k in obj} if isinstance(obj, dict) else [
            {k: o.get(k) for k in want if k in o} for o in obj]
    expr = vals.get("--jq") or vals.get("-q")
    text = json.dumps(obj)
    if expr:
        if not shutil.which("jq"):
            sys.exit("gh shim: jq is required for --jq and was not found on PATH")
        r = subprocess.run(["jq", "-r", expr], input=text, capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        sys.exit(r.returncode)
    print(text)


def body_arg(vals):
    if "--body-file" in vals:
        path = vals["--body-file"]
        return sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    return vals.get("--body")


def whoami():
    return api("user")["login"]


def issue_json(slug, n):
    d = api(f"repos/{slug}/issues/{n}")
    if "pull_request" in d:
        sys.exit(f"gh shim: #{n} is a pull request, not an issue")
    out = {
        "number": d["number"], "title": d["title"], "body": d.get("body") or "",
        "state": d["state"].upper(), "url": d["html_url"],
        "assignees": [{"login": a["login"]} for a in d.get("assignees", [])],
        "subIssuesSummary": {"total": (d.get("sub_issues_summary") or {}).get("total", 0),
                             "completed": (d.get("sub_issues_summary") or {}).get("completed", 0)},
    }
    parent = try_api(f"repos/{slug}/issues/{n}/parent")
    out["parent"] = {"number": parent["number"], "title": parent["title"]} if parent and "number" in parent else None
    subs = try_api(f"repos/{slug}/issues/{n}/sub_issues?per_page=100", paginate=True) or []
    out["subIssues"] = {"nodes": [{"number": s["number"], "title": s["title"], "state": s["state"].upper()}
                                  for s in subs]}
    return out


def pr_json(slug, d, full=False):
    merged = bool(d.get("merged_at"))
    out = {
        "number": d["number"], "url": d["html_url"], "title": d["title"], "id": d["node_id"],
        "state": "MERGED" if merged else d["state"].upper(),
        "mergedAt": d.get("merged_at"),
        "mergeCommit": {"oid": d["merge_commit_sha"]} if merged and d.get("merge_commit_sha") else None,
        "headRefName": d["head"]["ref"], "headRefOid": d["head"]["sha"], "baseRefName": d["base"]["ref"],
        "isDraft": d.get("draft", False), "body": d.get("body") or "",
    }
    return out


def cmd_repo(args):
    if args[:1] != ["view"]:
        passthrough(["repo"] + args)
    slug, rest = split_repo(args[1:])
    pos, vals, _ = opts(rest, {"--json", "--jq", "-q"})
    slug = pos[0] if pos else slug
    d = api(f"repos/{slug}")
    emit({"owner": {"login": d["owner"]["login"]}, "name": d["name"], "url": d["html_url"],
          "defaultBranchRef": {"name": d["default_branch"]}}, vals)


def cmd_issue(args):
    sub = args[:1]
    slug, rest = split_repo(args[1:])
    if sub == ["view"]:
        pos, vals, _ = opts(rest, {"--json", "--jq", "-q"})
        emit(issue_json(slug, num0(pos)), vals)
    elif sub == ["edit"]:
        pos, vals, _ = opts(rest, {"--add-assignee"})
        if set(vals) != {"--add-assignee"}:
            sys.exit("gh shim: issue edit only supports --add-assignee")
        who = whoami() if vals["--add-assignee"] == "@me" else vals["--add-assignee"]
        api(f"repos/{slug}/issues/{num0(pos)}/assignees", "POST", {"assignees[]": who})
    elif sub == ["comment"]:
        pos, vals, _ = opts(rest, {"--body", "--body-file"})
        api(f"repos/{slug}/issues/{num0(pos)}/comments", "POST", {"body": body_arg(vals) or ""})
    elif sub == ["close"]:
        pos, vals, _ = opts(rest, {"--comment", "-c", "--reason", "-r"})
        text = vals.get("--comment") or vals.get("-c")
        if text:
            api(f"repos/{slug}/issues/{num0(pos)}/comments", "POST", {"body": text})
        reason = (vals.get("--reason") or vals.get("-r") or "completed").replace(" ", "_")
        api(f"repos/{slug}/issues/{num0(pos)}", "PATCH", {"state": "closed", "state_reason": reason})
    else:
        passthrough(["issue"] + args)


def find_prs(slug, head, state):
    q = "all" if state in ("all", "merged") else state
    owner = slug.split("/")[0]
    prs = api(f"repos/{slug}/pulls?head={urllib.parse.quote(owner + ':' + head, safe='')}&state={q}&per_page=100",
              paginate=True)
    out = [pr_json(slug, p) for p in prs]
    if state == "merged":
        return [p for p in out if p["state"] == "MERGED"]
    if state == "closed":  # REST "closed" includes merged; gh's does not
        return [p for p in out if p["state"] == "CLOSED"]
    return out


def current_branch():
    r = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True)
    return r.stdout.strip()


def cmd_pr(args):
    sub = args[:1]
    slug, rest = split_repo(args[1:])
    if sub == ["list"]:
        _, vals, _ = opts(rest, {"--head", "-H", "--state", "-s", "--json", "--jq", "-q", "--limit", "-L"})
        head = vals.get("--head") or vals.get("-H")
        state = vals.get("--state") or vals.get("-s") or "open"
        if not head:
            sys.exit("gh shim: pr list needs --head")
        emit(find_prs(slug, head, state), vals)
    elif sub == ["view"]:
        pos, vals, _ = opts(rest, {"--json", "--jq", "-q"})
        if pos and pos[0].isdigit():
            d = api(f"repos/{slug}/pulls/{pos[0]}")
        else:
            branch = pos[0] if pos else current_branch()
            if not branch:
                sys.exit("gh shim: no branch checked out; pass a PR number")
            found = find_prs(slug, branch, "open") or find_prs(slug, branch, "all")
            if not found:
                sys.exit(f'no pull requests found for branch "{branch}"')
            d = api(f"repos/{slug}/pulls/{found[0]['number']}")
        out = pr_json(slug, d)
        if "commits" in (vals.get("--json") or ""):
            cs = api(f"repos/{slug}/pulls/{d['number']}/commits", paginate=True)
            out["commits"] = [{"oid": c["sha"], "committedDate": c["commit"]["committer"]["date"]} for c in cs]
        emit(out, vals)
    elif sub == ["create"]:
        pos, vals, flags = opts(rest, {"--title", "-t", "--body", "-b", "--body-file", "-F", "--head", "-H", "--base", "-B"},
                                {"--draft", "-d"})
        head = vals.get("--head") or vals.get("-H") or current_branch()
        base = vals.get("--base") or vals.get("-B") or api(f"repos/{slug}")["default_branch"]
        fields = {"title": vals.get("--title") or vals.get("-t") or "", "head": head, "base": base,
                  "body": body_arg(vals) or vals.get("-b") or ""}
        if flags & {"--draft", "-d"}:
            fields["draft"] = True
        d = api(f"repos/{slug}/pulls", "POST", fields)
        print(d["html_url"])
    elif sub == ["edit"]:
        pos, vals, _ = opts(rest, {"--title", "-t", "--body", "-b", "--body-file", "-F"})
        fields = {}
        if "--title" in vals or "-t" in vals:
            fields["title"] = vals.get("--title") or vals.get("-t")
        body = body_arg(vals) if ("--body" in vals or "--body-file" in vals) else vals.get("-b")
        if body is not None:
            fields["body"] = body
        api(f"repos/{slug}/pulls/{num0(pos)}", "PATCH", fields)
    elif sub == ["comment"]:
        pos, vals, _ = opts(rest, {"--body", "-b", "--body-file", "-F"})
        body = body_arg(vals) if ("--body" in vals or "--body-file" in vals) else vals.get("-b")
        if pos:
            n = number(pos[0])
        else:
            branch = current_branch()
            found = find_prs(slug, branch, "open") if branch else []
            if not found:
                sys.exit("gh shim: no open PR for the current branch; pass a PR number")
            n = found[0]["number"]
        api(f"repos/{slug}/issues/{n}/comments", "POST", {"body": body or ""})
    else:
        passthrough(["pr"] + args)


def main():
    argv = sys.argv[1:]
    cmd, args = (argv[0] if argv else ""), argv[1:]
    if cmd == "auth" and args[:1] == ["status"]:
        r = subprocess.run([REAL, "api", "user"], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"github.com\n  Logged in as {json.loads(r.stdout)['login']} (REST via cloud gh shim)")
            sys.exit(0)
        sys.stderr.write(r.stderr)
        sys.exit(1)
    handler = {"repo": cmd_repo, "issue": cmd_issue, "pr": cmd_pr}.get(cmd)
    if handler:
        handler(args)
    else:
        passthrough(argv)


if __name__ == "__main__":
    main()
