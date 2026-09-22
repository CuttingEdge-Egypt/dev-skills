# Report structure

The exact shape of the output. Deviating is fine when the target genuinely differs, but each piece
here exists because its absence caused a concrete problem in a real report.

## Front matter

```markdown
# <Product> Security Audit

<One paragraph: what was reviewed, and the single most important structural observation.>

| | |
|---|---|
| **Report date** | **20 September 2026** |
| **Repository** | repo-name |
| **Branch** | `main` |
| **Commit** | **`4942c407`** |
| **Scope** | 30 Django apps and the React SPA |

**Severity breakdown**

| Critical | High | Medium | Low | Provisional | Refuted |
|---:|---:|---:|---:|---:|---:|
| 4 | 19 | 16 | 9 | 1 | 6 |

Critical is findings **1, 8, 9 and 15**. <Name any finding whose severity differs from the
section it sits in, and say why in one clause.>

Findings are numbered **1–49**. The section headings group by tier but a few findings do not match
their heading. **Always read a finding's own Severity line.**
```

The date and commit are not decoration. Without them a reader cannot tell whether a finding is
stale, and the report becomes unusable within a week.

## Findings at a glance

Directly after the severity breakdown, one row per finding — every finding, including the Low ones:

```markdown
## Findings at a glance

"Starting position" is what the attacker needs before they begin.

| # | Severity | Finding | Category | Starting position |
|---:|---|---|---|---|
| 1 | Critical | Profile endpoint sets any account's password and self-promotes to Admin | Privilege escalation | Any authenticated user |
| 2 | Critical | Twenty dashboard endpoints expose any player's dossier via `?player_id=` | IDOR | Any authenticated user |
```

This is the table people triage from, quote in a ticket, and paste into a status update — most
readers never scroll past it. That is exactly why it drifts first and why a stale row here is worse
than a stale row anywhere else: it is wrong in the place most people look. `check_counts.py`
reconciles every row's number and severity against the finding itself, so let it, rather than
re-reading the table by hand.

Keep the finding text short enough to scan — this is an index, not a summary. The starting-position
column is what stops a reader assuming every finding needs an admin account.

### The Status column

Once a report has been through any re-verification pass — see the "status refresh" mode in
`references/incremental.md`, the mode built for "the dev team says they fixed these, check" — add a
`Status` column so triage doesn't require reopening every finding:

```markdown
| # | Severity | Finding | Category | Starting position | Status |
|---:|---|---|---|---|---|
| 1 | Critical | Profile endpoint sets any account's password and self-promotes to Admin | Privilege escalation | Any authenticated user | Resolved |
| 2 | Critical | Twenty dashboard endpoints expose any player's dossier via `?player_id=` | IDOR | Any authenticated user | Open |
| 7 | High | Presigned upload URL omits a content-type check | Injection & SSRF | Any authenticated user | Partially resolved |
```

Four values, applied at the finding level, never at the table level:

- **Open** — the default. A first-time fresh audit can omit the column entirely rather than fill
  every row with a word that says nothing yet.
- **Resolved** — you read the current code and confirmed the control is now in place. A commit
  message claiming a fix is not evidence; see `references/incremental.md` step 4.
- **Partially resolved** — some of the finding is closed, some is not. State both halves in the
  finding body; do not let the row alone imply the whole thing is handled.
- **New** — added in this pass, so a reader scanning a status-refresh report can tell what's freshly
  discovered from what's been carried forward.

The point of keeping resolved rows in the table, rather than deleting them the way current-state
mode does, is that the report becomes a running fix-tracking log across audits — exactly what's
useful when the workflow is "fix a batch, re-run the skill, see what's still open." If the user
wants a clean current-state handoff instead, with fixed findings gone entirely, that is a different
mode — say which one you're producing.

## Findings by category

The category × severity matrix, then — and this is the part people actually quote — one short
paragraph interpreting it:

```markdown
**What the distribution says.** Authorization — the IDOR and missing-function-level rows — is
**21 of 49 findings, 43% of the total, and 2 of the 4 Criticals**. That is not twenty-one teams
making twenty-one mistakes; it is one missing control observed twenty-one times.
```

This reframes the remediation plan from "fix 21 things" to "add one boundary, then sweep". It is
usually the highest-value sentence in the document, and it only exists if the categories are a
single consistent taxonomy — which is why overlapping category names are worth avoiding.

## Root causes

Two or three structural properties that generate findings faster than they can be patched. **Label
them A, B, C — never 1, 2, 3**, because numbered root causes collide with numbered findings and
"finding 3" becomes ambiguous. (This is a real bug that shipped in a real report.)

## A finding

