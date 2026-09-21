---
name: pr-prep
description: >-
  Drafts a PR title and description from branch/git history, tailored to whatever PR template and
  work-item tracker (Jira, Linear, Azure DevOps, GitHub Issues, or none) the repo actually uses. Use
  when the user asks to write a PR message, improve a PR description, prepare a pull request, or
  create a PR.
---

# PR prep

## Instructions

Use this workflow when the user asks to prepare or create a pull request.

0. **Work item reference (optional, tracker-agnostic)**
   - Don't assume a specific tracker or key format. Different repos use Jira (`PROJ-123`), Linear
     (`ENG-123`), Azure DevOps (`#123` or `AB#123`), a GitHub issue (`#123`), or nothing at all.
   - Check the branch name and the user's message for anything that looks like a work-item
     reference. If you find one, use it as-is — don't reformat it to a pattern from a different
     tracker.
   - If none is present, **ask once**: "Is there a work item / ticket this PR should reference?"
     Accept a key, a URL, or an explicit "none." Don't guess or invent one, and don't block drafting
     on the answer — draft with a placeholder and fill it in once they answer.

1. Determine the base branch. Don't hardcode `main`, `master`, or `develop`:
   - `git symbolic-ref refs/remotes/origin/HEAD` (or `git remote show origin`) to find the repo's
     actual default branch.
   - If that's ambiguous, ask the user which branch this PR targets.

