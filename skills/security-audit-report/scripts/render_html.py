#!/usr/bin/env python3
"""Render a security report from Markdown into a styled, self-contained HTML page.

The markdown is the single source of truth. Keeping a hand-edited HTML copy alongside it always
ends the same way: the two drift, and the prettier one is the one people read and the stale one
is the one they trust.

Usage:
    python render_html.py report.md report.html
    python render_html.py report.md report.html --css custom.css

Deliberately a small converter rather than a dependency: security reports get run in locked-down
environments where `pip install` is not available, and the markdown subset here is one this skill
controls. It handles headings, tables, fenced code, blockquotes, lists, inline formatting, links,
and horizontal rules.

Two report-specific touches make the output readable rather than merely converted:

  * `### 12. Title` becomes a numbered finding card, so findings are visually separable.
  * `- **Severity:** High` gets a coloured chip, so a reader can scan tiers without reading prose.

The masthead (title, provenance, severity ledger) is built from the report's own front matter --
the standfirst paragraph, the provenance table, and the severity breakdown table -- so there is
nothing to keep in sync by hand.
"""
import argparse
import html as H
import os
import re
import sys
import unicodedata

SEV_CLASS = {"critical": "crit", "high": "high", "medium": "med",
             "low": "low", "provisional": "prov"}

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Zilla+Slab:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600'
    '&family=IBM+Plex+Mono:wght@400;500&display=swap">'
)


def inline(s):
    """Inline markdown -> HTML.

    Code spans are stashed behind placeholders first so that bold or italics *wrapping* a code
    span still pairs up -- splitting on backticks first breaks `**`code`**` into orphaned markers.
    """
    spans = []

    def stash(m):
        spans.append("<code>" + H.escape(m.group(1)) + "</code>")
        return f"\x00{len(spans) - 1}\x00"

    t = re.sub(r"`([^`]+)`", stash, s)
    t = H.escape(t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"~~(.+?)~~", r"<s>\1</s>", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], t)


def cells(row):
    r = row.strip().strip("|")
    return [c.strip() for c in (r.split(" | ") if " | " in r else r.split("|"))]


def heading_slug(text, seen):
    """Return a unique GitHub-style fragment for a Markdown heading.

    Reports commonly contain a hand-written contents list whose fragments follow
    GitHub Markdown conventions. Giving every rendered heading the same style of
    id keeps those links working in the standalone HTML. Repeated headings use
    GitHub's -1, -2 suffix convention.
    """
    rendered = inline(text)
    plain = H.unescape(re.sub(r"<[^>]+>", "", rendered)).lower().strip()
    chars = []
    for char in plain:
        category = unicodedata.category(char)
        if char.isalnum() or category.startswith("M") or char in {" ", "-", "_"}:
            chars.append(char)
    base = re.sub(r"\s+", "-", "".join(chars)).strip("-") or "section"
    occurrence = seen.get(base, 0)
    seen[base] = occurrence + 1
    return base if occurrence == 0 else f"{base}-{occurrence}"


