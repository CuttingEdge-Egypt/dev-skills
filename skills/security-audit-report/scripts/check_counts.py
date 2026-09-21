#!/usr/bin/env python3
"""Reconcile a security report's summary tables against the findings themselves.

Hand-maintained counts drift the moment a finding is promoted, demoted, added or removed --
a single promotion changes a cell in the severity table, a cell in the category matrix, a row
in the at-a-glance table, both total rows, and often a sentence of prose. This reads the
findings as the source of truth and tells you what the tables should say.

Usage:
    python check_counts.py report.md
    python check_counts.py report.md --json     # machine-readable, for CI

Exit status is 0 when every table matches the findings, 1 otherwise -- so it can gate a commit.

What it expects to find in the report (all of which the skill's template produces):

    ### 12. Some finding title
    - **Severity:** High · **Confidence:** 9/10
    - **Category:** Injection & SSRF · **Impact:** Internal network read
    ...
    **Acceptance check.** What must be observably true for this to be closed.

Low findings may instead be table rows, in either supported shape -- number and title fused
into the first cell, or a separate `#` column:

    | **41. Some low finding** | Category name | location | assessment | acceptance check |
    | **41** | Some low finding | Category name | location | assessment | acceptance check |

Tables are located by their headers rather than by row shape, so column order is free and an
extra column (an acceptance check, a starting position) does not break parsing.
"""
import argparse
import collections
import json
import re
import sys

SEVERITIES = ["Critical", "High", "Medium", "Low", "Provisional"]

# "- **Severity:** High" / "- **Severity:** **Provisional**" / "- **Severity:** Critical (historical)"
SEVERITY_RE = re.compile(r"^-\s+\*\*Severity:\*\*\s*\*{0,2}(" + "|".join(SEVERITIES) + r")")
CATEGORY_RE = re.compile(r"^-\s+\*\*Category:\*\*\s*(.+?)\s*·\s*\*\*Impact:\*\*")
HEADING_RE = re.compile(r"^###\s+(\d+)\.\s")
ACCEPTANCE_RE = re.compile(r"\*\*Acceptance check[.:]?\*\*", re.I)
DIVIDER_RE = re.compile(r"^\|[\s:|-]+\|?\s*$")


def split_cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def leading_number(cell):
    """The finding number a table cell starts with, bold or plain, or None."""
    m = re.match(r"^\*{0,2}(\d+)\*{0,2}\.?\s*", cell.strip())
    return int(m.group(1)) if m else None


def iter_tables(lines):
    """Yield (headers, rows) for every pipe table, where rows is [(line_index, cells)]."""
    i, n = 0, len(lines)
    while i < n:
        if (lines[i].lstrip().startswith("|") and i + 1 < n
                and DIVIDER_RE.match(lines[i + 1].strip())):
            headers = split_cells(lines[i])
            i += 2
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append((i, split_cells(lines[i])))
                i += 1
            yield headers, rows
        else:
            i += 1


def column(headers, *names):
    """Index of the first header matching any of `names`, ignoring case and markup."""
    cleaned = [re.sub(r"[^a-z0-9 ]", "", h.lower()).strip() for h in headers]
    for name in names:
        if name in cleaned:
            return cleaned.index(name)
    return None


def classify_tables(lines):
    """Locate the at-a-glance table and the Low findings table by their headers.

    Row shape is a poor discriminator -- the category matrix, the Low table and the glance
    table all begin with a bolded or numeric first cell. Headers are unambiguous: the glance
    table is the one carrying a Severity column beside numbered findings, and the Low table
    carries a Category column without one.
    """
    glance, low = None, None
    for headers, rows in iter_tables(lines):
        numbered = rows and all(leading_number(r[1][0]) is not None for r in rows if r[1])
        if not numbered:
            continue
        has_sev = column(headers, "severity") is not None
        has_cat = column(headers, "category") is not None
        if has_sev and glance is None:
            glance = (headers, rows)
        elif has_cat and low is None:
            low = (headers, rows)
    return glance, low


