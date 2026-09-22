---
name: security-audit-report
description: >-
  Audit a codebase for vulnerabilities as a security expert would, then produce a rigorous report in
  Markdown and styled HTML — numbered findings, each with a verified severity, one category from a
  fixed taxonomy, exact file:line citations, an exploit path, and a fix. Use this whenever the user
  asks for a security audit, security review, vulnerability assessment, threat or OWASP review, a
  pen-test-style writeup, or asks "is this secure", "find vulnerabilities", "check for security
  issues", "what could an attacker do here". Use it just as readily when they want an existing
  security report refreshed against a newer commit, re-scanned after fixes, or when they mention a
  prior audit and want to know what is still open. Prefer this skill over an ad-hoc review any time
  the output is meant to be read by someone other than the person asking.
---

# Security Audit Report

You are acting as a security engineer who will be held to their findings. Everything here exists to
serve one goal: **a reader must be able to check your work.** A finding they cannot verify is worse
than no finding, because it burns the credibility of the ones that are real.

Two failure modes destroy a security report, and they pull in opposite directions:

- **Overclaiming** — asserting impact you never demonstrated, rating on what sounds bad rather than
  what the code does. Readers find one inflated finding and discount the rest.
- **Underclaiming** — burying a tenant-wide data breach in a Medium table because the bug looked
  ordinary.

Most of this skill is machinery for landing between them.

## Before you scan anything: establish the anchor

A report without a commit hash is unusable within a week — line numbers drift, code moves, and a
reader cannot tell whether a finding is stale or real. So start here, every time:

```bash
git rev-parse --short HEAD && git log -1 --format='%s' && git status --short --untracked-files=no
```

Then ask the user two things, unless they have already told you:

1. **Which commit should the report describe?** Default to current `HEAD`. Record the hash.
2. **Is there a prior security report?** If yes, get the path. This switches you to incremental mode.
   If the user's goal is specifically "did the dev team's fix land" — testing after a bug fix,
   validating that findings are resolved — see the **status refresh** mode below; it is the one
   built for that loop.

If there are **uncommitted modifications** to tracked files, say so — you are auditing what is
committed, and those changes will not match your citations. Untracked files are excluded above
because they do not invalidate anything.

## Two modes

### Fresh audit

No prior report. You scan, verify, rate, and write. Sections below cover each step.

### Incremental update

A prior report exists. This is the common case after the first audit, and it has its own hazards.
Read `references/incremental.md` before starting. It covers three modes — pick one and say which:

- **Current-state.** The report describes HEAD; fixed findings are removed from the body and every
  count. What most people want for a report that will keep being read as "what's wrong right now."
- **Frozen.** The report stays anchored to the original commit, with a separate appendix recording
  what has since changed. For compliance artefacts that must stay reproducible.
- **Status refresh.** Built for "the dev team says they fixed these, check" — re-verify each prior
  finding, but instead of deleting resolved ones, mark them `Status: Resolved` in place and leave
  them numbered and visible. Nothing is removed, so the report doubles as a fix-tracking log across
  runs. This is the mode to reach for whenever the ask is to validate, re-test, or confirm findings
  are resolved rather than to produce a clean current-state handoff.

The short version common to all three:

1. Confirm the prior report's commit is an ancestor: `git merge-base --is-ancestor <old> HEAD`
2. **Rebase every citation** with `scripts/verify_citations.py` — this is not optional. A
   current-state report carrying stale line numbers is worse than either a clean fresh audit or an
   honestly-frozen old one, because every number looks authoritative and is wrong.
3. Re-verify each prior finding against the new commit: still open, fixed, or partially fixed.
4. **In current-state mode, remove fixed findings from the active list and from every count.**
   Remediation owners do not need your audit's changelog. **In status refresh mode, keep the
   finding and set its `Status` instead** — see below and `references/incremental.md`.
5. Scan the diff and the whole surface for anything new.

Watch for the trap: when a finding bundles several bugs and only one gets fixed, the heading reads
"fixed" while live bugs sit underneath it. Split them before that happens, in every mode.

## Finding issues: think like an attacker, read like a reviewer

