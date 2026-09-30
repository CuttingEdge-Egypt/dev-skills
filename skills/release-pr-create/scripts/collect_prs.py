#!/usr/bin/env python3
"""Collect the PRs a release PR (<source> -> <target>) would ship, with titles, descriptions and
their deployment-related sections, as JSON.

Usage:
    python scripts/collect_prs.py --target <branch> --source <branch>
        [--remote origin] [--platform auto|github|azure|none] [--since <commit-ish>]
        [--out <file.json>]

How the range is found (the "boundary" -- the commit after which PRs count as unreleased):
  1. --since <commit-ish> if given (a tag, a SHA, the last release commit, ...).
  2. Otherwise, the head commit of the last *completed* PR from <source> into <target> on the
     platform (GitHub via `gh`, Azure DevOps via `az repos`), if it is an ancestor of <source>.
     This is exact regardless of whether release PRs are merge-committed or squash-merged.
  3. Otherwise, plain `<target>..<source>` (commits on source not yet in target). Correct when
     release PRs are merge-committed; wildly over-inclusive if they are squash-merged -- the
     script warns when the range looks like that.

PRs are found from commit messages in the range:
    GitHub merge   "Merge pull request #123 from org/branch"
    GitHub squash  "Some title (#123)"
    Azure DevOps   "Merged PR 123: Some title"
    GitLab         "See merge request group/proj!123"
and, on GitHub, by asking the API which PR a commit without a number belongs to (rebase merges).

Each PR is classified:
    change   -- a normal PR (feature, fix, chore... -- its head is a short-lived branch)
    release  -- its head is itself a long-lived branch (dev/develop/staging/main/master/release/*),
                i.e. an earlier release PR inside the range (e.g. dev->staging inside staging->main)
Commits in the range that belong to no PR are reported as direct_commits.

Output (stdout or --out): JSON with platform, source, target, boundary, range, prs[], release_prs[],
direct_commits[], warnings[]. Each PR carries: number, title, body, url, author, merged_at,
base, head, labels, sections{heading: text}, deployment{heading: text} (deployment-ish sections only),
deployment_stated (bool), deployment_is_none (bool), deploy_hints[] (lines outside those sections
that mention env vars / secrets / migrations / infra / manual steps), fetched (bool).

Exit codes: 0 ok, 2 could not run (bad refs, not a git repo). Requires git and Python 3.9+;
`gh` (authenticated) for GitHub details, `az` with the azure-devops extension for Azure DevOps.
Without either, PR numbers and commit subjects are still returned (fetched=false) so details can
be filled in from another source.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse

LONG_LIVED = re.compile(
    r"^(refs/heads/)?(dev|develop|development|staging|stage|stg|uat|qa|preprod|pre-prod|main|master|"
    r"prod|production|release([/-].*)?|hotfix-release)$",
    re.IGNORECASE,
)

PR_PATTERNS = [
    ("github-merge", re.compile(r"^Merge pull request #(\d+) from (\S+)")),
    ("azure", re.compile(r"^Merged PR (\d+):\s*(.*)")),
    ("github-squash", re.compile(r"\(#(\d+)\)\s*$")),
    ("gitlab", re.compile(r"See merge request \S*!(\d+)")),
]

DEPLOY_HEADING = re.compile(
    r"(?i)(deploy|release note|rollout|roll-out|migration|config|environment|env var|secret|infra|"
    r"manual|pre-release|post-release|operations|ops note|breaking|upgrade|rollback|permission)"
)
NONE_TEXT = re.compile(r"(?is)^\W*(none|n/?a|nothing|no\b.*(change|action|step|note)s?.*|-)\W*$")
HINT_RE = re.compile(
    r"(?i)(\benv(ironment)?\s*var|\bsecret\b|key vault|keyvault|\bmigration|\bmigrate\b|feature flag|"
    r"\bterraform\b|\bhelm\b|\bk8s\b|kubernetes|\bconfigmap\b|app ?settings|\.env\b|\bcron\b|"
    r"\bqueue\b|\bbucket\b|\bmanual(ly)?\b|\brun (the )?script\b|\bbackfill\b|\bseed\b|\bpermission|"
    r"\biam\b|\brole\b|\bbreaking\b|\bdowntime\b|`[A-Z][A-Z0-9_]{3,}`|build agent|\brequires?\b.{0,40}"
    r"\b(node|python|java|jdk|\.net|dotnet|runtime|version|agent|restart)\b|\brestart\b|\bcache (flush|clear))"
)


# ---------------------------------------------------------------------------------------------


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    exe = shutil.which(cmd[0]) or cmd[0]  # resolves gh.exe / az.cmd on Windows
    if cmd[0] == "git":  # deep checkouts on Windows otherwise fail with "Filename too long"
        cmd = ["git", "-c", "core.longpaths=true", *cmd[1:]]
    try:
        proc = subprocess.run([exe, *cmd[1:]], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", f"{cmd[0]}: not found")
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {proc.stderr.strip()}")
    return proc


def git(*args: str) -> str:
    return run(["git", *args], check=True).stdout


def resolve_ref(remote: str, branch: str) -> str:
    for cand in (f"{remote}/{branch}", branch):
        if run(["git", "rev-parse", "--verify", "--quiet", cand + "^{commit}"]).returncode == 0:
            return cand
    raise RuntimeError(f"branch '{branch}' not found locally or as {remote}/{branch} (did you git fetch?)")


def is_ancestor(a: str, b: str) -> bool:
    return run(["git", "merge-base", "--is-ancestor", a, b]).returncode == 0


def detect_platform(remote: str) -> tuple[str, dict]:
    url = run(["git", "remote", "get-url", remote]).stdout.strip()
    info = {"remote_url": url}
    if not url:
        return "none", info
    low = url.lower()
    if "dev.azure.com" in low or "visualstudio.com" in low:
        # https://dev.azure.com/{org}/{project}/_git/{repo}  |  git@ssh.dev.azure.com:v3/{org}/{project}/{repo}
        m = re.search(r"dev\.azure\.com[:/](?:v3/)?([^/]+)/([^/]+)/(?:_git/)?([^/]+?)(?:\.git)?$", url)
        if not m:
            m = re.search(r"//([^.]+)\.visualstudio\.com/(?:DefaultCollection/)?([^/]+)/_git/([^/]+?)(?:\.git)?$", url)
            if m:
                info.update(org_url=f"https://dev.azure.com/{m.group(1)}", project=m.group(2), repo=m.group(3))
        else:
            org = m.group(1).split("@")[-1]
            info.update(org_url=f"https://dev.azure.com/{org}", project=m.group(2), repo=m.group(3))
        return "azure", info
    if "github" in low:
        path = urlparse(url).path if "://" in url else url.split(":", 1)[-1]
        info["repo"] = path.strip("/").removesuffix(".git")
        return "github", info
    return "none", info


# ---------------------------------------------------------------------------------------------
# platform adapters


def gh_json(args: list[str]):
    proc = run(["gh", *args])
    if proc.returncode != 0:
        return None, proc.stderr.strip()
    try:
        return json.loads(proc.stdout or "null"), ""
    except json.JSONDecodeError as exc:
        return None, f"bad JSON from gh: {exc}"


def az_json(args: list[str], info: dict):
    extra = []
    if info.get("org_url"):
        extra += ["--org", info["org_url"]]
    proc = run(["az", *args, *extra, "--output", "json"])
    if proc.returncode != 0:
        return None, proc.stderr.strip()
    try:
        return json.loads(proc.stdout or "null"), ""
    except json.JSONDecodeError as exc:
        return None, f"bad JSON from az: {exc}"


def strip_ref(name: str) -> str:
    return re.sub(r"^refs/heads/", "", name or "")


def fetch_pr(platform: str, info: dict, number: int) -> tuple[dict | None, str]:
    if platform == "github":
        fields = "number,title,body,url,author,mergedAt,baseRefName,headRefName,labels,state"
        args = ["pr", "view", str(number), "--json", fields]
        if info.get("repo"):
            args += ["--repo", info["repo"]]
        data, err = gh_json(args)
        if not data:
            return None, err
        return {
            "number": data.get("number", number), "title": data.get("title", ""), "body": data.get("body") or "",
            "url": data.get("url", ""), "author": (data.get("author") or {}).get("login", ""),
            "merged_at": data.get("mergedAt") or "", "base": data.get("baseRefName", ""),
            "head": data.get("headRefName", ""), "labels": [l.get("name", "") for l in data.get("labels") or []],
            "state": data.get("state", ""),
        }, ""
    if platform == "azure":
        data, err = az_json(["repos", "pr", "show", "--id", str(number)], info)
        if not data:
            return None, err
        repo = data.get("repository") or {}
        web = (repo.get("webUrl") or "").rstrip("/")
        return {
            "number": data.get("pullRequestId", number), "title": data.get("title", ""),
            "body": data.get("description") or "",
            "url": f"{web}/pullrequest/{number}" if web else "",
            "author": (data.get("createdBy") or {}).get("displayName", ""),
            "merged_at": data.get("closedDate") or "", "base": strip_ref(data.get("targetRefName", "")),
            "head": strip_ref(data.get("sourceRefName", "")),
            "labels": [l.get("name", "") for l in data.get("labels") or []], "state": data.get("status", ""),
        }, ""
    return None, "no platform CLI"


def last_release_head(platform: str, info: dict, source: str, target: str) -> tuple[str | None, str]:
    """Head commit of the most recent completed source->target PR."""
    if platform == "github":
        args = ["pr", "list", "--base", target, "--head", source, "--state", "merged", "--limit", "1",
                "--json", "number,headRefOid,mergedAt"]
        if info.get("repo"):
            args += ["--repo", info["repo"]]
        data, err = gh_json(args)
        if data:
            return data[0].get("headRefOid"), f"GitHub PR #{data[0].get('number')} merged {data[0].get('mergedAt')}"
        return None, err or "no merged PR found"
    if platform == "azure":
        args = ["repos", "pr", "list", "--source-branch", source, "--target-branch", target,
                "--status", "completed", "--top", "1"]
        if info.get("project"):
            args += ["--project", info["project"]]
        if info.get("repo"):
            args += ["--repository", info["repo"]]
        data, err = az_json(args, info)
        if data:
            pr = data[0]
            sha = (pr.get("lastMergeSourceCommit") or {}).get("commitId")
            return sha, f"Azure DevOps PR {pr.get('pullRequestId')} completed {pr.get('closedDate')}"
        return None, err or "no completed PR found"
    return None, "no platform CLI"


def squash_release_boundary(target_ref: str, source_ref: str) -> tuple[str | None, str]:
    """Offline detection of a squash-merged release: a commit on target (not on source) whose tree is
    identical to some commit on source is that release's squash -- the matching source commit is the
    boundary. Only the newest target-only commits are checked. Returns (sha, description)."""
    target_only = git("log", "--format=%H %T %s", "-n", "50", f"{source_ref}..{target_ref}").splitlines()
    if not target_only:
        return None, ""
    source_trees: dict[str, str] = {}
    for line in git("log", "--format=%T %H", "-n", "5000", source_ref).splitlines():
        tree, sha = line.split(" ", 1)
        source_trees.setdefault(tree, sha)  # newest commit with that tree
    for line in target_only:
        sha, tree, subj = line.split(" ", 2)
        if tree in source_trees and len(git("rev-list", "--parents", "-n", "1", sha).split()) == 2:
            src = source_trees[tree]
            return src, f"squash-merged release {sha[:12]} ('{subj}') has the same tree as {src[:12]} on the source"
    return None, ""


def gh_prs_for_commit(info: dict, sha: str) -> list[int]:
    if not info.get("repo"):
        return []
    data, _ = gh_json(["api", f"repos/{info['repo']}/commits/{sha}/pulls"])
    return [p["number"] for p in (data or []) if p.get("merged_at")]


# ---------------------------------------------------------------------------------------------
# description parsing


HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$|^\s*\*\*([^*]{2,80})\*\*:?\s*$|^\s*__([^_]{2,80})__:?\s*$")


def split_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = "_preamble"
    sections[current] = []
    in_fence = False
    for line in body.replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else HEADING_RE.match(line)
        if m:
            current = (m.group(2) or m.group(3) or m.group(4)).strip().rstrip(":")
            base, n = current, 2
            while current in sections:
                current = f"{base} ({n})"
                n += 1
            sections[current] = []
            continue
        sections[current].append(line)
    out = {k: strip_comments("\n".join(v)).strip() for k, v in sections.items()}
    return {k: v for k, v in out.items() if v or k != "_preamble"}


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def analyse_body(body: str) -> dict:
    sections = split_sections(body or "")
    deployment = {k: v for k, v in sections.items() if k != "_preamble" and DEPLOY_HEADING.search(k)}
    stated = bool(deployment)
    is_none = stated and all(NONE_TEXT.match(v or "none") for v in deployment.values())
    hints = []
    for name, text in sections.items():
        if name in deployment:
            continue
        for line in text.split("\n"):
            s = line.strip()
            if s and HINT_RE.search(s) and not s.startswith(("- [ ]", "- [x]", "* [ ]", "* [x]")):
                hints.append({"section": name, "line": s[:300]})
    return {"sections": sections, "deployment": deployment, "deployment_stated": stated,
            "deployment_is_none": is_none, "deploy_hints": hints[:20]}


# ---------------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--target", required=True, help="release branch the PR goes into (staging/main/master/...)")
    ap.add_argument("--source", required=True, help="branch being released (dev/develop/staging/...)")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--platform", default="auto", choices=["auto", "github", "azure", "none"])
    ap.add_argument("--since", help="explicit boundary commit-ish; overrides platform/merge-base detection")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    warnings: list[str] = []
    try:
        os.chdir(git("rev-parse", "--show-toplevel").strip())
        target_ref = resolve_ref(args.remote, args.target)
        source_ref = resolve_ref(args.remote, args.source)
    except RuntimeError as exc:
        print(f"collect_prs: {exc}", file=sys.stderr)
        return 2

    platform, info = detect_platform(args.remote)
    if args.platform != "auto":
        platform = args.platform
    cli = {"github": "gh", "azure": "az"}.get(platform)
    if cli and not shutil.which(cli):
        warnings.append(f"{cli} CLI not found -- PR titles/descriptions not fetched; fill them in from "
                        f"another source (a {platform} connector, the web UI, or the user)")
        platform_usable = False
    else:
        platform_usable = bool(cli)
    if not cli:
        warnings.append("no PR platform detected (remote is not GitHub or Azure DevOps, or --platform none) -- "
                        "only commit subjects are available; get PR descriptions from another source")

    # ---- boundary
    boundary, boundary_method = None, ""
    if args.since:
        boundary = git("rev-parse", args.since + "^{commit}").strip()
        boundary_method = f"--since {args.since}"
    elif platform_usable:
        sha, how = last_release_head(platform, info, args.source, args.target)
        if sha and run(["git", "cat-file", "-e", sha + "^{commit}"]).returncode == 0 and is_ancestor(sha, source_ref):
            boundary, boundary_method = sha, f"head of last completed {args.source}->{args.target} PR ({how})"
        elif sha:
            warnings.append(f"last {args.source}->{args.target} PR head {sha[:12]} is not in local history "
                            f"of {source_ref}; fell back to {args.target}..{args.source} (fetch, or pass --since)")
        else:
            warnings.append(f"could not find a previous {args.source}->{args.target} PR ({how}); "
                            f"using {args.target}..{args.source}")
    if not boundary:
        sha, how = squash_release_boundary(target_ref, source_ref)
        if sha:
            boundary, boundary_method = sha, how
    if boundary:
        rng = f"{boundary}..{source_ref}"
    else:
        rng = f"{target_ref}..{source_ref}"
        boundary_method = boundary_method or f"commits on {source_ref} not in {target_ref}"
        boundary = git("merge-base", target_ref, source_ref).strip()

    raw = git("log", "--format=%H%x1f%P%x1f%an%x1f%aI%x1f%s%x1f%b%x1e", rng)
    commits = []
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split("\x1f")
        if len(parts) < 6:
            continue
        sha, parents, author, date, subj, body = parts[:6]
        commits.append({"sha": sha, "parents": parents.split(), "author": author, "date": date,
                        "subject": subj, "body": body})

    if not commits:
        warnings.append(f"no commits in {rng} -- {args.target} already contains everything on {args.source}")
    if not args.since and not boundary_method.startswith("head of") and len(commits) > 400:
        warnings.append(f"{len(commits)} commits in range -- if release PRs are squash-merged into "
                        f"{args.target}, this range is wrong; pass --since <last release commit or tag>")

    # ---- PR numbers from messages; track which commits they cover
    pr_order: list[int] = []
    pr_commit: dict[int, dict] = {}
    covered: set[str] = set()
    for c in commits:
        text = c["subject"] + "\n" + c["body"]
        for kind, pat in PR_PATTERNS:
            m = pat.search(c["subject"]) if kind != "gitlab" else pat.search(text)
            if m:
                n = int(m.group(1))
                if n not in pr_commit:
                    pr_order.append(n)
                    pr_commit[n] = {**c, "match": kind}
                covered.add(c["sha"])
                if len(c["parents"]) > 1:  # merge commit: its second-parent-only commits belong to the PR
                    side = git("rev-list", f"{c['parents'][0]}..{c['sha']}").split()
                    covered.update(side)
                break

    uncovered = [c for c in commits if c["sha"] not in covered and len(c["parents"]) == 1]
    if platform_usable and platform == "github" and uncovered:
        for c in uncovered[:60]:
            for n in gh_prs_for_commit(info, c["sha"]):
                if n not in pr_commit:
                    pr_order.append(n)
                    pr_commit[n] = {**c, "match": "github-api"}
                covered.add(c["sha"])
        if len(uncovered) > 60:
            warnings.append(f"{len(uncovered)} commits without a PR number; only the first 60 were looked up")
        uncovered = [c for c in uncovered if c["sha"] not in covered]
    # merge commits of the form "Merge branch 'dev' into feature" etc. are noise, drop them
    direct = [c for c in uncovered if not re.match(r"^Merge (branch|remote-tracking branch)", c["subject"])]

    # ---- fetch + analyse
    prs, release_prs, fetch_errors = [], [], []
    for n in pr_order:
        c = pr_commit[n]
        entry = {"number": n, "commit": c["sha"][:12], "commit_subject": c["subject"], "match": c["match"],
                 "fetched": False}
        if platform_usable:
            data, err = fetch_pr(platform, info, n)
            if data:
                entry.update(data)
                entry["fetched"] = True
            else:
                fetch_errors.append(f"#{n}: {err[:200]}")
        if not entry["fetched"]:
            title = c["subject"]
            m = re.match(r"^Merged PR \d+:\s*(.*)", title) or re.match(r"^(.*?)\s*\(#\d+\)\s*$", title)
            if m:
                title = m.group(1)
            elif c["match"] == "github-merge":
                title = (c["body"].strip().split("\n")[0] or title)
                m2 = PR_PATTERNS[0][1].match(c["subject"])
                entry["head"] = m2.group(2).split("/", 1)[-1] if m2 else ""
            entry.setdefault("title", title)
            entry.setdefault("body", c["body"] if c["match"] != "github-merge" else "")
        entry.update(analyse_body(entry.get("body", "")))
        head = entry.get("head", "")
        if head and LONG_LIVED.match(head):
            entry["kind"] = "release"
            release_prs.append(entry)
        else:
            entry["kind"] = "change"
            prs.append(entry)
    if fetch_errors:
        warnings.append(f"could not fetch {len(fetch_errors)} PR(s): " + "; ".join(fetch_errors[:5]))
    if release_prs:
        warnings.append(f"{len(release_prs)} earlier release PR(s) inside the range "
                        f"({', '.join('#' + str(p['number']) for p in release_prs)}); their feature PRs are listed "
                        f"separately if merge commits were kept -- if they were squash-merged, read their "
                        f"descriptions for the PRs they shipped")

    result = {
        "platform": platform, "platform_info": info, "source": args.source, "target": args.target,
        "source_ref": source_ref, "target_ref": target_ref, "boundary": boundary, "boundary_method": boundary_method,
        "range": rng, "commit_count": len(commits), "prs": prs, "release_prs": release_prs,
        "direct_commits": [{"sha": c["sha"][:12], "subject": c["subject"], "author": c["author"], "date": c["date"]}
                           for c in direct],
        "warnings": warnings,
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.out}: {len(prs)} PR(s), {len(release_prs)} release PR(s), "
              f"{len(direct)} direct commit(s), {len(warnings)} warning(s)")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