2. Gather context from git (substitute the base branch found in step 1 for `<base>`):
   - `git status`
   - `git diff` (staged + unstaged)
   - `git log --oneline <base>...HEAD`
   - `git diff --name-only <base>...HEAD` (also scan this list for documentation: e.g. `README.md`,
     `README.rst`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/` trees, `*.md` at repo root or under
     `docs/`, and similar conventional doc filenames)
   - `git log --format='%h %s%n%b' <base>...HEAD` (capture commit messages/comments)

3. **Find a PR template — but don't depend on one existing.**
   - Look for a repo-provided template in the conventional locations: `.github/PULL_REQUEST_TEMPLATE.md`,
     `.github/pull_request_template.md`, `docs/PULL_REQUEST_TEMPLATE.md`, or a `.github/PULL_REQUEST_TEMPLATE/`
     directory with multiple templates (if there are several, ask which one applies).
   - If found, follow its sections and order exactly — it's the repo's own convention and takes
     priority over anything below.
   - If **not** found, fall back to `assets/PULL_REQUEST_TEMPLATE.md` bundled with this skill and use
     its sections. Mention to the user that no repo template was found and this is a generic fallback,
     in case they'd rather add a real one to the repo later.

4. Draft **PR title** and **PR body**:
   - **Title**: concise, human-readable, not the raw branch name. If a work item reference is known,
     prefix it — match whatever style the repo's existing merged PRs use (check `git log` on the base
     branch for the convention) if one is discernible; otherwise use `<KEY>: <title>`.
   - **Body**: concise, reflects branch history and changed files, summarizes intent and impact,
     realistic test plan and checklist, concrete bullets under `## Changes`, and a `## Documentation`
     block with repo-relative README/doc paths and design-doc URLs when known (otherwise "None" or a
     placeholder per the template).
   - **Infer documentation from the branch**: if `git diff --name-only <base>...HEAD` includes
     `README.md` or similar in-repo docs (see step 2), treat documentation as **present**: list those
     repo-relative paths under `## Documentation` and briefly note what changed (e.g. "README updated
     with setup steps"). Don't claim "None" when such files are in the diff. External design-doc URLs
     still require a real link or a placeholder — don't invent URLs.
   - **Screenshots / recordings**: if the template has this section (or you're using the bundled
     fallback, which does) and the diff touches UI, templates, styles, or other user-facing surface,
     prompt the user to attach before/after screenshots or a short screen recording rather than
     leaving it blank. You can't capture these yourself — ask the user to paste them into the section
     (or drop them into the PR after creation), and mark it "N/A" only when the change genuinely has
     no visible surface (backend-only, config, internal refactor).

5. Present both to the user for review, then **close gaps by asking** (don't rely on a long "please
   replace the placeholders yourself" closing paragraph).
   - After the first draft, identify what's still missing or placeholder: e.g. `## Design Decisions`
     is thin or unfilled, external links under `## Documentation` are unknown while in-repo paths may
     already be filled from the branch diff, the work item reference from step 0 is still pending.
   - Ask directly for those pieces, in short separate prompts as needed, for example:
     - **Design decisions**: ask whether they want to record any (decision, reasoning, alternatives).
       Ask them to paste the content, or reply explicitly that there are none.
     - **Documentation**: ask for any external design-doc or wiki URLs not inferable from git. Ask
       them to paste links or short notes, or reply "none" if there's nothing beyond the in-repo paths
       already listed (or truly no docs).
   - When the user answers, merge their text into the PR body and re-output the full title +
     description (same output format as below). If they said "none" for a section, replace the
     placeholder with an honest "None" (or one line stating there's nothing notable) while keeping the
     section — don't leave a lingering placeholder once they've answered.
   - If they send free-form edits to other sections, apply those and re-output the full body the same
     way.
   - **PR creation**: don't create the PR until the user explicitly approves the latest draft. A short
     closing note is fine — e.g. that you can open the PR once they confirm the text is final — without
     dumping a checklist of "replace every placeholder yourself."

6. After approval, help create the PR:
   - Base branch: whatever was determined in step 1.
   - Push the branch if needed (`git push -u origin HEAD`).
   - Pass the PR body to `gh pr create` (or the repo's equivalent PR tooling) without leaving a copy
     in the repo:
     - **Preferred**: `gh pr create --base <base> --title '…' --body "$(cat <<'EOF' … EOF)"`
       (heredoc), or paste the body when `gh` prompts interactively.
     - **If a file is needed** (e.g. `--body-file`): create it **outside the repository** — e.g.
       `PR_BODY=$(mktemp)`, write the markdown there, run
       `gh pr create --base <base> --title '…' --body-file "$PR_BODY"`, then `rm -f "$PR_BODY"`.
   - Return the PR URL.

## Output Format

Deliver **two** copy-friendly blocks:

### Title

- Put the PR title on **one line** inside a single-line fenced code block (a plain-text fence is
  fine) so it can be copied in one click.

### Description

- Wrap the **entire** PR body in one `markdown` fenced block: opening `markdown` fence → only the
  template's content → closing fence.
- Don't put commentary inside either fence. Brief notes **outside** the fences are fine (e.g.
  unrelated local changes). After the user supplies decisions/docs or says "none," the next full
  description inside the fence should reflect that — avoid leaving unfilled placeholders in sections
  they already answered.

Sections inside the description follow whichever template applies (step 3): the repo's own
`.github/PULL_REQUEST_TEMPLATE.md` order if one exists, otherwise `assets/PULL_REQUEST_TEMPLATE.md`'s
order:

- `## Summary`
- `## Design Decisions` (optional; if unknown after asking, use "None" or a single honest line once
  the user says there are none)
- `## Changes`
- `## Documentation` (README / in-repo doc paths inferred from files in `<base>...HEAD` when
  applicable; design-doc URLs; "None" only when no such files appear in the branch diff and no
  external doc applies)
- `## Screenshots / Recordings` (for UI-visible or user-facing changes; "N/A" for backend-only or
  non-visual changes)
- `## Test Plan`
- `## Compliance Checklist`

## Guardrails

- Don't write PR description scratch files (e.g. `.pr-body-*.md`) **inside the repo** — they're easy
  to commit by mistake. Use a heredoc, stdin, or a temp path from `mktemp` outside the project tree.
- Don't create a PR before explicit user approval of the draft.
- For **Design Decisions** and **Documentation** (external URLs), ask the user for content or an
  explicit "none" before treating the description as final; merge their answer into the markdown
  block instead of ending on "replace the placeholders yourself."
- Don't invent tests or outcomes; mark unknowns clearly.
- Don't invent design-doc URLs or in-repo paths that aren't in the branch diff; list paths that are
  changed/added. For external URLs: don't invent; use a placeholder only until the Documentation
  prompt is answered — then use the user's links or "None," not a lingering placeholder.
- Don't invent a work-item key or force one into a repo that doesn't use trackers this way — ask once
  (step 0), accept "none," and move on.
- Don't assume the base branch is `main`/`master`/`develop` — determine it (step 1) or ask.
- If the branch includes unrelated commits, call it out before drafting final PR text.
