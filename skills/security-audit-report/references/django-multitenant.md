# Django / DRF and multi-tenant codebases

Patterns that account for most real findings in Django REST Framework applications, especially
ones where tenancy is enforced by hand. Read this when the target uses Django, DRF, or any
framework where a tenant boundary is applied per-view rather than by the ORM.

## Start here: what is the default permission?

```bash
rg -n "DEFAULT_PERMISSION_CLASSES" -A3
```

`IsAuthenticated` as the default is the single highest-leverage fact in a DRF audit. It means a
view that omits `permission_classes` is not closed — it is open to **every account on the
platform**. In products whose user population includes low-trust personas (customers, players,
parents, patients), forgetting a permission class silently publishes the endpoint to them.

This makes omission invisible in code review: the diff shows a view with no permission line, which
looks like every other view, and nothing fails.

Sweep per view, not per file. One view in a file that sets `permission_classes` hides every
sibling in that file that doesn't:

```bash
# Each view class / @api_view function with no permission_classes of its own -- each is a candidate
python - <<'EOF'
import ast, pathlib
for p in pathlib.Path(".").rglob("*.py"):
    if {"migrations", "node_modules", ".venv"} & set(p.parts):
        continue
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        continue
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and any(("View" in ast.unparse(b)) for b in n.bases):
            names = {t.id for s in n.body if isinstance(s, ast.Assign) for t in s.targets if isinstance(t, ast.Name)}
            if "permission_classes" not in names:
                print(f"{p}:{n.lineno} {n.name}")
        elif isinstance(n, ast.FunctionDef):
            decs = [ast.unparse(d) for d in n.decorator_list]
            if any(d.startswith("api_view") for d in decs) and not any(d.startswith("permission_classes") for d in decs):
                print(f"{p}:{n.lineno} {n.name}")
EOF
```

A class that inherits `permission_classes` from a base or mixin also appears in this list. Check
its bases before you call it a finding.

## Is there a real tenant boundary, or is every filter hand-written?

Check all three places a boundary could live:

```bash
rg -n "DATABASE_ROUTERS" ; rg -n "class .*Manager\(models\.Manager\)" ; rg -n "^MIDDLEWARE" -A25
```

If there is no router, no scoped default manager, and no tenant middleware, then **every** tenant
filter is written by hand in every view, and the audit's job is to find the ones that were
forgotten. Expect the finding count in the authorization categories to dominate.

Beware middleware that *mentions* tenancy without enforcing it — a subscription check or a
per-tenant storage router looks like a boundary in the stack listing and is not one. Read what it
does before crediting it.

## The `?id=` sweep

The highest-yield single sweep in a multi-tenant Django app:

```bash
rg -n "objects\.get\(\s*(pk|id)\s*=\s*request\.(GET|data|query_params)" --glob '*.py'
rg -n "objects\.get\(id=.*kwargs" --glob '*.py'
```

Each hit is a candidate IDOR. For each, ask: after this line, is there any check that the caller may
have this object? Look for an object-level helper — `user_can_access_x(request, obj)` — and check
whether it is imported in that file at all:

```bash
rg -c "user_can_access" path/to/views.py
```

A helper that exists, is correct, and is called in one file while a sibling file with twenty
endpoints never imports it is a strong, easily-evidenced finding.

## Persona filters are not tenant filters

Codebases often have a function that narrows a queryset by the requester's role — coach sees their
team, parent sees their children. Two traps:

- It may not add a **club/tenant** filter at all. Verify by reading it, not by its name.
- It usually has per-model branches and **returns its input unchanged for unhandled models or
  unhandled personas**. That silent passthrough is the bug: a new model added later gets no
  filtering and nothing errors.

Also check whether an admin-ish persona has *no* branch — often that means the filter stops
narrowing entirely for anyone holding that role, which converts a role assignment into a data breach.

## Serializers

```bash
rg -n 'fields\s*=\s*"__all__"' --glob '*.py'
```

`fields = "__all__"` on a model with sensitive columns exposes them all, and on write it makes every
field assignable. Check specifically whether `password`, `is_active`, `is_staff`, a role/type FK, or
a tenant FK are writable — mass assignment on any of those is escalation.

`PrimaryKeyRelatedField` without a scoped queryset lets a caller attach a foreign tenant's object to
their own record. `ModelSerializer.update()` not being overridden while `create()` is, is a common
source of accidental M2M `.set()` behaviour that silently removes other members.

## Webhooks

```bash
rg -n "AllowAny|permission_classes\s*=\s*\[\]" --glob '*view*.py'
rg -n "hmac|compare_digest|construct_event|WEBHOOK_SECRET" --glob '*.py'
```

When a codebase has several payment callbacks, check each one separately — it is common for one to
be implemented correctly and the others to have been written by copying an earlier, unsafe version.
A correct handler verifies the signature *before any mutation*, binds the amount to the expected
order total, takes a row lock, and returns early when already processed.

Note the difference between an **unsigned** callback (anyone can forge state changes) and a signed
one **missing amount binding or idempotency** (needs a genuine signed body first, so it is a real
but much narrower defect). Rating those the same overstates the second.

## Authentication

```bash
rg -n "SIMPLE_JWT" -A20
rg -n "class .*Login|TokenObtainPair" --glob '*.py'
```

- **Token lifetime** measured in hundreds of days, no rotation, no blacklist app installed, and no
  logout endpoint together mean a leaked token is effectively permanent. `BLACKLIST_AFTER_ROTATION`
  is inert unless `rest_framework_simplejwt.token_blacklist` is in `INSTALLED_APPS` — check, because
  the setting reads as protection.
- **Parallel login paths** are a recurring finding: a second endpoint (QR login, SSO shim, legacy
  OTP verify) that authenticates by hand and issues the same tokens while skipping the main gate's
  lockout counter, OTP policy, and account-state checks. The lockout omission is usually the real
  impact — it turns the endpoint into an unlimited password-guessing oracle while the front door
  locks out.
- **Custom revocation claims** (a token-version field) only work where they are checked. Websocket
  middleware that instantiates base `JWTAuthentication` instead of the project's subclass silently
  skips them.

## Secrets

Check tracking, not the filesystem — `.gitignore` has no effect on already-tracked files, and that
gap reliably convinces people a key is protected when it ships in every clone:

```bash
git ls-files | rg -i "credential|secret|\.pem$|adminsdk|dump\.json|\.env$"
rg -n "BEGIN (RSA |EC )?PRIVATE KEY" $(git ls-files)
rg -n "http-basic|--password|PAT|token" Dockerfile*
```

A credential in a Dockerfile `RUN` line is in the image layer and in `docker history`, not just the
repo. Report the class and location; never paste the secret value into the report.

## SSRF

```bash
rg -n "requests\.(get|post)\(" --glob '*.py' -A2
```

Look for a caller-supplied URL with no scheme allowlist, no host/IP validation, redirects followed,
and no timeout. Whether it is *blind* matters for severity: if the response body is returned to the
caller (saved and re-serialised, or echoed), it is full-read SSRF and much worse. Check the cloud
metadata endpoint for the actual deployment target — some require a header an attacker cannot set,
some do not, and that distinction decides the rating.
