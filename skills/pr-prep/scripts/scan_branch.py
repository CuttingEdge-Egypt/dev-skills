#!/usr/bin/env python3
"""Scan what the current branch changed (vs. its base) for PR-readiness problems.

Usage:
    python scripts/scan_branch.py [--base <ref>] [--committed-only] [--json] [--max-per-check N]

What it checks (only lines/files this branch added or changed -- never pre-existing code):
  hygiene   : ahead/behind base, merge conflicts with base, uncommitted/untracked files,
              WIP/fixup commits, conflict markers, suspicious files (.env, keys, logs, backups),
              large files, likely secrets in added lines
  leftovers : debug statements, focused/skipped tests, new TODO/FIXME/HACK, commented-out code
  unused    : new functions/classes/constants with no other reference in the repo, newly added
              imports never used in their file, new source files nothing references,
              files whose only change is whitespace

Everything under "unused" and "leftovers" is a CANDIDATE found by regex + `git grep`. It must be
confirmed by reading the code before being reported as a problem (dynamic dispatch, framework
registration, reflection, public API, and CLI output all produce false positives).

By default the diff is merge-base..working-tree plus untracked files, i.e. what the PR would contain
if everything currently on disk were committed. --committed-only restricts it to merge-base..HEAD.

Base resolution when --base is omitted: origin/HEAD, then origin/main, origin/master,
origin/develop, then local main/master/develop. Exit code: 0 = scan ran, 2 = could not run.
Requires only git and Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field

# ---------------------------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------------------------


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def git_out(*args: str) -> str:
    return git(*args).stdout


def ref_exists(ref: str) -> bool:
    return git("rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False).returncode == 0


def resolve_base(explicit: str | None) -> str:
    if explicit:
        if not ref_exists(explicit):
            raise RuntimeError(f"base ref '{explicit}' not found")
        return explicit
    head = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False)
    if head.returncode == 0 and head.stdout.strip():
        ref = head.stdout.strip().replace("refs/remotes/", "", 1)
        if ref_exists(ref):
            return ref
    for cand in ("origin/main", "origin/master", "origin/develop", "main", "master", "develop"):
        if ref_exists(cand):
            return cand
    raise RuntimeError("could not determine base branch; pass --base <ref>")


# ---------------------------------------------------------------------------------------------
# findings
# ---------------------------------------------------------------------------------------------


@dataclass
class Finding:
    check: str
    severity: str  # blocker | warning | info
    detail: str
    file: str = ""
    line: int = 0
    snippet: str = ""


@dataclass
class Report:
    base: str
    merge_base: str
    branch: str
    scope: str
    files_changed: int = 0
    findings: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def add(self, *args, **kwargs):
        f = Finding(*args, **kwargs)
        f.snippet = redact(f.snippet)  # any check can quote a line that holds a secret
        self.findings.append(f)


# ---------------------------------------------------------------------------------------------
# diff parsing
# ---------------------------------------------------------------------------------------------

SKIP_CONTENT_DIRS = (
    "node_modules/", "vendor/", "dist/", "build/", "out/", ".next/", "coverage/", "__pycache__/",
    "bin/", "obj/", ".venv/", "venv/", "target/", "third_party/", "migrations/",
)
SKIP_CONTENT_SUFFIXES = (
    ".min.js", ".min.css", ".map", ".lock", "-lock.json", ".lock.json", ".snap", ".svg",
    ".generated.cs", ".designer.cs", ".pb.go", "_pb2.py",
)
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
             "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock", "packages.lock.json", "uv.lock"}
DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")


def is_generated_or_vendored(path: str) -> bool:
    p = path.replace("\\", "/")
    base = os.path.basename(p)
    if base in LOCKFILES:
        return True
    if any(("/" + d) in ("/" + p) for d in SKIP_CONTENT_DIRS):
        return True
    return p.endswith(SKIP_CONTENT_SUFFIXES)


def parse_added_lines(diff_text: str) -> dict[str, list[tuple[int, str]]]:
    """Return {path: [(new_line_no, text), ...]} for '+' lines of a -U0 unified diff."""
    added: dict[str, list[tuple[int, str]]] = {}
    current = None
    new_line = 0
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target == "/dev/null":
                current = None
            else:
                current = target[2:] if target.startswith("b/") else target
                added.setdefault(current, [])
            continue
        if raw.startswith("--- ") or raw.startswith("diff --git"):
            continue
        m = hunk_re.match(raw)
        if m:
            new_line = int(m.group(1))
            continue
        if current is None:
            continue
        if raw.startswith("+"):
            added[current].append((new_line, raw[1:]))
            new_line += 1
        elif raw.startswith(" "):
            new_line += 1
    return added


def read_text(path: str) -> str | None:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if b"\0" in data[:8000]:
        return None
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------------------------
# language helpers
# ---------------------------------------------------------------------------------------------

EXT_LANG = {
    ".py": "py", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js",
    ".vue": "js", ".svelte": "js", ".cs": "cs", ".java": "java", ".kt": "java", ".go": "go",
    ".rb": "rb", ".php": "php", ".rs": "rs", ".swift": "swift", ".scala": "java", ".dart": "java",
    ".c": "c", ".h": "c", ".cpp": "c", ".hpp": "c", ".cc": "c", ".sh": "sh", ".bash": "sh",
    ".ps1": "ps", ".sql": "sql", ".html": "html", ".cshtml": "html", ".razor": "html",
}


def lang_of(path: str) -> str | None:
    return EXT_LANG.get(os.path.splitext(path)[1].lower())


COMMENT_PREFIX = {
    "py": ("#",), "rb": ("#",), "sh": ("#",), "ps": ("#",),
    "js": ("//",), "cs": ("//",), "java": ("//",), "go": ("//",), "php": ("//", "#"),
    "rs": ("//",), "swift": ("//",), "c": ("//",), "sql": ("--",),
}

DEBUG_PATTERNS = {
    "py": [r"\bprint\s*\(", r"\bbreakpoint\s*\(", r"\bimport\s+i?pdb\b", r"\bi?pdb\.set_trace\s*\(",
           r"\bpprint\s*\(", r"\bic\s*\("],
    "js": [r"\bconsole\.(log|debug|trace|dir|table)\s*\(", r"^\s*debugger\s*;?\s*$", r"\balert\s*\("],
    "cs": [r"\bConsole\.Write(Line)?\s*\(", r"\bDebug\.Write(Line)?\s*\(", r"\bDebugger\.Break\s*\("],
    "java": [r"\bSystem\.(out|err)\.print(ln|f)?\s*\(", r"\bprintStackTrace\s*\(", r"\bprintln\s*\("],
    "go": [r"\bfmt\.Print(ln|f)?\s*\(", r"\bspew\.Dump\s*\("],
    "rb": [r"\bbinding\.(pry|irb)\b", r"\bbyebug\b", r"^\s*pp?\s+\S"],
    "php": [r"\bvar_dump\s*\(", r"\bprint_r\s*\(", r"\bdd\s*\(", r"\bdump\s*\("],
    "rs": [r"\bdbg!\s*\(", r"\bprintln!\s*\("],
    "swift": [r"\bprint\s*\(", r"\bdebugPrint\s*\("],
    "c": [r"\bprintf\s*\(", r"\bstd::cout\b"],
}

FOCUSED_TEST = re.compile(
    r"\b(it|describe|test|context)\.only\s*\(|\b(fit|fdescribe|fcontext)\s*\(|"
    r"\b(it|describe|test)\.skip\s*\(|\bxit\s*\(|\bxdescribe\s*\(|"
    r"@pytest\.mark\.skip\b|@unittest\.skip\b|\[Ignore\]|\[Fact\s*\(\s*Skip\s*=|@Disabled\b|@Ignore\b|"
    r"\bt\.Skip\s*\("
)
TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
CONFLICT_RE = re.compile(r"^(<{7}|={7}|>{7})( |$)")
CODEISH_RE = re.compile(
    r"(;\s*$|[{}]\s*$|^\s*(return|if|for|while|else|elif|def|class|function|const|let|var|import|"
    r"from|public|private|protected|await|async|try|catch|except|throw|raise)\b|"
    r"^\s*[\w.\[\]]+\s*=[^=]|^\s*[\w.]+\(.*\)\s*;?\s*$)"
)

SECRET_PATTERNS = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("API secret key", re.compile(r"\bsk-(live|proj|ant)?[-_A-Za-z0-9]{20,}\b")),
    ("Stripe-style secret key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("connection string with password", re.compile(r"(?i)\b(password|pwd)\s*=\s*[^;\s'\"]{4,}\s*;")),
    ("hard-coded credential", re.compile(
        r"(?i)\b\w*(password|passwd|secret|api[_-]?key|_key|access[_-]?token|auth[_-]?token|client[_-]?secret)"
        r"\w*['\"]?\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
]
def redact(text: str) -> str:
    for _, pat in SECRET_PATTERNS:
        text = pat.sub(lambda m: m.group(0) if PLACEHOLDER_SECRET.search(m.group(0)) else "<redacted>", text)
    return text


PLACEHOLDER_SECRET = re.compile(r"(?i)(example|placeholder|changeme|your[_-]|xxx|dummy|test|fake|<|\$\{|\{\{|%\()")

SUSPICIOUS_FILE_RE = re.compile(
    r"(^|/)(\.env(\.[\w-]+)?|id_rsa|id_ed25519|.*\.pem|.*\.key|.*\.p12|.*\.pfx|.*\.keystore|"
    r"\.DS_Store|Thumbs\.db|.*\.log|.*\.orig|.*\.rej|.*\.bak|.*\.swp|.*\.tmp|.*~|"
    r"npm-debug\.log.*|.*\.sqlite3?|.*\.db|nohup\.out|scratch.*|tmp_.*|debug_.*)$",
    re.IGNORECASE,
)
ENV_TEMPLATE_RE = re.compile(r"\.env\.(example|sample|template|dist|defaults)$", re.IGNORECASE)

# Symbol definitions: (lang, regex, exported_flag_group_or_None)
DEF_PATTERNS = {
    "py": [re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("),
           re.compile(r"^class\s+([A-Za-z_]\w*)\b"),
           re.compile(r"^\s+(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("),
           re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*(?::[^=]+)?=")],
    "js": [re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*)"),
           re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
           re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*"
                      r"(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"),
           re.compile(r"^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)"),
           re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)")],
    "cs": [re.compile(r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|async|"
                      r"sealed|abstract|partial|readonly|unsafe|extern|new)\s+)+[\w<>\[\],.?\s]+?\s+"
                      r"([A-Z]\w*)\s*(?:<[^>]*>)?\s*\("),
           re.compile(r"^\s*(?:(?:public|private|protected|internal|static|sealed|abstract|partial)\s+)*"
                      r"(?:class|record|struct|interface|enum)\s+([A-Za-z_]\w*)")],
    "java": [re.compile(r"^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|"
                        r"override|suspend|internal|open)\s+)+(?:fun\s+)?[\w<>\[\],.?\s]*?\b"
                        r"([a-zA-Z_]\w*)\s*\("),
             re.compile(r"^\s*(?:(?:public|private|protected|static|final|abstract|data|sealed|open)\s+)*"
                        r"(?:class|interface|enum|record|object)\s+([A-Za-z_]\w*)")],
    "go": [re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*[\[(]"),
           re.compile(r"^type\s+([A-Za-z_]\w*)\s+")],
    "rb": [re.compile(r"^\s*def\s+(?:self\.)?([a-z_]\w*[?!]?)"),
           re.compile(r"^\s*(?:class|module)\s+([A-Z]\w*)")],
    "php": [re.compile(r"^\s*(?:(?:public|private|protected|static|final|abstract)\s+)*function\s+([A-Za-z_]\w*)"),
            re.compile(r"^\s*(?:(?:final|abstract)\s+)?(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)")],
    "rs": [re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([a-z_]\w*)"),
           re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)")],
}
# names that are conventionally invoked by a framework/runtime, never directly
IMPLICIT_NAMES = {
    "main", "__init__", "__str__", "__repr__", "__eq__", "__hash__", "__call__", "__enter__",
    "__exit__", "__iter__", "__next__", "__len__", "__getitem__", "__setitem__", "__post_init__",
    "setUp", "tearDown", "setUpClass", "tearDownClass", "init", "constructor", "render",
    "componentDidMount", "componentWillUnmount", "ngOnInit", "ngOnDestroy", "toString", "equals",
    "hashCode", "Dispose", "Main", "ConfigureServices", "Configure", "OnModelCreating", "Up", "Down",
    "get", "post", "put", "patch", "delete", "handle", "handler", "run", "execute", "setup",
    "default", "index", "show", "create", "update", "destroy", "new", "edit", "String", "Error",
    "ServeHTTP", "Close", "Read", "Write", "ToString", "Equals", "GetHashCode", "OnGet", "OnPost",
}
TEST_FILE_RE = re.compile(r"(^|/)(tests?|__tests__|spec|specs)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$|Tests?\.\w+$")
ENTRYPOINT_RE = re.compile(
    r"(^|/)(main|index|app|server|cli|manage|setup|wsgi|asgi|conftest|__init__|__main__|Program|"
    r"Startup|settings|config|urls|routes|admin|apps|models|serializers|views|tasks|signals|"
    r"middleware|schema|page|layout|route|loading|error|not-found|\+page|\+layout|_app|_document)"
    r"\.\w+$|(^|/)(migrations|pages|bin|scripts|cmd|public|static|fixtures|seeds)/"
)

PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+[\w.]+\s+)?import\s+(.+?)\s*$")
JS_IMPORT_RE = re.compile(r"^\s*import\s+(?:type\s+)?(.+?)\s+from\s+['\"]")


def imported_names(lang: str, line: str) -> list[str]:
    if lang == "py":
        m = PY_IMPORT_RE.match(line)
        if not m or line.strip().startswith("from __future__"):
            return []
        body = m.group(1).strip().strip("()").rstrip("\\").strip()
        if body == "*" or not body:
            return []
        names = []
        for part in body.split(","):
            part = part.strip()
            if not part:
                continue
            if " as " in part:
                names.append(part.split(" as ")[-1].strip())
            else:
                names.append(part.split(".")[0].strip())
        return [n for n in names if re.fullmatch(r"[A-Za-z_]\w*", n)]
    if lang == "js":
        m = JS_IMPORT_RE.match(line)
        if not m:
            return []
        clause = m.group(1)
        names = []
        braces = re.search(r"\{([^}]*)\}", clause)
        if braces:
            for part in braces.group(1).split(","):
                part = part.strip().removeprefix("type ").strip()
                if part:
                    names.append(part.split(" as ")[-1].strip())
            clause = clause.replace(braces.group(0), "")
        star = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)", clause)
        if star:
            names.append(star.group(1))
            clause = clause.replace(star.group(0), "")
        default = clause.strip().strip(",").strip()
        if default and re.fullmatch(r"[A-Za-z_$][\w$]*", default):
            names.append(default)
        return [n for n in names if re.fullmatch(r"[A-Za-z_$][\w$]*", n)]
    return []


def count_word(text: str, word: str) -> int:
    return len(re.findall(r"(?<![\w$])" + re.escape(word) + r"(?![\w$])", text))


def is_comment_ref(grep_line: str) -> bool:
    """True if a `git grep -n` hit (path:line:text) sits on a comment line (e.g. commented-out code)."""
    path, _, rest = grep_line.partition(":")
    _, _, text = rest.partition(":")
    prefixes = COMMENT_PREFIX.get(lang_of(path) or "", ())
    return any(text.strip().startswith(p) for p in prefixes)


def repo_references(word: str) -> list[str]:
    """Lines (path:line:text) across tracked + untracked files containing `word` as a whole word."""
    proc = git("grep", "-n", "-I", "-w", "--untracked", "-F", "-e", word, "--", ".", check=False)
    if proc.returncode not in (0, 1):
        return []
    return [ln for ln in proc.stdout.splitlines() if ln]


# ---------------------------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------------------------


def check_hygiene(rep: Report, base: str, mb: str, committed_only: bool, changed: list[str],
                  untracked: list[str]):
    counts = git_out("rev-list", "--left-right", "--count", f"{base}...HEAD").split()
    behind, ahead = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
    rep.notes.append(f"{ahead} commit(s) ahead of {base}, {behind} behind")
    if ahead == 0 and not changed:
        rep.add("hygiene/empty-branch", "blocker", f"branch has no changes relative to {base}")
    if behind:
        rep.add("hygiene/behind-base", "warning",
                f"branch is {behind} commit(s) behind {base}; rebase or merge before opening the PR")

    mt = git("merge-tree", "--write-tree", "--name-only", "--no-messages", base, "HEAD", check=False)
    if mt.returncode == 1:
        files = [l for l in mt.stdout.splitlines()[1:] if l.strip()]
        rep.add("hygiene/merge-conflict", "blocker",
                f"merging into {base} will conflict in: {', '.join(files[:10]) or '(unknown files)'}")
    elif mt.returncode not in (0, 1):
        rep.notes.append("merge-conflict check skipped (needs git >= 2.38 for `merge-tree --write-tree`)")

    status = git_out("status", "--porcelain")
    tracked_dirty = [l for l in status.splitlines() if l and not l.startswith("??")]
    if tracked_dirty:
        sev = "warning"
        msg = f"{len(tracked_dirty)} tracked file(s) have uncommitted changes"
        if committed_only:
            msg += " (not included in this scan)"
        else:
            msg += " (included in this scan -- commit them or they won't be in the PR)"
        rep.add("hygiene/uncommitted", sev, msg, snippet="; ".join(l[3:] for l in tracked_dirty[:10]))
    if untracked:
        rep.add("hygiene/untracked", "info",
                f"{len(untracked)} untracked file(s) -- add them if they belong to this PR, "
                f"otherwise ignore or delete", snippet="; ".join(untracked[:10]))

    log = git_out("log", "--format=%h %s", f"{mb}..HEAD")
    for line in log.splitlines():
        sha, _, subj = line.partition(" ")
        if re.match(r"(?i)^(fixup!|squash!|amend!|wip\b|tmp\b|temp\b|test commit|asdf|\.+$)", subj.strip()) \
                or re.search(r"(?i)\b(wip|do not merge|dnm)\b", subj):
            rep.add("hygiene/wip-commit", "warning",
                    f"commit {sha} looks like a work-in-progress/fixup commit: '{subj}' -- squash or reword")

    for path in changed + untracked:
        norm = path.replace("\\", "/")
        if SUSPICIOUS_FILE_RE.search(norm) and not ENV_TEMPLATE_RE.search(norm):
            sev = "blocker" if re.search(r"(?i)(\.env|id_rsa|id_ed25519|\.pem|\.key|\.p12|\.pfx|\.keystore)$", norm) \
                else "warning"
            rep.add("hygiene/suspicious-file", sev,
                    "file type that is rarely meant to be committed (secret, log, backup, OS or scratch file)",
                    file=path)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > 1_000_000:
            rep.add("hygiene/large-file", "warning", f"{size / 1_000_000:.1f} MB added/changed -- "
                    "consider Git LFS or keeping it out of the repo", file=path)


def check_added_lines(rep: Report, added: dict[str, list[tuple[int, str]]]):
    for path, lines in added.items():
        lang = lang_of(path)
        norm = path.replace("\\", "/")
        generated = is_generated_or_vendored(norm)
        is_test = bool(TEST_FILE_RE.search(norm))
        is_doc = norm.lower().endswith(DOC_SUFFIXES)
        prefixes = COMMENT_PREFIX.get(lang or "", ())
        comment_run: list[tuple[int, str]] = []

        def flush_comments():
            if len(comment_run) >= 2 or (comment_run and len(comment_run[0][1]) > 30):
                ln0, txt0 = comment_run[0]
                rep.add("leftovers/commented-out-code", "warning",
                        f"{len(comment_run)} added comment line(s) that look like disabled code",
                        file=path, line=ln0, snippet=txt0.strip()[:120])
            comment_run.clear()

        for ln, text in lines:
            stripped = text.strip()

            if CONFLICT_RE.match(text) and not is_doc:
                rep.add("hygiene/conflict-marker", "blocker", "unresolved merge conflict marker",
                        file=path, line=ln, snippet=stripped[:120])

            if not is_doc:
                for label, pat in SECRET_PATTERNS:
                    m = pat.search(text)
                    if m and not PLACEHOLDER_SECRET.search(m.group(0)):
                        rep.add("hygiene/possible-secret", "blocker",
                                f"possible {label} in an added line (value redacted)", file=path, line=ln,
                                snippet=pat.sub("<redacted>", stripped)[:120])
                        break

            if generated or lang is None:
                continue

            if TODO_RE.search(text) and any(stripped.startswith(p) for p in prefixes + ("/*", "*", "<!--")):
                rep.add("leftovers/new-todo", "info", "TODO/FIXME/HACK added in this branch",
                        file=path, line=ln, snippet=stripped[:120])

            if FOCUSED_TEST.search(text):
                rep.add("leftovers/focused-or-skipped-test", "warning",
                        "focused (.only) or skipped test added -- the suite may silently run less",
                        file=path, line=ln, snippet=stripped[:120])

            is_comment = any(stripped.startswith(p) for p in prefixes)
            if not is_comment:
                for pat in DEBUG_PATTERNS.get(lang, []):
                    if re.search(pat, text):
                        rep.add("leftovers/debug-statement", "info" if is_test else "warning",
                                "debug/print statement added (confirm it isn't intended output or logging)",
                                file=path, line=ln, snippet=stripped[:120])
                        break

            if is_comment:
                body = stripped
                for p in prefixes:
                    if body.startswith(p):
                        body = body[len(p):].strip()
                        break
                if body and not TODO_RE.search(body) and CODEISH_RE.search(body) and not body.endswith((".", ":")) \
                        and not body.startswith(("eslint", "noqa", "type:", "pylint", "@ts-", "prettier", "nolint",
                                                 "#region", "#endregion", "pragma", "region", "endregion", "-*-", "!")):
                    comment_run.append((ln, text))
                    continue
            flush_comments()
        flush_comments()


def check_unused(rep: Report, added: dict[str, list[tuple[int, str]]], new_files: set[str],
                 max_symbols: int = 200):
    checked = 0
    for path, lines in added.items():
        lang = lang_of(path)
        norm = path.replace("\\", "/")
        if lang is None or is_generated_or_vendored(norm):
            continue
        is_test = bool(TEST_FILE_RE.search(norm))
        content = read_text(path)
        if content is None:
            continue

        # unused imports added in this file
        for ln, text in lines:
            for name in imported_names(lang, text):
                if name in ("React", "h", "_"):
                    continue
                if count_word(content, name) <= 1:
                    rep.add("unused/import", "warning", f"'{name}' is imported here but never used in this file",
                            file=path, line=ln, snippet=text.strip()[:120])

        # new symbol definitions with no reference anywhere else
        if is_test:
            continue
        for ln, text in lines:
            for pat in DEF_PATTERNS.get(lang, []):
                m = pat.match(text)
                if not m:
                    continue
                name = m.group(1)
                if name in IMPLICIT_NAMES or name.startswith("__") or len(name) < 3 \
                        or re.match(r"(?i)^test", name):
                    break
                if checked >= max_symbols:
                    break
                checked += 1
                refs = repo_references(name)
                others = [r for r in refs if not r.startswith(f"{norm}:{ln}:") and not is_comment_ref(r)]
                if not others:
                    exported = bool(re.match(r"^\s*(export|pub\b|public\b)", text)) or \
                        (lang == "go" and name[:1].isupper())
                    note = " (exported -- may be public API consumed outside this repo)" if exported else ""
                    rep.add("unused/symbol", "warning",
                            f"'{name}' is defined in this branch but referenced nowhere else in the repo{note}",
                            file=path, line=ln, snippet=text.strip()[:120])
                break

    # new source files nothing references by module/file name
    for path in sorted(new_files):
        norm = path.replace("\\", "/")
        lang = lang_of(norm)
        if lang is None or lang in ("sql", "html", "sh", "ps") or is_generated_or_vendored(norm) \
                or TEST_FILE_RE.search(norm) or ENTRYPOINT_RE.search(norm):
            continue
        stem = os.path.splitext(os.path.basename(norm))[0]
        if len(stem) < 3:
            continue
        refs = [r for r in repo_references(stem) if not r.startswith(norm + ":")]
        if not refs:
            rep.add("unused/orphan-file", "warning",
                    f"new file whose name '{stem}' is not referenced by any other file (nothing imports it?)",
                    file=path)


def check_whitespace_only(rep: Report, diff_args: list[str]):
    full = git_out("diff", "--numstat", *diff_args)
    ws = git_out("diff", "--numstat", "-w", "--ignore-blank-lines", *diff_args)

    def parse(out):
        res = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0] != "-":
                res[parts[2]] = int(parts[0]) + int(parts[1])
        return res

    full_m, ws_m = parse(full), parse(ws)
    for path, n in full_m.items():
        if n and ws_m.get(path, 0) == 0 and "=>" not in path:
            rep.add("unused/whitespace-only", "info",
                    f"only whitespace/blank-line changes ({n} line(s)) -- likely editor noise; revert unless intended",
                    file=path)


# ---------------------------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------------------------

SEV_ORDER = {"blocker": 0, "warning": 1, "info": 2}


def render_markdown(rep: Report, max_per_check: int) -> str:
    out = [f"# Branch scan: {rep.branch} vs {rep.base}", "",
           f"- merge-base: `{rep.merge_base[:12]}`  scope: {rep.scope}  files changed: {rep.files_changed}"]
    out += [f"- {n}" for n in rep.notes]
    by_sev = {s: sum(1 for f in rep.findings if f.severity == s) for s in SEV_ORDER}
    out += [f"- findings: {by_sev['blocker']} blocker, {by_sev['warning']} warning, {by_sev['info']} info", ""]
    if not rep.findings:
        out.append("No findings.")
        return "\n".join(out)
    groups: dict[str, list[Finding]] = {}
    for f in sorted(rep.findings, key=lambda f: (SEV_ORDER[f.severity], f.check, f.file, f.line)):
        groups.setdefault(f.check, []).append(f)
    for check, items in sorted(groups.items(), key=lambda kv: (SEV_ORDER[kv[1][0].severity], kv[0])):
        sevs = "/".join(s for s in SEV_ORDER if any(f.severity == s for f in items))
        out.append(f"## {check} ({len(items)}, {sevs})")
        for f in items[:max_per_check]:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            line = f"- {loc + ' -- ' if loc else ''}{f.detail}"
            if f.snippet:
                line += f"\n  `{f.snippet.replace('`', chr(39))}`"
            out.append(line)
        if len(items) > max_per_check:
            out.append(f"- ... {len(items) - max_per_check} more (use --json or --max-per-check)")
        out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", help="base branch/ref the PR will target (default: auto-detect)")
    ap.add_argument("--committed-only", action="store_true",
                    help="scan merge-base..HEAD only (ignore uncommitted and untracked files)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    ap.add_argument("--max-per-check", type=int, default=25, help="cap items shown per check in Markdown")
    args = ap.parse_args()

    try:
        top = git_out("rev-parse", "--show-toplevel").strip()
        os.chdir(top)
        base = resolve_base(args.base)
        mb = git_out("merge-base", base, "HEAD").strip()
        branch = git_out("rev-parse", "--abbrev-ref", "HEAD").strip()
    except RuntimeError as exc:
        print(f"scan_branch: {exc}", file=sys.stderr)
        return 2

    diff_args = [mb, "HEAD"] if args.committed_only else [mb]
    scope = f"{mb[:12]}..HEAD" if args.committed_only else f"{mb[:12]}..working tree (+untracked)"
    rep = Report(base=base, merge_base=mb, branch=branch, scope=scope)

    if branch in ("main", "master", "develop") or base.split("/")[-1] == branch:
        rep.add("hygiene/on-base-branch", "blocker",
                f"you are on '{branch}' -- create a feature branch before opening a PR")

    name_status = git_out("diff", "--name-status", "--no-renames", *diff_args)
    changed, new_files = [], set()
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and not parts[0].startswith("D"):
            changed.append(parts[-1])
            if parts[0].startswith("A"):
                new_files.add(parts[-1])
    untracked = [] if args.committed_only else \
        [l for l in git_out("ls-files", "--others", "--exclude-standard").splitlines() if l]
    rep.files_changed = len(changed) + len(untracked)

    added = parse_added_lines(git_out("diff", "-U0", "--no-color", "--no-renames", "--no-ext-diff", *diff_args))
    for path in untracked:
        text = read_text(path)
        if text is not None:
            added[path] = list(enumerate(text.splitlines(), start=1))
        new_files.add(path)

    check_hygiene(rep, base, mb, args.committed_only, changed, untracked)
    check_added_lines(rep, added)
    check_unused(rep, added, new_files)
    check_whitespace_only(rep, diff_args)

    if args.json:
        print(json.dumps({**asdict(rep), "findings": [asdict(f) for f in rep.findings]}, indent=2))
    else:
        print(render_markdown(rep, args.max_per_check))
    return 0


if __name__ == "__main__":
    sys.exit(main())