def parse(md):
    """Walk the report once, attributing each finding to a severity and category."""
    lines = md.split("\n")

    # Section offsets let us fall back to the enclosing heading when a finding omits
    # an explicit severity line -- which is itself worth reporting.
    section_at = {}
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("## "):
            name = s[3:].strip()
            if name in SEVERITIES:
                section_at[i] = name

    def section_for(idx):
        best = None
        for i, name in section_at.items():
            if i < idx:
                best = name
        return best

    counts = collections.defaultdict(lambda: collections.defaultdict(int))
    numbers, missing_severity, current = [], [], None
    severity_by_number, no_acceptance = {}, []

    for i, line in enumerate(lines):
        h = HEADING_RE.match(line)
        if h:
            current = int(h.group(1))
            numbers.append(current)
            # A finding's body runs to the next finding or the next section heading.
            body = []
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("### ") or lines[j].startswith("## "):
                    break
                body.append(lines[j])
            if not ACCEPTANCE_RE.search("\n".join(body)):
                no_acceptance.append(current)

        c = CATEGORY_RE.match(line)
        if not c:
            continue
        category = c.group(1).strip()

        # Scan back to this finding's own heading looking for its severity line.
        # Stopping at the heading is what makes multi-line severity notes safe.
        severity = None
        for j in range(i - 1, -1, -1):
            if lines[j].startswith("### "):
                break
            m = SEVERITY_RE.match(lines[j])
            if m:
                severity = m.group(1)
                break

        if severity is None:
            severity = section_for(i) or "Medium"
            missing_severity.append(current)

        counts[category][severity] += 1
        if current is not None:
            severity_by_number[current] = severity

    # Low findings may live in a table, one row each.
    _, low = classify_tables(lines)
    low_rows = set()
    if low:
        headers, rows = low
        cat_at = column(headers, "category")
        acc_at = column(headers, "acceptance check", "acceptance")
        for idx, cells in rows:
            num = leading_number(cells[0])
            if num is None:
                continue
            low_rows.add(idx)
            numbers.append(num)
            severity_by_number[num] = "Low"
            category = cells[cat_at] if cat_at is not None and cat_at < len(cells) else "(uncategorised)"
            counts[category.strip()]["Low"] += 1
            if acc_at is None or acc_at >= len(cells) or not cells[acc_at].strip():
                no_acceptance.append(num)

    return counts, sorted(numbers), missing_severity, severity_by_number, sorted(set(no_acceptance)), low_rows


def published_tables(md, skip_lines=frozenset()):
    """Pull the numbers the report currently claims, so we can diff against reality."""
    found = {}
    lines = md.split("\n")

    # Category matrix rows. The blurb after the name is optional, and the trailing total may or
    # may not be bold -- an earlier version required both, which meant a perfectly ordinary row
    # was skipped in silence and the script reported "all tables reconcile" without having
    # checked the table at all. Anything that looks like a matrix row but will not parse is
    # surfaced as `unparsed_rows` rather than ignored; a checker that fails open is worse than
    # no checker, because it converts an unchecked table into a green tick.
    rows, unparsed = {}, []
    for i, line in enumerate(lines):
        if not line.startswith("| **") or i in skip_lines:
            continue
        cells = split_cells(line)
        if len(cells) < 3:
            continue
        name = re.match(r"^\*\*(.+?)\*\*", cells[0])
        if not name:
            continue
        label = name.group(1).strip()
        if label.lower() in ("total", "finding", "category", "level"):
            continue
        nums, ok = [], True
        for c in cells[1:]:
            c = c.strip().strip("*")
            if c in ("-", "–", ""):
                nums.append(0)
            elif c.isdigit():
                nums.append(int(c))
            else:
                ok = False
                break
        # A severity matrix row is numeric all the way across, with a trailing total.
        if ok and len(nums) >= 3:
            rows[label] = nums[:-1] if len(nums) > 1 else nums
        elif any(ch.isdigit() for ch in "".join(cells[1:])) and len(cells) >= 5:
            unparsed.append(line.strip()[:90])
    if rows:
        found["category_rows"] = rows
    if unparsed:
        found["unparsed_rows"] = unparsed

    m = re.search(r"^\|\s*\*\*Total\*\*\s*\|((?:\s*\*\*\d+\*\*\s*\|)+)$", md, re.M)
    if m:
        found["category_total"] = [int(x) for x in re.findall(r"\d+", m.group(1))]

    # Severity breakdown: the first all-numeric table row after the heading.
    m = re.search(r"\*\*Severity breakdown\*\*.*?\n\|[^\n]*\n\|[-:\s|]+\n\|([^\n]+)\|", md, re.S)
    if m:
        found["severity_row"] = [int(x) for x in re.findall(r"\d+", m.group(1))]

    return found