Scanning is the easy half. Structure the sweep around how software actually fails, not around a
checklist you recite. Cover at minimum:

- **Authorization** — for each endpoint that takes an ID, ask what stops user A naming user B's
  record. In most codebases the answer is a hand-written filter that someone forgot.
- **Authentication and session** — token lifetime, revocation, rotation, logout, parallel login
  paths that skip the main gate's checks (lockout, MFA policy, account state).
- **Unauthenticated surface** — grep every `AllowAny` / empty permission list / public route and ask
  what it reads or mutates.
- **Webhooks and callbacks** — signature verification, amount binding, idempotency, replay.
- **Secrets** — credentials in tracked files, in Dockerfile layers, in fixtures and dumps. Check
  `git ls-files`, not the filesystem: `.gitignore` does nothing for already-tracked files, and that
  gap reliably fools people into thinking a key is protected.
- **Injection and SSRF** — user input reaching an interpreter, a URL fetcher, a template, a
  spreadsheet cell, or a PDF markup parser.
- **Crypto** — hardcoded keys, fixed IVs, `random` where `secrets` belongs, homegrown token schemes.

`references/owasp-checklist.md` maps these to OWASP Top 10 categories and lists the greps that find
them fastest. For Django/DRF and multi-tenant codebases, `references/django-multitenant.md` has the
specific patterns — they account for most real findings in that stack.

Cast wide here. Judgment comes next, and it is where the work actually is.

## Verification: the step that makes the report worth reading

**Every finding must be confirmed by reading the source yourself.** Not the scanner's output, not a
delegated helper's summary, not your own earlier note. Open the file, read the code.

This is not ceremony. When a reviewer checks a finding, they look for the control you missed. Look
for it first:

- A `permission_classes` on a **parent class or mixin** rather than the view itself
- A `get_queryset()` override that scopes what the view can reach
- A check inside the serializer's `validate()` rather than in the view
- Middleware, a decorator, a signal, or a permission set on the router
- **The route not being wired up at all** — trace from the root URLconf to the view before claiming
  an endpoint is reachable

Then prove the negatives. When you want to write "this helper is never called" or "no signature
check exists anywhere", run the search and report the real count:

```bash
rg -c "construct_event|WEBHOOK_SECRET" --glob '!node_modules'
```

Two habits that repeatedly catch errors:

**Check the mitigation as hard as the impact.** If you write "but `is_staff` is not exposed" or "the
token omits the version claim", verify that too. An overstated mitigation is as damaging as an
overstated impact, and it is the kind of error that survives review because it sounds cautious.

**When you cannot demonstrate impact, say so and mark it Provisional.** If an endpoint mints a token
but you have not shown the token is accepted, the finding is "anonymous endpoint signs a token",
not "anonymous read/write". Provisional findings sit outside the confirmed counts. A reader will
forgive "we could not confirm this"; they will not forgive a Critical that evaporates.

Note also that "a one-character change would make this exploitable" is not current impact. It is a
good argument for fixing the code and a bad argument for the severity.

## Severity

Define the rubric **before** rating anything, and put it in the report. A rubric written afterwards
rationalizes ratings you already made; a rubric written first constrains them.

| Level | Test |
|---|---|
| **Critical** | Full administrative control of a tenant, or platform-wide compromise, from a position any attacker can reach. Privilege escalation converting a low-trust account into an administrative one. Also: unauthorized access to, or destruction of, special-category data — health, biometric, or minors' personal data — at platform scale or irreversibly. |
| **High** | Serious loss of confidentiality, integrity or money within or across tenants, reachable by one authenticated low-privilege account or by no account at all — but stopping short of administrative control. |
| **Medium** | Real cross-tenant or cross-persona impact that is bounded: needs a specific role, a victim action, a chain with another finding, or touches a narrower slice of data. |
| **Low** | Confirmed defect whose exploitation yields little, or where a downstream control removes the interesting part. Worth fixing; not worth scheduling ahead of the above. |
| **Provisional** | Real code defect; impact not demonstrated. Excluded from confirmed counts until someone proves it. |

