## Release summary

<!-- 1-3 sentences: what this release delivers, how many PRs, the date span they were merged in. -->

## Features

<!-- One line per user-visible feature or improvement, written for someone who didn't read the PR.
     End each line with the PR reference(s) and work-item key if known: "... (#123, PROJ-45)". -->

## Fixes

## Other changes

<!-- Chores, refactors, dependency bumps, CI, docs. Group small items onto one line when it helps. -->

## Deployment Notes

<!-- Checklist for whoever deploys. Every item cites the PR it came from. Keep only the subsections
     that have items; if nothing at all was found, write "None — no deployment actions found in the
     included PRs" and keep the "not stated" list below. -->

### Before deploying

<!-- infra to provision, secrets to add to the vault, env vars / app settings to set, permissions,
     external registrations (redirect URIs, webhooks) -->

- [ ] ...

### During deployment

<!-- migrations, deploy ordering between services, feature flags to flip at deploy time -->

- [ ] ...

### After deploying

<!-- backfills and one-off scripts, role grants, cache flushes, smoke checks called out by PRs -->

- [ ] ...

### New configuration

| Name | Kind | Needed in | PR |
|---|---|---|---|
| `EXAMPLE_VAR` | env var / secret / app setting / feature flag | staging, prod | #123 |

### PRs with no deployment notes stated

<!-- PRs whose description has no deployment section at all (not the same as "None"). List them so
     the deployer can confirm with the author. Include any hint lines found elsewhere in the PR. -->

## Included PRs

| PR | Title | Author |
|---|---|---|

<!-- Optional sections, only when they apply:
## Reverted in this range   (PR + its revert; neither ships)
## Direct commits           (commits on the source branch with no PR)
-->
