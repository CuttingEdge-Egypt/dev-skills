# Release PR formatting rules

A release PR is read twice: once by a reviewer skimming what ships, and once, line by line, by
whoever deploys it. Both readers need **one thing per line**. Packing several changes into one
line to save space makes the notes harder to scan, and it makes deployment items impossible to tick
off.

## References

- Put references at the **end** of the line, in parentheses: PR references first, then work items,
  with ` · ` between the two groups and `, ` within each group: `(!7997, !7999 · #4004)`.
- Use the platform's own syntax so they autolink:
  - Azure DevOps: PRs `!123`, work items `#456`.
  - GitHub: PRs `#123`; work items as the tracker writes them (`PROJ-12`, `AB#456`).
- Never mix the two styles in one group, and never leave out the separator (`!8010 #4004` is wrong).

## Features, Fixes, Other changes

- **One bullet = one change.** Several PRs that build the *same* feature share one bullet that cites
  all of them. Unrelated changes never share a bullet, even when they're in the same area. Don't join
  them with commas, semicolons or "+".
- If a single feature has several notable parts, use sub-bullets under it, not a comma list:
  ```markdown
  - **EMR cases**: injuries are now tracked as cases (!8001, !8016, !8023, !8008)
    - ICD-10 diagnosis codes and referrals
    - Chronic conditions, priority and attachments
    - New Cases tab on the player profile
  ```
- With more than about 8 items in a section, group them by product area under `###` subheadings
  (`### EMR`, `### Reservations`). Order the areas by impact, and the items within each area too.
- Start each bullet with what changed for the user, not with the PR title or a ticket number.
- **Other changes** are bullets too, one per change. Small related chores may share a bullet
  ("Lint and Docker build cleanup (!8011, !7976)"), but never make the section one paragraph.

## Deployment Notes

- **One action per checkbox.** Each checkbox is one thing a person does and ticks off: one command,
  one role grant, one variable, one backup. Three commands are three checkboxes, in the order to run
  them.
  - ✗ `- [ ] Run load_icd10_catalog --apply, grant_case_access_from_legacy --apply, sync_player_medical_statuses --apply (!8001)`
  - ✓ three checkboxes, one command each, each citing `!8001`.
- Start each item with an imperative verb ("Set", "Run", "Grant", "Back up"). Bold only the
  object when that helps scanning, never the whole line.
- Background a deployer needs in order to do an item right (why it's slow, what it deletes) goes in
  an indented line under that item, not appended to it with semicolons:
  ```markdown
  - [ ] Back up the production database before migrating (!8029, !7959, !8001)
    - `core/0284` deletes `MatchCard`; `reservations/0021` drops `servicecategory.gateway`;
      `core/0276` can't be reversed
  ```
- **Decisions and conflicts** (two PRs disagree on a default, or an item needs a human call) go in
  their own `### ⚠️ Decide before deploying` subsection at the top of Deployment Notes, one per
  bullet. Don't mix them into the action checklists.
- Within each phase, order items by dependency first (what must exist before what), then by risk.
- **Migrations**: give the total as one line, then one checkbox per migration that needs attention
  (slow, locking, irreversible, data backfill), with its reason indented underneath.
- Keep the template's headings exactly as written (`### Before deploying`, not `### Before`) and
  all of its table columns. Delete an empty subsection; don't rename one.
- **PRs with no deployment notes stated**: one bullet per PR with a few words saying what it does,
  so the deployer knows who to ask about what (`- !8026 role-based API authorization`). Add a
  `deploy_hints` line underneath when the script found one.

## What goes in the PR body vs. in chat

Notes about **how the draft was made** go in chat, not in the PR: descriptions that couldn't be
fetched, truncated bodies, script warnings, "the rest are duplicates and merge wrappers". The PR
body says only what ships and what the deploy needs. If information is missing, fix that first
(re-fetch the PRs) or ask the user. Don't leave "read the full PRs" in the deployment notes.

The **Release summary** gives plain facts: how many feature PRs ship, the date range, and the headline
changes in 1–3 sentences. Don't count release/merge wrapper PRs and don't describe them.

## When the body is too long (Azure DevOps: 4,000 characters)

Measure the length (for example `python -c "import sys; print(len(open(sys.argv[1], encoding='utf-8').read()))" body.md`).
Don't estimate it. **Never make it fit by breaking the rules above.** Split it instead:

1. **PR description**: `## Release summary`, a `## Highlights` list (the 5–8 most important
   features, formatted as above), then `## Deployment Notes` in full.
2. **First PR comment** (Azure allows 150,000 characters per comment): starts with
   `# Release <number>: full release notes`, then `## Features`, `## Fixes`, `## Other changes`,
   `## Included PRs`, all in full.
3. If Deployment Notes alone still don't fit, move `### New configuration` and `### PRs with no
   deployment notes stated` into the comment as well. Remove those headings from the description
   entirely; don't leave a heading whose only content is "see the comment". The action checklists
   (Decide / Before / During / After) always stay in the description.

Point to the comment **once**, as a blockquote directly under the Release summary, naming exactly
what moved, so a reader knows before the Highlights that the list is partial:

```markdown
> This description has the highlights and the deployment checklist only, because Azure DevOps
> limits PR descriptions to 4,000 characters. The full feature and fix list, the included PRs, the
> new configuration table and the PRs with no deployment notes are in the first comment below.
```

List only the parts that actually moved. Don't add other "see the comment" lines anywhere else.

Show the user all three blocks (title, description, comment) and tell them that the description was
split and that the comment must be posted too. Without the comment, the pointer leads nowhere.
