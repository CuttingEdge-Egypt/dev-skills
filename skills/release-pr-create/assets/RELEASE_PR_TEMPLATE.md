## Release summary

<!-- 1-3 sentences: what this release delivers, how many PRs, the date span they were merged in. -->

## Features

<!-- One bullet per change, written for someone who didn't read the PR. Never join unrelated changes
     on one line; use sub-bullets for a feature's parts and ### area subheadings past ~8 items.
     End each line with PR refs, then work items: "... (!123, !124 · #45)". See references/formatting.md. -->

## Fixes

## Other changes

<!-- Chores, refactors, dependency bumps, CI, docs. Bullets, not a paragraph; closely related small
     chores may share a bullet. -->

## Deployment Notes

<!-- Checklist for whoever deploys. ONE action per checkbox (one command, one grant, one variable);
     background goes on an indented line under the item. Every item cites the PR it came from. Keep
     only the subsections that have items, with these exact headings; if nothing at all was found,
     write "None — no deployment actions found in the included PRs" and keep the "not stated" list. -->

### ⚠️ Decide before deploying

<!-- conflicts between PRs (different defaults for one setting) and items needing a human call -->

- ...

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

<!-- PRs whose description has no deployment section at all (not the same as "None"). One bullet per
     PR with a few words on what it does, so the deployer can confirm with the author. Put any hint
     lines found elsewhere in the PR on an indented line underneath. -->

## Included PRs

| PR | Title | Author |
|---|---|---|

<!-- Optional sections, only when they apply:
## Reverted in this range   (PR + its revert; neither ships)
## Direct commits           (commits on the source branch with no PR)
-->