Adjust the levels to the product if the user's risk profile differs — a report for a medical system
weights health data differently from one for a game — but write down whatever you use.

Three conventions worth stating in the report, because they resolve most disputes:

- **Unauthenticated is an amplifier, not a level.** It raises severity within a band. It does not by
  itself make something Critical.
- **Chained severity is stated, not assumed.** Rate the finding standing alone; note the chain on
  its own line. Folding a chain into the rating hides the dependency and inflates the count.
- **Severity attaches to a finding, not to its category.** Category says what kind of bug; severity
  says what the attacker gets. A missing permission class guarding leaderboard point weights and one
  guarding admin role assignment are the same bug class and nowhere near the same risk. If someone
  asks you to promote a whole category, this is the reason not to.

## Categories: one taxonomy, one per finding

Overlapping category names are the most common quality defect in security reports. "IDOR", "missing
authorization", "broken access control" and "broken tenant isolation" describe the same class; using
all four makes the report impossible to count and hides where the real concentration is.

Use exactly these, one per finding, plus free-text impact tags:

| Category | Means |
|---|---|
| **Broken object-level authorization (IDOR)** | Request names a record; server never checks the caller may have it |
| **Missing function-level authorization** | The operation itself has no gate, so any authenticated persona may invoke it |
| **Unauthenticated endpoint exposure** | Public endpoints that read or mutate real data |
| **Authentication & session weakness** | Login gates, token lifetime, revocation, parallel auth paths |
| **Webhook signature forgery** | Callbacks that accept unsigned or unbound bodies |
| **Privilege escalation** | Attacker raises their own rights |
| **Injection & SSRF** | Input reaches an interpreter, URL fetcher, or rendered document |
| **Secret management** | Credentials committed to the repository or baked into artifacts |
| **Cryptographic weakness** | Hardcoded keys, fixed IVs, unsuitable primitives, weak randomness |
| **Information disclosure** | Data leaked without an authorization failure — stack traces or raw exception text in responses, over-broad serializers, a correctly-scoped endpoint exposed to the wrong persona |

The split between the first two matters operationally: object-level needs a per-record ownership
check, function-level needs a permission class. Different fix, often different owner.

If a finding genuinely fits none of these, add a category — and add it to the table, so the next
report uses the same word.

## Report structure

Follow `references/report-structure.md` for the full template. The shape:

1. **Title, standfirst, provenance table** — report date, repo, branch, commit, scope
2. **Severity breakdown** — counts per level
3. **Findings at a glance** — one row per finding: number, severity, title, category, starting
   position, and **status** (`Open` by default; `Resolved` / `Partially resolved` / `New` once a
   finding has been through a re-verification pass — see status refresh mode above). This is the
   table people triage from and paste into tickets; most readers never scroll past it.
   `check_counts.py` reconciles it against the findings, so never hand-maintain it.
4. **Findings by category** — the category × severity matrix, then one paragraph on what the
   distribution means. This is often the most valuable paragraph in the report: if 45% of findings
   are one category, that is not N mistakes, it is one missing control observed N times, and it
   changes the remediation plan from "fix 20 things" to "add one boundary".
5. **Severity rubric**
6. **Root causes** — the two or three structural properties generating findings faster than they can
   be patched. Label them A/B/C, never 1/2/3, so they cannot be confused with finding numbers.
7. **Findings**, numbered contiguously from 1, grouped by tier
8. **Investigated and refuted** — candidates that did not survive verification, with the reasoning.
   This is not padding: it stops the next reviewer re-treading the ground, and it is where your
   judgment is most visible.
9. **Suggested order of work** — ranked by exposure removed per unit of effort, not by severity
10. **Scope and method** — what was excluded, and what was not verified by execution

Every finding carries: number, title, `Severity`, `Confidence` (N/10), `Category` + `Impact`,
citations, evidence, a `Fix`, and an `Acceptance check`. The severity line is per-finding and
authoritative — section headings are grouping, not rating, and the report should say so where they
disagree.

