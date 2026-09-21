# Incremental updates against a newer commit

Re-running an audit is not re-running the scan. Most of the work is deciding what the prior report
still means, and the failure modes here are different from a fresh audit's.

## 1. Establish the relationship between the two commits

```bash
git merge-base --is-ancestor <old-commit> HEAD && echo "HEAD moved forward from the audit" \
  || echo "diverged -- ask which commit the report should describe"
git log --oneline <old-commit>..HEAD | wc -l
git diff --stat <old-commit>..HEAD | tail -1
```

If the branches diverged, stop and ask. A report anchored to a commit that is not an ancestor of
what you are reading will produce findings nobody can reproduce.

## 2. Decide the model, and say which one you chose

Two coherent options. Mixing them is the mistake:

**Current-state** (usually what people want). The report describes HEAD. Fixed findings are removed
from the body and from every count. Every citation must be rebased. Severities describe current
risk.

**Frozen** . The report stays an audit of the original commit, with a separate appendix recording
what has since been fixed. Citations stay as they were. Good for compliance, where the artefact
needs to be reproducible.

The mixed version — current-state framing with stale line numbers, or a mixture of historical and
current severities — is worse than either, because everything looks authoritative and some of it is
wrong. If the user asks for current-state, the citation rebase is mandatory, not optional.

## 3. Rebase the citations

```bash
python scripts/verify_citations.py report.md --repo . --from-commit <old> --write
```

This anchors each citation to its line *content* at the old commit and finds that content in the
current file. Typical outcome on a few hundred commits of drift: about half already correct, about
half moved by a handful of lines, and a small group whose anchor content no longer exists.

**That last group is the interesting one.** The content is gone because the code was edited or
moved — which often means the finding was fixed. Re-resolve each by symbol:

```bash
rg -n "class ExaminationView|def generate_presigned_url" --glob '*.py'
```

Watch for whole files relocating. When code moves into a new app or module, the citation is not just
off by a few lines — it names a file that no longer contains the code at all, which is the version
of staleness most likely to make a reader dismiss the finding.

## 4. Re-verify each prior finding

For every finding in the old report, read the code at HEAD and classify:

- **Still open** — unchanged, or changed in ways that do not close it
- **Fixed** — the control is now present; verify by reading it, not by seeing a plausible commit
  message
- **Partially fixed** — some of it closed. This needs care; see below.

Do not take a commit message as evidence. "fix: scope examinations to club" tells you someone
intended a fix, not that the endpoint is now safe.

## 5. The bundling trap

When a finding covers several related bugs and only some get fixed, the heading reads as resolved
while live bugs sit underneath it. This is the most likely way for a real vulnerability to be
silently closed during an incremental update.

Split it. Give the unfixed part its own number and its own entry, and cross-link. If numbering is
already in use elsewhere, append the new finding at the end rather than renumbering — renumbering
breaks every cross-reference in the document.

For a finding that is genuinely partially fixed and stays as one entry, state both halves
explicitly: what is already in place, and what specifically remains. Phrase it forward-looking —
"the amount binding is still missing" — rather than as a status timestamp.

## 6. Remove fixed findings, then recount

Fixed findings come out of the active list and out of every count. If continuity matters to the
user, a one-line note is enough; a whole section of audit history is not what a remediation owner
needs.

Removing findings usually leaves gaps in the numbering. Either renumber and remap every
cross-reference, or keep the gaps — but if you renumber, do it programmatically and check:

```bash
python scripts/check_counts.py report.md     # catches gaps, duplicates, and stale totals
```

Watch for cross-references in prose ("finding 19's brute-force oracle"), in anchors
(`[finding 26](#26-...)`), and in `**#12**` style references. All three need remapping.

## 7. Scan for what is new

The diff is the obvious place, but it is not sufficient — a new finding can appear in untouched code
because something *else* changed: a new caller reaching an old unguarded view, a permission class
removed from a parent, a new field added to a `fields = "__all__"` serializer.

Run the full sweep. Use the diff to prioritise, not to scope.

## 8. Final reconciliation

```bash
python scripts/check_counts.py report.md
python scripts/verify_citations.py report.md --repo . --prefix <prefix>
python scripts/render_html.py report.md report.html
```

Then re-read the front matter specifically. Prose counts ("21 of 49 findings", "all 3 Criticals")
are not checked by the scripts and are where stale numbers survive longest — every promotion or
removal can invalidate a sentence that no table covers.