```markdown
### 12. A duplicate player-update view resets any player's password and phone number

- **Severity:** High · **Confidence:** 10/10
- **Category:** Broken object-level authorization (IDOR) · **Impact:** Credential reset
- **Status:** Resolved — `permission_classes` now includes `IsClubMember`; confirmed by reading
  `backend/users/views/general.py:2387` at `a1b2c3d`

```
backend/users/views/general.py:2387   no permission_classes
  :2391 Player.objects.get(pk=pk)     :2401-2420 mobile rewrite
route: users/routers/general.py:421 -> PATCH /user-generals/update-player/<pk>/
```

<Evidence: what the code does, what you read to confirm it, and what you ruled out.>

**Exploit**

1. <Each step mechanically possible against the real code.>

**Fix.** <Specific and actionable. Name the function or the pattern to follow.>

**Acceptance check.** <What must be observably true for this to be closed.>
```

Required on every finding: a number, a `Severity` line, a `Confidence` out of 10, one `Category`
from the taxonomy plus free-text `Impact` tags, repo-relative `file:line` citations, evidence, a
`Fix`, and an `Acceptance check`. Add a `Status` line once any re-verification pass has happened
(see the Status column above); a fresh audit with nothing to re-verify yet can leave it out.

### The acceptance check

`Fix` tells the engineer what to change. `Acceptance check` tells whoever closes the ticket how to
know it worked — which is what makes a finding ticketable rather than merely reported. Write the
**observable end state, not the implementation**:

```markdown
**Acceptance check.** A DELETE naming a foreign-club user id returns 404 and that `AuthUser` row
still exists. After the refusal, the related `Player`, health and examination row counts are
unchanged — assert on the counts, because the failure mode here is a cascade that fires before
the check.
```

Not "add a permission class": that restates the fix and can be satisfied by a class that permits
everything. Three habits make these checks catch real half-fixes:

- **Say what must still be there.** A handler that returns 403 *after* writing passes a status-code
  assertion and fails the finding. Name the rows, files or counters that must be unchanged.
- **Assert on the body, not just the status,** wherever a handler could deny and serialise anyway.
- **Name the personas** when persona scoping is the point — "a Parent's report contains only their
  own children" is checkable; "persona filtering is applied" is not.

For Low findings kept in a table, the acceptance check is a column, one sentence per row.

Low findings may use either table shape; `check_counts.py` reads both, and locates the columns from
the header rather than by position, so an extra column is free:

```markdown
| # | Finding | Category | Location | Assessment | Acceptance check | Status |
| **45** | Two unauthenticated upload endpoints | Unauthenticated endpoint exposure | `core/views.py:3065` | ... | Anonymous POST returns 401. | Open |
```

Use **repo-relative paths** in citations. A bare `views.py:42` is ambiguous across a codebase with
thirty apps, and the citation checker will flag it.

Where a rating depends on combining findings, add a separate line rather than folding it in:

```markdown
- **Chain:** the leaked order IDs are what finding 4 looks up. Treat as High while 4 is unfixed.
```

Where impact is real but unproven, say so in the severity line and exclude it from the counts:

```markdown
- **Severity:** **Provisional** · **Confidence:** 8/10 that the endpoint is anonymous and signs a
  token; **unverified** that the token is accepted. Excluded from the confirmed counts.
```

## Investigated and refuted

A table of candidates that did not survive verification, each with the reasoning. Not padding — it
stops the next reviewer re-treading the same ground, and it is where your judgment is most legible.

Be honest about what a refutation proves. "The same oracle already exists on another endpoint"
shows a bug was not *introduced*; it does not show the bug is absent. If the report claims full
attack-surface coverage, that candidate belongs in Low, not in the refuted table.

## Suggested order of work

Ranked by **exposure removed per unit of effort**, not by severity. The first group is usually
deletions and rotations — an unused endpoint removed, a key rotated — because they close real
exposure in minutes. Deep structural fixes come later even when they address Criticals.

Keep this section synchronised with the findings: a plan that lists already-completed work
undermines the report that told the reader to trust its current status.

## Scope and method

What was excluded and why (denial of service, dependency CVEs, rate limiting, and so on), and what
was **not verified by execution**. If no exploit was run against a live system, say it plainly here
and mark any finding whose rating depends on execution as Provisional.

## Writing for the reader

The audience is whoever will fix these. Keep the audit's own history out of the body: no "raised
from High", no "an earlier revision said", no changelog of your revisions. They did not read the
earlier revision.

The one exception is a *forward-looking* note — "this is the pattern to copy" or "the amount binding
is still missing" — which tells them what to do rather than what you used to think.