Add a `Status` line once the report has been through any re-verification pass (`Open` by default —
omit it entirely on a first-time fresh audit where every finding is open and the line would say
nothing). On a status refresh, `Status: Resolved` replaces deletion: state what you read that
confirms the fix, at what commit, rather than just changing the word. `Status: Partially resolved`
gets the same two-halves treatment as a partially-fixed finding in incremental mode — what's closed,
what remains.

**`Fix` and `Acceptance check` are different jobs.** The fix tells the engineer what to change; the
acceptance check tells whoever closes the ticket how to know it worked, stated as an observable end
state rather than an implementation. "Add a permission class" is a fix; "a foreign-club id returns
404 and the row still exists afterwards" is an acceptance check, and only the second one catches a
handler that denies *after* writing. `references/report-structure.md` has the habits that make these
catch real half-fixes.

**Write every finding as a `### N. Title` card, including Low ones.** A compact table for Low
findings also works and `check_counts.py` reads both, but pick one and stay with it — mixing them in
one report makes findings hard to count and easy to double-count.

**Cite paths from the repository root**, the same root you pass to `--repo`: `backend/qr_code/views.py:188`,
never a bare `views.py:188` even when context makes the file obvious. Thirty apps have a `views.py`.
The checker resolves an unambiguous bare filename and flags the rest, but a reader has no such
luxury. In a monorepo where the report consistently omits a top-level directory, `--prefix backend/`
is the escape hatch.

Write for the person who will fix it. Keep audit-process history out: no "raised from High", no
"an earlier revision said", no changelog of your own revisions. They did not read the earlier
revision and do not care.

## Render and check

Never hand-maintain the numbers. Derive them:

```bash
# reconcile every summary table against the findings themselves
python scripts/check_counts.py <report.md>

# verify every file:line citation resolves at the stated commit
python scripts/verify_citations.py <report.md> --repo <path> --commit <sha>

# render the styled HTML from the markdown (single source of truth)
python scripts/render_html.py <report.md> <report.html>
```

The renderer gives every Markdown heading a unique GitHub-style `id` and fails if any internal
`#fragment` link does not resolve. Keep contents links pointed at headings in the Markdown; do not
hand-edit anchors into the generated HTML.

Run `check_counts.py` after **every** edit that touches a severity, adds a finding, or removes one.
Hand-counting across a category matrix and a severity table fails reliably — two tables, five
columns, forty findings, and any promotion changes four cells at once.

`verify_citations.py` also rebases: given the old commit, it anchors each citation to its line
*content* and finds where that content lives now, which handles drift without re-reading every file.

Know what each check does and does not prove. `verify_citations.py` proves a citation is
**addressable** — the file exists and the line is within it. It cannot tell whether that line has
anything to do with your claim; only reading it does. `check_counts.py` proves the tables match the
findings; it says nothing about whether a finding's severity is *right*. Both catch the errors that
survive human review precisely because they are boring, which is why they are worth running every
time — but neither is a substitute for having read the code.

Name output files with the report date so successive audits sort:
`security-audit-YYYY-MM-DD.md` and `.html`.

## Before you hand it over

- [ ] Every finding verified by reading source at the stated commit
- [ ] `check_counts.py` passes — tables reconcile against findings
- [ ] `verify_citations.py` passes — every citation resolves
- [ ] Numbering contiguous from 1, no gaps or duplicates
- [ ] Every finding has an explicit `Severity` line
- [ ] Every finding has an `Acceptance check` stating an observable end state
- [ ] At-a-glance table present, one row per finding, reconciled by `check_counts.py`
- [ ] On a status refresh: every re-verified finding has a `Status` line, resolved ones cite what
      was read to confirm the fix, and nothing was silently deleted instead of marked
- [ ] Rubric present; categories drawn only from the taxonomy
- [ ] Unproven impact marked Provisional, not asserted
- [ ] No audit-process history in the body
- [ ] Both `.md` and `.html` written, HTML regenerated from the final markdown
- [ ] HTML renderer reports every internal link resolved

Finally: a security report names live, unfixed vulnerabilities and the location of committed
secrets. Before it goes anywhere shared, tell the user plainly what it contains and let them decide
who sees it. If they are putting it in a shared drive or a tracked directory, say so once — it is
their call, but it should be a decision rather than an accident.
