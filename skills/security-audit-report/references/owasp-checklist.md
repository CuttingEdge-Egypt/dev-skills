# OWASP coverage and the greps that find each class

A sweep structured around how software actually fails, mapped to OWASP Top 10 (2021) so the report
can speak the language a security reviewer expects. The greps are starting points — every hit still
needs reading, and the absence of a hit is not evidence of absence.

Language-agnostic where possible; Django/DRF specifics live in `django-multitenant.md`.

## A01 Broken Access Control

The largest category in almost every application audit. Splits into two findings categories with
different fixes:

**Object-level (IDOR)** — request names a record, server never checks ownership.

```bash
rg -n "objects\.get\(|findById|findOne\(|SELECT .* WHERE id" -g '!test*'
rg -n "req\.(params|query|body)\.\w*id" --glob '*.{js,ts}'
```

For each: is there an ownership or tenant check after the lookup? Are IDs sequential integers
(enumerable) or unguessable UUIDs? Sequential IDs turn a single-record bug into a full-database
bug and belong in the severity reasoning.

**Function-level** — the operation has no gate at all.

```bash
rg -L "permission|authorize|requireAuth|@PreAuthorize" --glob '*controller*'
```

Also check: does an admin UI enforce access only in the frontend? A frontend-only gate is not a
control; say so explicitly, since teams often believe it is one.

## A02 Cryptographic Failures

```bash
rg -n "AES|DES|ECB|MD5|sha1\(|Random\(\)|math/rand|random\.(randint|choice)"
rg -n "BEGIN (RSA |EC )?PRIVATE KEY" $(git ls-files)
```

Look for hardcoded keys and **fixed IVs** — a constant IV makes encryption deterministic, which
turns "encrypted ID" schemes into forgeable capability tokens anyone with the source can mint.

`random` instead of `secrets`/`crypto` for tokens or passwords is a genuine defect, but be honest
about exploitability: predicting a Mersenne Twister stream needs many consecutive known outputs from
the same process. Report it as hygiene unless you can show the preconditions hold.

## A03 Injection

```bash
rg -n "raw\(|execute\(|cursor\.execute|\.query\(|eval\(|exec\(|dangerouslySetInnerHTML|innerHTML"
rg -n "f\"SELECT|\" \+ .* \+ \"|%s.*%.*\(" --glob '*.py'
```

Beyond SQL, check the injection targets people forget:

- **Spreadsheet formulas** — a cell beginning `=` becomes a live formula. Verify against the pinned
  library whether it is written as a formula type or as text; the answer differs by library and
  version and decides whether this is Medium or noise.
- **Document markup** — PDF/report generators with their own markup language. Incomplete escaping
  (escaping `&` but not `<`) can make the generator fetch a URL during rendering.
- **Query/filter DSLs** — search and RAG filter expressions built by string interpolation. If a
  sanitiser strips operators by *argument name*, check every argument that reaches the expression.

## A04 Insecure Design

Not a grep — a reading. The question is whether a control is missing by construction rather than by
accident. Examples worth stating as root causes: no tenant boundary in the data layer; notification
delivery over a channel with no subscription authorisation; a capability token with no expiry or
revocation.

## A05 Security Misconfiguration

```bash
rg -n "DEBUG\s*=\s*True|ALLOWED_HOSTS|CORS_ALLOW_ALL|cors\(\)" 
rg -n "DEFAULT_PERMISSION_CLASSES|AUTHENTICATION_CLASSES" -A3
```

Defaults matter more than individual settings: a permissive default permission class means every
forgotten decorator is an open door, and that belongs in the root-cause section rather than as a
finding.

## A06 Vulnerable Components

Usually out of scope for a code audit — say so in Scope and method rather than half-covering it. If
in scope, use the ecosystem's own tooling (`pip-audit`, `npm audit`, `govulncheck`) and treat the
output as a separate appendix.

## A07 Identification and Authentication Failures

```bash
rg -n "TOKEN_LIFETIME|expiresIn|jwt\.sign|SECRET_KEY"
rg -n "class .*Login|/login|signin|authenticate\("
```

Check for parallel authentication paths — a second endpoint that issues the same credentials while
skipping the main gate's lockout, MFA policy and account-state checks. Also check that any custom
revocation mechanism is enforced on *every* surface, including websockets and background consumers.

Absence of lockout is worth distinguishing from absence of rate limiting: if the product has a
lockout and one endpoint bypasses it, that is an authorization bug in the bypass, not a missing
control.

## A08 Software and Data Integrity Failures

```bash
rg -n "pickle\.loads|yaml\.load\(|Marshal|deserialize"
rg -n "hmac|compare_digest|verify_signature|constructEvent"
```

Webhooks live here. A handler that mutates payment or entitlement state from an unsigned body is
forgeable by anyone who can reach the URL. Check each handler separately — one correct
implementation and three copies of an older unsafe one is a common pattern.

## A09 Logging and Monitoring Failures

Worth a finding only when it hides something specific: an endpoint that bypasses login-history
recording, or a security alert that can be cleared by the attacker. Generic "insufficient logging"
findings add length and no value.

## A10 Server-Side Request Forgery

```bash
rg -n "requests\.get\(|fetch\(|axios\.|urllib\.request|http\.Get" -A2
```

The severity hinges on two things: whether the response is returned to the caller (full-read vs
blind), and what the deployment's metadata endpoint requires. Some cloud metadata services need a
header an attacker cannot set through a simple fetch; others do not. Determine the actual deployment
target before rating.

## Frontend-specific

```bash
rg -n "innerHTML|document\.write|dangerouslySetInnerHTML|v-html" --glob 'src/**'
rg -n "localStorage|sessionStorage" --glob 'src/**'
```

For any `document.write` into a `window.open('')` popup: an empty-URL `about:blank` document
**inherits the opener's origin**, so injected script reaches the app's storage — including tokens.
That origin detail is what separates a real finding from a cosmetic one, so state it explicitly.

Conversely, check where user-uploaded files are served from. If blobs are served from a different
origin than the app, uploaded HTML cannot touch app tokens, and a stored-XSS claim does not hold —
verify the storage domain configuration rather than assuming.
