# dev-skills

A collection of [Agent Skills](https://github.com/vercel-labs/skills) for the engineering team —
reusable, packaged instructions that work with Claude Code and 30+ other coding agents (Cursor,
Cline, Copilot, Windsurf, ...).

## Skills

| Skill | Description |
|---|---|
| [`security-audit-report`](skills/security-audit-report/SKILL.md) | Audits a codebase for vulnerabilities and produces a rigorous Markdown + HTML report — numbered findings, each with a verified severity, category, exact file:line citations, an exploit path, and a fix. Supports fresh audits and incremental re-audits against a newer commit. |

## Install

Skills are installed with the [`npx skills`](https://github.com/vercel-labs/skills) CLI, which
detects whichever coding agent(s) you have and installs into the right config directory
(`.claude/skills/`, `.agents/skills/`, etc.).

```bash
# see what's available
npx skills add basyonic/dev-skills --list

# install one skill
npx skills add basyonic/dev-skills --skill security-audit-report

# install everything
npx skills add basyonic/dev-skills --skill '*'
```

To install from a local checkout instead of GitHub, point the CLI at the repo path:

```bash
npx skills add . --skill security-audit-report
```

## Contributing a skill

See `CLAUDE.md` for the expected directory layout (`skills/<name>/SKILL.md`) and guidance on
keeping skills portable across agents.
