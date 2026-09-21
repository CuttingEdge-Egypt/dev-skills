#!/usr/bin/env python3
"""Verify -- and optionally rebase -- the file:line citations in a security report.

A citation that points at the wrong line is worse than no citation. A developer opens the file,
sees unrelated code, and concludes the finding is stale or wrong. The bug is still there, twelve
lines away, and now nobody trusts the report.

Two modes:

  verify   Every citation must name a file that exists and a line within it. Use before publishing.
             python verify_citations.py report.md --repo /path/to/repo

  rebase   The report was written against an older commit and should now describe a newer one.
           Each citation is anchored to its *line content* at the old commit, and that content is
           located in the current file. This handles drift without re-reading every file by hand.
             python verify_citations.py report.md --repo /path/to/repo --from-commit 7d995e5b --write

Citations whose anchor content no longer exists are reported individually -- that usually means the
code was edited or moved, and those need a human to re-resolve them by symbol. That is the signal
you want: it is exactly the set where a finding may have been fixed.

`--prefix` handles reports that cite paths relative to a subdirectory (e.g. "core/views.py" when the
file is really "backend/core/views.py").
"""
import argparse
import collections
import os
import re
import subprocess
import sys

# Matches "path/to/file.py:123", "file.py:10-20", and comma continuations ":45, :67"
CITATION_RE = re.compile(
    r"((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|ts|tsx|js|jsx|go|rb|java|php|rs|json|ya?ml))"
    r"((?::\d+(?:-\d+)?)(?:,\s*:\d+(?:-\d+)?)*)"
)


def git_show(repo, rev, path):
    r = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"],
                       capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace").split("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("--repo", required=True, help="repository root the citations refer to")
    ap.add_argument("--from-commit", help="old commit to rebase citations from")
    ap.add_argument("--prefix", default="", help="path prefix to prepend, e.g. 'backend/'")
    ap.add_argument("--write", action="store_true", help="apply rebased line numbers to the report")
    args = ap.parse_args()

    md = open(args.report, encoding="utf-8").read()
    cur_cache, old_cache = {}, {}
    stats = collections.Counter()

    def current(path):
        if path not in cur_cache:
            full = os.path.join(args.repo, path)
            cur_cache[path] = (open(full, encoding="utf-8", errors="replace").read().split("\n")
                               if os.path.isfile(full) else None)
        return cur_cache[path]

    def old(path):
        if path not in old_cache:
            old_cache[path] = git_show(args.repo, args.from_commit, path)
        return old_cache[path]

    tracked = None

    def find_by_basename(name):
        """Resolve a bare filename when exactly one tracked file has that name.

        Bare citations ("views.py:84") are a report defect, but rejecting them outright makes the
        checker useless on drafts. Resolving the unambiguous ones and only complaining about the
        genuinely ambiguous ones keeps the signal where it belongs.
        """
        nonlocal tracked
        if tracked is None:
            r = subprocess.run(["git", "-C", args.repo, "ls-files"], capture_output=True)
            tracked = r.stdout.decode("utf-8", "replace").split("\n") if r.returncode == 0 else []
        hits = [p for p in tracked if p.endswith("/" + name) or p == name]
        return hits[0] if len(hits) == 1 else None

    def resolve(path):
        """Try the cited path, then the prefix, then a unique basename match."""
        for cand in ([path] if not args.prefix else [path, args.prefix + path]):
            if current(cand) is not None:
                return cand
        if "/" not in path:
            found = find_by_basename(path)
            if found:
                stats["resolved_bare"] += 1
                return found
        return args.prefix + path if args.prefix else path

    unresolved, missing_files, out_of_range, bare = [], [], [], []

    def remap(path, line):
        """Find where the old commit's content for this line lives now."""
        o, n = old(path), current(path)
        if o is None or n is None or line > len(o):
            return None
        anchor = o[line - 1].rstrip()
        if not anchor.strip():
            return None
        hits = [i + 1 for i, l in enumerate(n) if l.rstrip() == anchor]
        if not hits:
            return None
        return min(hits, key=lambda h: abs(h - line))  # nearest wins when content repeats

    def handle(m):
        path = resolve(m.group(1))
        lines = current(path)
        if lines is None:
            # A citation with no directory ("views.py:42") is ambiguous rather than wrong --
            # several files may share the name. The fix is to qualify it, not to move the line.
            if "/" not in m.group(1):
                bare.append(m.group(1))
                stats["bare_filename"] += 1
            else:
                missing_files.append(m.group(1))
                stats["missing_file"] += 1
            return m.group(0)

        def one(sm):
            start, end = int(sm.group(1)), sm.group(2)
            if args.from_commit:
                new_start = remap(path, start)
                if new_start is None:
                    unresolved.append(f"{path}:{start}")
                    stats["unresolved"] += 1
                    return sm.group(0)
                stats["same" if new_start == start else "moved"] += 1
                text = f":{new_start}"
                if end:
                    new_end = remap(path, int(end)) or new_start + (int(end) - start)
                    text += f"-{max(new_end, new_start)}"
                return text
            # verify-only
            if start > len(lines):
                out_of_range.append(f"{path}:{start} (file has {len(lines)} lines)")
                stats["out_of_range"] += 1
            else:
                stats["ok"] += 1
            return sm.group(0)

        return m.group(1) + re.sub(r":(\d+)(?:-(\d+))?", one, m.group(2))

    rewritten = CITATION_RE.sub(handle, md)

    print(f"citations examined: {sum(stats.values())}")
    for k in ("ok", "same", "moved", "resolved_bare", "unresolved", "missing_file",
              "out_of_range", "bare_filename"):
        if stats[k]:
            print(f"  {k:14} {stats[k]}")

    for label, items in (
        ("missing files -- path is wrong, or the file moved", missing_files),
        ("line past end of file", out_of_range),
        ("anchor content gone -- re-resolve by symbol (the code was edited or moved)", unresolved),
        ("bare filenames -- qualify with a repo-relative path so the citation is unambiguous", bare),
    ):
        if items:
            print(f"\n{label}:")
            for it in sorted(set(items)):
                print("  ", it)

    if args.write and args.from_commit:
        open(args.report, "w", encoding="utf-8").write(rewritten)
        print(f"\nrebased {stats['moved']} citations; {stats['same']} were already correct")
        if unresolved:
            print("NOTE: the unresolved citations above were left untouched and need a human.")

    return 1 if (missing_files or out_of_range or unresolved or bare) else 0


if __name__ == "__main__":
    sys.exit(main())
