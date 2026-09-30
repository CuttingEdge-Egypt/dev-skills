# dev-skills

A collection of [Agent Skills](https://github.com/vercel-labs/skills) for the engineering team —
reusable, packaged instructions that work with Claude Code and 30+ other coding agents (Cursor,
Cline, Copilot, Windsurf, ...).

## Skills

| Skill | Description |
|---|---|
| [`pr-create`](skills/pr-create/SKILL.md) | Drafts a PR title and description from branch/git history, tailored to whatever PR template and work-item tracker (Jira, Linear, Azure DevOps, GitHub Issues, or none) the repo actually uses. Falls back to a bundled template if the repo doesn't have one. |
| [`pr-prep`](skills/pr-prep/SKILL.md) | Pre-PR readiness check for the current branch. Runs the repo's own linters on changed files, runs a code review (via the `code-review` skill, or a built-in review as fallback), and scans only what the branch changed for unused code, debug leftovers, skipped tests, secrets, stray files, and conflicts with base. Produces a readiness report with a verdict, then offers fixes. |
| [`release-pr-create`](skills/release-pr-create/SKILL.md) | Drafts and, after approval, opens a release PR (e.g. `dev` → `staging`, `staging` → `main`). Collects every PR merged since the last release to that target (GitHub or Azure DevOps), writes a stakeholder-readable feature list, and consolidates each PR's deployment notes into one checklist covering env vars, secrets, migrations, infra, permissions, and manual steps. Every item cites its PR. |
| [`security-audit-report`](skills/security-audit-report/SKILL.md) | Audits a codebase for vulnerabilities and produces a rigorous Markdown + HTML report — numbered findings, each with a verified severity, category, exact file:line citations, an exploit path, and a fix. Supports fresh audits and incremental re-audits against a newer commit. |

## Install

Skills are installed with the [`npx skills`](https://github.com/vercel-labs/skills) CLI, which
detects whichever coding agent(s) you have and installs into the right config directory
(`.claude/skills/`, `.agents/skills/`, etc.).

```bash
# see what's available
npx skills add CuttingEdge-Egypt/dev-skills --list

# install one skill
npx skills add CuttingEdge-Egypt/dev-skills --skill pr-create

# install everything
npx skills add CuttingEdge-Egypt/dev-skills --skill '*'
```

To install from a local checkout instead of GitHub, point the CLI at the repo path:

```bash
npx skills add . --skill security-audit-report
```

## Contributing a skill

See `CLAUDE.md` for the expected directory layout (`skills/<name>/SKILL.md`) and guidance on
keeping skills portable across agents.
