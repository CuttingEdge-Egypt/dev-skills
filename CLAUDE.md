# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repository is a collection of Claude Code **skills** for the engineering team — reusable,
packaged instructions (`SKILL.md` + supporting references/scripts/assets) that make Claude Code more
effective at recurring engineering tasks. Each top-level directory is one self-contained skill.

## Repository structure

Skills live under `skills/<skill-name>/` (the "flat layout" the `npx skills` CLI expects — see
Installation below). Each skill directory follows this layout:

```
skills/<skill-name>/
  SKILL.md              # required: YAML frontmatter (name, description) + the skill's instructions
  references/           # optional: longer reference docs the SKILL.md links to on demand
  scripts/               # optional: helper scripts the skill's instructions call out to
  assets/                # optional: static assets (css, templates, etc.) used when the skill renders output
  .gitignore
```

Do not put a skill directly at the repo root or nest it more than one level deep under `skills/`
(a `SKILL.md` found at a shallower level shadows anything nested below it) — one flat `skills/<name>/`
per skill.

The `description` field in a skill's frontmatter is what triggers the skill — it's matched against
the user's request, so it should enumerate the phrasings and situations that should invoke it (see
`skills/security-audit-report/SKILL.md` for the pattern: explicit trigger phrases, adjacent verbs, and
an explicit "prefer this over an ad-hoc X" clause).

## Installation (`npx skills`)

Skills in this repo are installed with the [`npx skills`](https://github.com/vercel-labs/skills) CLI,
which works across 30+ coding agents (Claude Code, Cursor, Cline, Copilot, Windsurf, ...), not just
Claude Code:

```bash
# from a local checkout
npx skills add . --list                 # see what's installable
npx skills add . --skill security-audit-report

# once this repo is on GitHub
npx skills add <owner>/<repo> --skill security-audit-report
npx skills add <owner>/<repo> --skill '*'   # install everything
```

The CLI detects the agent(s) present in the environment and installs into the right config
directory for each (`.claude/skills/`, `.agents/skills/`, etc.) — it does not need Claude Code
specifically.

## Writing skills agent-agnostically

Because these skills are meant to install into any agent, keep both frontmatter and body portable:

- Frontmatter: stick to `name` and `description`. Fields like `allowed-tools`, `context: fork`, and
  `hooks` are part of the Agent Skills spec but vary in support across agents — avoid them unless a
  skill genuinely only makes sense on Claude Code, and note that dependency explicitly if so.
- Body text: don't write instructions in terms of one agent's specific tool/feature names (e.g.
  "subagent", "the Task tool", "the Artifact tool", "AskUserQuestion"). Describe the *action* instead
  ("delegate to a helper", "ask the user to choose") so the instructions read correctly regardless of
  which agent is following them.
- Scripts referenced from a `SKILL.md` should be invoked as plain CLI commands (`python
  scripts/foo.py ...`) — any agent that can run a shell command can follow the skill.

Skills push detail out of `SKILL.md` and into `references/*.md`, loaded only when that section of the
workflow is reached (e.g. an "incremental update" mode reference, a category-specific checklist).
Keep `SKILL.md` itself focused on the workflow and decision points; move exhaustive detail,
templates, and taxonomies to `references/`.

Scripts under `scripts/` are meant to be run by Claude Code as part of following the skill (e.g.
reconciling generated counts, verifying citations, rendering final output) — they are deterministic
checks/renderers that replace hand-maintained bookkeeping the model would otherwise get wrong, not
general project tooling.

## Working on a skill

- Treat `SKILL.md` as the entry point a future Claude Code session reads cold — it must be
  self-contained about *when* to trigger and *what steps to follow*, with heavier material deferred
  to `references/`.
- When a skill ships scripts, run them as documented in that skill's `SKILL.md` (each script's own
  docstring/usage comment is authoritative for its CLI) rather than re-deriving behavior by hand.
- No repo-wide build/lint/test tooling exists yet; each skill is validated by using it end-to-end
  (running its scripts against sample input) rather than a shared test suite.
- After adding or moving a skill, sanity-check discovery with `npx skills add . --list`.
- Keep `README.md`'s skills table in sync with `skills/`: whenever a skill is added, removed, or its
  description/purpose changes meaningfully, update the corresponding README row in the same change.
