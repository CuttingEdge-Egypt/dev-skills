# Built-in review (fallback when no code-review tool is available)

Use this when no code-review skill or tool is installed, or when it can't run (not installed,
not authenticated, no network, or the user declined to send code to an external service). Read the
diff `git diff <merge-base>` and each changed file in full, not just the hunks, because many bugs
only show up next to the unchanged code around them.

Review the way a careful senior teammate would. Only report things you can point to at a
`file:line`, and say why each one matters. Aim for a short list of real problems, not a long list
of style nits. Lint already covers style.

## What to look for, roughly in priority order

1. **Correctness.** Logic errors, off-by-one, wrong conditions, inverted checks, null/undefined
   paths, unhandled promise rejections or missing `await`, mutated shared state, and wrong units or
   types. Also check that the change does what the branch name and commits say it does.
2. **Error handling.** Swallowed exceptions, broad `catch`/`except` that hides failures, errors
   logged but not propagated, and missing cleanup (files, connections, locks).
3. **Security.** Untrusted input reaching SQL, shell, file paths, templates, or redirects.
   Missing authorization checks on new endpoints. Secrets or PII in code or logs. New dependencies
   from unexpected sources.
4. **Breaking changes.** Changed public signatures, API responses, DB schemas, config keys, or event
   payloads without a migration path, and callers of a changed function that weren't updated
   (`git grep` the old name or signature).
5. **Tests.** Is the new behavior covered? Were tests weakened, deleted, or skipped to make them
   pass? Do the assertions actually check the change?
6. **Scope creep.** Changes unrelated to the branch's purpose, such as drive-by refactors, formatting
   churn in untouched code, or a second feature. Suggest splitting them into their own PR.
7. **Maintainability.** Duplicated logic that already exists elsewhere in the repo (search before
   claiming it), misleading names, and magic numbers that deserve a named constant.
8. **Performance**, only where it plausibly matters: N+1 queries, unbounded loops over user input,
   work inside hot paths, and missing pagination.

## Severity

- **Blocker**: will break something, loses data, is a security hole, or fails CI.
- **Warning**: a real risk or a clear quality problem a reviewer would push back on.
- **Info**: a suggestion or nice-to-have. Keep these few.

Label the report section "Code review (built-in, no review tool available)" so the user knows
which path ran and that the review wasn't independent.