def convert(md):
    lines = md.split("\n")
    out, i, n, open_card = [], 0, len(lines), False
    heading_ids = {}

    def close_card():
        # Two closes: the .f-body column and the .finding grid that wraps it.
        nonlocal open_card
        if open_card:
            out.append("</div></div>")
            open_card = False

    while i < n:
        line = lines[i]

        if line.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + H.escape("\n".join(buf)) + "</code></pre>")
            continue

        m = re.match(r"^(#{1,4}) (.*)$", line)
        if m:
            level, text = len(m.group(1)), m.group(2)
            anchor = heading_slug(text, heading_ids)
            fm = re.match(r"^(\d+)\.\s+(.*)$", text)
            if level == 3 and fm:
                close_card()
                # .finding is a two-column grid: the number sits in the gutter and everything
                # else goes in .f-body. Both must be *direct* children of .finding -- emitting
                # the body's blocks as bare siblings instead lets grid auto-placement drop every
                # other one (the title, the evidence block) into the 3.5rem gutter column.
                out.append('<div class="finding">')
                out.append(f'<span class="f-num">{fm.group(1)}</span>')
                out.append('<div class="f-body">')
                open_card = True
                out.append(f'<h3 class="f-title" id="{H.escape(anchor, quote=True)}">'
                           f'{inline(fm.group(2))}</h3>')
            else:
                close_card()
                out.append(f'<h{level} id="{H.escape(anchor, quote=True)}">{inline(text)}</h{level}>')
            i += 1
            continue

        if line.strip() == "---":
            close_card()
            out.append("<hr>")
            i += 1
            continue

        if line.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            head = cells(line)
            i += 2
            body = []
            while i < n and lines[i].startswith("|"):
                body.append(cells(lines[i]))
                i += 1
            # A Severity column (the at-a-glance table) gets a colour dot, so the tier is
            # scannable down the page. Matched on the header name, so the category matrix --
            # whose *headers* are severity names but whose cells are counts -- is untouched.
            sev_col = next((k for k, c in enumerate(head)
                            if re.sub(r"[^a-z]", "", c.lower()) == "severity"), None)
            t = ['<div class="tbl-scroll"><table><thead><tr>']
            t += [f"<th>{inline(c)}</th>" for c in head]
            t.append("</tr></thead><tbody>")
            for r in body:
                tds = []
                for k, c in enumerate(r):
                    sm = (re.match(r"\*{0,2}(Critical|High|Medium|Low|Provisional)\b", c.strip())
                          if k == sev_col else None)
                    if sm:
                        dot = f'<span class="sev-dot sd-{SEV_CLASS[sm.group(1).lower()]}"></span>'
                        tds.append(f'<td class="sev">{dot}{inline(c)}</td>')
                    else:
                        tds.append(f"<td>{inline(c)}</td>")
                t.append("<tr>" + "".join(tds) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
            continue

        if line.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            out.append(f"<blockquote>{inline(' '.join(buf))}</blockquote>")
            continue

        if re.match(r"^[-*] ", line):
            out.append("<ul>")
            while i < n and (re.match(r"^[-*] ", lines[i])
                             or (lines[i].startswith("  ") and lines[i].strip())):
                if re.match(r"^[-*] ", lines[i]):
                    item = [lines[i][2:]]
                    i += 1
                    while (i < n and lines[i].startswith("  ") and lines[i].strip()
                           and not re.match(r"^[-*] ", lines[i])):
                        item.append(lines[i].strip())
                        i += 1
                    text = " ".join(item)
                    # The chip states the severity, so consume the "**Severity:** High ·"
                    # that produced it rather than printing the tier twice on one line.
                    sm = re.match(r"\*\*Severity:\*\*\s*\*{0,2}"
                                  r"(Critical|High|Medium|Low|Provisional)"
                                  r"\*{0,2}\s*(?:·\s*)?", text)
                    if sm:
                        cls = SEV_CLASS[sm.group(1).lower()]
                        rest = text[sm.end():].strip().lstrip("·").strip()
                        tail = f" {inline(rest)}" if rest else ""
                        out.append(f'<li><span class="chip chip-{cls}">{sm.group(1)}</span>'
                                   f'{tail}</li>')
                    else:
                        out.append(f"<li>{inline(text)}</li>")
                else:
                    i += 1
            out.append("</ul>")
            continue

        if not line.strip():
            i += 1
            continue

        buf = [line]
        i += 1
        while i < n and lines[i].strip() and not re.match(r"^(#{1,4} |```|\||>|[-*] |---$)", lines[i]):
            buf.append(lines[i])
            i += 1
        out.append(f"<p>{inline(' '.join(buf))}</p>")

    close_card()
    return "\n".join(out)


def build_masthead(md):
    """Assemble title, provenance and the severity ledger from the report's own front matter."""
    title_md = (re.search(r"^# (.+)$", md, re.M) or [None, "Security Audit"])[1]
    # The H1 often contains code spans or emphasis; render them in the masthead, and strip
    # markup entirely for <title>, which cannot carry markup at all.
    title_html = inline(title_md)
    # Derive the plain-text title by stripping tags from the rendered version rather than by
    # deleting markdown characters -- underscores are common inside identifiers like `qr_code`,
    # and a naive character strip mangles them.
    title_text = H.unescape(re.sub(r"<[^>]+>", "", title_html))

    body = md.split("\n", 1)[1] if "\n" in md else ""
    stand = ""
    for para in body.split("\n\n"):
        p = para.strip()
        if p and not p.startswith(("|", "#", ">", "-", "*")):
            stand = " ".join(p.split("\n"))
            break

    prov = re.findall(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|$", md, re.M)
    skip = {"critical", "high", "medium", "low", "provisional", "total", "level", "category"}
    chips = "".join(
        f"<span><b>{H.escape(k)}</b> {inline(v)}</span>"
        for k, v in prov[:6] if k.strip().lower() not in skip
    )

    ledger = ""
    m = re.search(r"\*\*Severity breakdown\*\*[^\n]*\n\n?\|([^\n]+)\|\n\|[-:\s|]+\|\n\|([^\n]+)\|", md)
    if m:
        heads = [h.strip() for h in m.group(1).split("|") if h.strip()]
        nums = [int(x) for x in re.findall(r"\d+", m.group(2))]
        pairs = [(h, v) for h, v in zip(heads, nums) if v]
        total = sum(v for _, v in pairs) or 1
        cls = {"critical": "crit", "high": "high", "medium": "med",
               "low": "low", "provisional": "prov", "refuted": "clear"}
        bars, keys = [], []
        for label, v in pairs:
            c = cls.get(label.strip().lower(), "clear")
            bars.append(f'<span class="lb-{c}" style="flex:{v} 1 {max(6, v * 100 // total)}%">'
                        f'{v}{"" if v * 100 // total < 8 else " " + H.escape(label)}</span>')
            keys.append(f'<div class="lk lk-{c}"><span class="lk-n">{v}</span>'
                        f'<span class="lk-l">{H.escape(label)}</span></div>')
        ledger = (f'<section class="ledger" aria-label="Findings by severity">'
                  f'<div class="ledger-bar" role="img" aria-label="'
                  + ", ".join(f"{v} {l.lower()}" for l, v in pairs) + '">'
                  + "".join(bars) + '</div><div class="ledger-key">'
                  + "".join(keys) + '</div></section>')

    return (f'<div class="wrap"><header class="masthead">'
            f'<p class="eyebrow">Application Security Review</p>'
            f'<h1>{title_html}</h1>'
            f'<p class="standfirst">{inline(stand)}</p>'
            f'<div class="provenance">{chips}</div></header>{ledger}\n'), title_text


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markdown")
    ap.add_argument("output")
    ap.add_argument("--css", help="override the bundled theme")
    args = ap.parse_args()

    md = open(args.markdown, encoding="utf-8").read()
    css_path = args.css or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "assets", "report.css")
    css = open(css_path, encoding="utf-8").read()

    masthead, title = build_masthead(md)

    # Everything before the first "## " is front matter, already rendered into the masthead.
    split = md.find("\n## ")
    body_md = md[split + 1:] if split != -1 else md

    doc = (f"<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
           f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
           f"<title>{H.escape(title)}</title>\n{FONTS}\n<style>\n{css}\n</style>\n</head>\n<body>\n"
           f"{masthead}{convert(body_md)}\n</div>\n</body>\n</html>\n")

    open(args.output, "w", encoding="utf-8").write(doc)

    findings = len(re.findall(r'<span class="f-num">', doc))
    balanced = len(re.findall(r"<div\b", doc)) == doc.count("</div>")
    ids = set(re.findall(r'\bid="([^"]+)"', doc))
    fragments = set(re.findall(r'href="#([^"]+)"', doc))
    missing_fragments = sorted(fragments - ids)
    print(f"wrote {args.output} ({len(doc):,} bytes)")
    print(f"  findings rendered : {findings}")
    print(f"  tags balanced     : {balanced}")
    print(f"  internal links    : {len(fragments) - len(missing_fragments)}/{len(fragments)} resolved")
    if not balanced:
        print("  WARNING: unbalanced <div> tags -- check for a malformed table or heading")
        return 1
    if missing_fragments:
        print("  WARNING: unresolved internal links: " + ", ".join(missing_fragments))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
