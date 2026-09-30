---
name: release-pr-create
description: >-
  Drafts (and, once approved, opens) a release PR that promotes an integration branch into a
  release branch: dev/develop → staging, staging → main/master, dev → main/master, or into
  production/release/*. It collects every PR merged into the source branch since the last release
  to that target (GitHub or Azure DevOps), reads their titles and descriptions, and writes a feature
  list plus a consolidated deployment checklist covering new env vars and app settings, secrets,
  migrations, infra, permissions, and manual pre/post-deploy steps, each item citing its PR. Use this
  whenever the user asks for a release PR, a promotion or "deploy to staging/prod" PR, a "merge dev
  into main" PR, release notes for what's going out, or "what's shipping in this release and what
  do we need to configure". DO NOT USE for a normal feature/bugfix PR into dev or develop (use
  pr-create), or for readiness checks on a branch (use pr-prep).
---

# Release PR create

A release PR bundles many already-reviewed PRs. Reviewers don't need another diff summary. They
need to know **what ships** and **what the deploy will require**. Deployment details are scattered
across a dozen PR descriptions, and missing one (a secret nobody added to the vault, a migration
run out of order) causes outages. This skill collects them into one checklist in which every item
traces back to its PR.

## 0. Confirm this is a release PR

The **target** must be a release branch: `staging`/`stage`/`uat`, `main`/`master`,
`production`/`prod`, or `release/*`. The **source** is a long-lived integration branch (`dev`,
`develop`, or `staging` when promoting on to `main`). If the user actually wants a feature branch
merged into `dev`/`develop`, stop and use the pr-create skill instead, because this workflow would
list unrelated PRs.

## 1. Determine source and target

- **Target**: whatever the user names. If they say "prod" or "release", map it to the repo's actual
  branch (`git branch -r`). Ask if it's still unclear.
- **Source**: branch flows differ between repos, so work it out rather than assuming:
  1. If an **open PR into the target** from a long-lived branch already exists (`gh pr list --base
     <target> --state open`, or `az repos pr list --target-branch <target> --status active`), its
     source is the answer. Offer to **update that PR's description** instead of opening a second one.
  2. Otherwise, check which PRs were previously merged into the target (the same commands with
     merged/completed status). If past `→ main` releases came from `staging`, the source is `staging`.
  3. Otherwise, for a `staging` target, the source is `dev`/`develop`. For `main`/`master`, use
     `staging` if it exists and has commits `main` lacks, otherwise `dev`/`develop`.
  4. If more than one answer is still plausible, ask. Releasing the wrong branch ships the wrong
     code, so it's worth one question.
- `git fetch <remote> <source> <target>` first. Local branches are often stale, and a stale target
  makes already-released PRs look new.

## 2. Collect the PRs

```bash
python scripts/collect_prs.py --target <target> --source <source> --out <tmp>/release-prs.json
```

Write the JSON somewhere **outside the repo** (a temp dir) so it can't be committed. The script's
docstring documents every field. In summary, it:

- finds the **boundary** (the last release). It uses the head commit of the last completed
  source→target PR from the platform, or an offline match of a squash-merged release commit, or
  plain `target..source`. `boundary_method` says which one was used. `--since <tag|sha>` overrides
  it when the user knows better.
- extracts PR numbers from merge and squash commit messages (GitHub, Azure DevOps, GitLab styles).
  On GitHub it also looks up commits that have no PR number.
- fetches each PR with `gh` or `az repos` and splits its description into sections. `deployment`
  holds the deployment-ish sections, `deployment_stated` and `deployment_is_none` say whether a
  deployment section exists and whether it just says "None". `deploy_hints` are lines elsewhere in
  the description that mention env vars, secrets, migrations, infra, or manual steps.
- separates `release_prs` (earlier release PRs inside the range, e.g. a dev→staging release within
  a staging→main promotion) and `direct_commits` (commits that belong to no PR).

**Read `warnings` before anything else.** Each one changes how much you can trust the rest:
- *CLI not found / could not fetch*: titles come from commit subjects and bodies are empty. Get the
  descriptions another way: a GitHub or Azure DevOps connector if your environment has one, the web
  UI, or by asking the user. Don't write deployment notes from commit subjects alone and present
  them as complete.
- *Large range / fell back to `target..source`*: if the repo squash-merges releases, the range may
  include PRs that already shipped. Check the oldest PRs' merge dates against the last release. If
  in doubt, ask for the last release tag or commit and re-run with `--since`.
- *Earlier release PRs inside the range*: their feature PRs usually appear in `prs` too (merge
  commits keep them). If they don't, because that release was squash-merged, read the release PR's
  own description (it's in `release_prs[].body`) for the list of PRs it shipped and fetch those.

## 3. Build the feature list

- Classify each PR as **Features**, **Fixes**, or **Other changes** (chores, refactors, deps, CI,
  docs). Use conventional-commit prefixes (`feat:`, `fix:`), labels, and branch prefixes
  (`feature/`, `bugfix/`, `hotfix/`, `chore/`), then read the content when those disagree.
- Rewrite each item as one line a stakeholder understands ("Customers can apply discount codes at
  checkout"), not the raw PR title. Keep the PR reference and any work-item key found in the
  title, branch, or body, in whatever form the repo uses (`PROJ-12`, `AB#123`, `#45`).
- **Reverts**: when a PR and its revert are both in the range, neither ships. Drop both from the
  lists and mention them under "Reverted in this range". Otherwise the release notes announce a
  feature that isn't there.
- **Direct commits**: list them briefly. They shipped without review, which the reviewer should know.

## 4. Consolidate deployment notes

This is the most valuable part, so be thorough and stick to what the PRs actually say.

- Go through every PR's `deployment` sections **and** its `deploy_hints`. Put each action into the
  template's phases: **before deploying** (provision infra, add secrets, set env vars and app
  settings, permissions, external registrations), **during** (migrations, ordering between services,
  flags flipped at deploy time), and **after** (backfills, one-off scripts, role grants, smoke checks
  the PR asks for).
- Write each item as a checkbox action that names the PR: `- [ ] Add secret SMTP_PASSWORD to the
  key vault in each environment (#13)`. Keep exact names (variables, buckets, scripts, migrations)
  in backticks, spelled exactly as the PR wrote them.
- Fill the **New configuration** table with every env var, app setting, secret, and feature flag.
  One row per name: if two PRs touch the same name, merge them into one row with both PR numbers,
  and point out any conflict (for example, different default values).
- **Secret values**: if a PR description contains an actual credential and not just its name, never
  copy it. Write the name only, and tell the user in chat that the value is in PR #N's description
  and needs rotating.
- A PR with **no deployment section** is not the same as one that says "None". List it under "PRs
  with no deployment notes stated", with any `deploy_hints` found, so the deployer can check with the
  author. Only when every PR explicitly says None (or there are no PRs) should the section read
  "None — no deployment actions found in the included PRs".
- Don't add actions the PRs don't mention. "May require configuration" boilerplate makes the real
  items harder to see. You can **infer an ordering constraint** only when it follows directly from
  stated items (a secret must exist before the service that reads it is deployed). Say that it's
  inferred.

## 5. Draft the release PR

- **Template**: use a release-specific template if the repo has one
  (`.github/PULL_REQUEST_TEMPLATE/release.md` or similar). Otherwise use
  `assets/RELEASE_PR_TEMPLATE.md`. The repo's normal feature-PR template usually doesn't fit a
  release, so don't force it.
- **Title**: match past release PRs into the same target if they follow a pattern (the platform
  lookup in step 1 shows them). Otherwise use `Release: <source> → <target> (<YYYY-MM-DD>)`.
- **Azure DevOps limits PR descriptions to 4,000 characters.** If the draft is longer, keep
  Deployment Notes in full and shorten the other sections: collapse "Other changes" into one line
  and drop the Included PRs table, because the PR links are already inline. Tell the user what you
  shortened. GitHub allows about 65k, so this rarely matters there.

Present the draft as two copy-friendly blocks: the title on one line in a plain code fence, and the
body in one `markdown` fence. After them, add a few lines **outside** the fences covering the range
used (`boundary_method`, number of PRs), any warnings you couldn't resolve, and questions such as
"PR #21 mentions Node 20 on build agents but has no deployment section; is that a deploy
requirement?".

## 6. Create (or update) the PR, only after approval

Don't create anything until the user approves the draft. Then:

- **GitHub**: `gh pr create --base <target> --head <source> --title '…' --body-file "$BODY"`, or
  `gh pr edit <n> --body-file "$BODY"` to update an existing release PR.
- **Azure DevOps**: `az repos pr create --source-branch <source> --target-branch <target> --title
  '…' --description "$(cat "$BODY")"`, or `az repos pr update --id <n> --description …`. You can
  also use an Azure DevOps connector if your environment has one.
- Write `$BODY` to a temp file outside the repo (`mktemp`) and delete it afterwards.
- Return the PR URL. Don't merge it, complete it, or set auto-complete. The release still needs its
  own review and a deploy window.

## Guardrails

- Every feature line and every deployment item must trace back to a PR in the collected range. Don't
  invent items, and don't fill gaps from general knowledge of "what deploys usually need".
- Don't present results as complete when PR descriptions couldn't be fetched. Say which ones are
  missing.
- Never copy secret values into the release PR.
- Don't write scratch files (the JSON, the body) inside the repo.
- Don't create, update, merge, or complete a PR without explicit approval.