def check_glance(lines, severity_by_number):
    """The at-a-glance table repeats every finding's number and severity, so it drifts first.

    It is the one table a reader scans instead of the findings, which makes a stale row worse
    than a missing table: it is wrong in the place most people look.
    """
    problems = []
    glance, _ = classify_tables(lines)
    if glance is None:
        return problems, False

    headers, rows = glance
    sev_at = column(headers, "severity")
    listed = {}
    for _, cells in rows:
        num = leading_number(cells[0])
        if num is None or sev_at is None or sev_at >= len(cells):
            continue
        m = re.search(r"\*{0,2}(" + "|".join(SEVERITIES) + r")\*{0,2}", cells[sev_at])
        listed[num] = m.group(1) if m else cells[sev_at].strip()

    if len(listed) != len(rows):
        problems.append(f"at-a-glance table: {len(rows)} rows but {len(listed)} parsed — "
                        f"check the number and severity columns")

    missing = sorted(set(severity_by_number) - set(listed))
    extra = sorted(set(listed) - set(severity_by_number))
    if missing:
        problems.append(f"at-a-glance table is missing findings: {missing}")
    if extra:
        problems.append(f"at-a-glance table lists findings that do not exist: {extra}")

    mismatched = [(n, listed[n], severity_by_number[n]) for n in sorted(set(listed) & set(severity_by_number))
                  if listed[n] != severity_by_number[n]]
    for num, said, actual in mismatched:
        problems.append(f"at-a-glance row {num} says {said}, finding {num} says {actual}")

    return problems, True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = ap.parse_args()

    md = open(args.report, encoding="utf-8").read()
    lines = md.split("\n")
    counts, numbers, missing, severity_by_number, no_acceptance, low_rows = parse(md)
    pub = published_tables(md, skip_lines=low_rows)

    totals = collections.Counter()
    for cat in counts:
        for sev, n in counts[cat].items():
            totals[sev] += n
    actual = [totals[s] for s in SEVERITIES]
    problems = []

    # Numbering: gaps and duplicates both make a report hard to cite.
    dupes = sorted({n for n in numbers if numbers.count(n) > 1})
    if dupes:
        problems.append(f"duplicate finding numbers: {dupes}")
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        gaps = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
        if gaps:
            problems.append(f"gaps in numbering: {gaps}")

    if missing:
        problems.append(f"findings with no explicit Severity line: {sorted(set(missing))}")

    if no_acceptance:
        problems.append(f"findings with no Acceptance check: {no_acceptance}")

    glance_problems, has_glance = check_glance(lines, severity_by_number)
    problems += glance_problems

    if "category_total" in pub and pub["category_total"][:5] != actual:
        problems.append(f"category table total row says {pub['category_total'][:5]}, findings say {actual}")
    if "severity_row" in pub and pub["severity_row"][:5] != actual[: len(pub["severity_row"][:5])]:
        problems.append(f"severity breakdown says {pub['severity_row'][:5]}, findings say {actual}")

    for name, row in pub.get("category_rows", {}).items():
        if name not in counts:
            problems.append(f"category row '{name}' has no findings using that category name "
                            f"— taxonomy drift, or a typo in the table")
            continue
        want = [counts[name][s] for s in SEVERITIES][: len(row)]
        if row != want:
            problems.append(f"category row '{name}' says {row}, findings say {want}")

    for cat in counts:
        if "category_rows" in pub and cat not in pub["category_rows"]:
            problems.append(f"category '{cat}' is used by findings but missing from the matrix")

    for line in pub.get("unparsed_rows", []):
        problems.append(f"table row looks like a matrix row but could not be parsed, so it was "
                        f"NOT checked: {line}")

    if args.json:
        print(json.dumps({
            "by_severity": dict(zip(SEVERITIES, actual)),
            "total": sum(actual),
            "by_category": {k: dict(v) for k, v in counts.items()},
            "numbering_ok": not dupes and numbers == list(range(1, len(numbers) + 1)),
            "at_a_glance_present": has_glance,
            "findings_without_acceptance_check": no_acceptance,
            "problems": problems,
        }, indent=2))
        return 1 if problems else 0

    print(f"{'Category':52}" + "".join(f"{s[:4]:>6}" for s in SEVERITIES) + f"{'total':>7}")
    print("-" * 95)
    for cat in sorted(counts, key=lambda c: -sum(counts[c].values())):
        row = [counts[cat][s] for s in SEVERITIES]
        print(f"{cat[:52]:52}" + "".join(f"{n or '-':>6}" for n in row) + f"{sum(row):>7}")
    print("-" * 95)
    print(f"{'TOTAL':52}" + "".join(f"{n:>6}" for n in actual) + f"{sum(actual):>7}")
    print(f"\nfindings numbered: {len(numbers)}  (contiguous 1-{len(numbers)}: "
          f"{numbers == list(range(1, len(numbers) + 1))})")
    print(f"at-a-glance table: {'present, reconciled' if has_glance and not glance_problems else 'present, PROBLEMS' if has_glance else 'absent'}")
    print(f"acceptance checks: {len(numbers) - len(no_acceptance)}/{len(numbers)} findings")

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  -", p)
        return 1
    print("\nAll summary tables reconcile against the findings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
