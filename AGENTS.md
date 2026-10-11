# AGENTS.md

Guidance for coding agents other than Claude Code (Codex, Cursor, Copilot, ...) working in this
repository.

**Read [`CLAUDE.md`](CLAUDE.md) first — it is the single source of truth for this repo's purpose,
layout, skill-authoring rules, and workflow, and it applies to every agent, not just Claude Code.**
This file only adds what you need to read it correctly from another agent.

## Reading CLAUDE.md as a non-Claude agent

- Wherever `CLAUDE.md` says "Claude Code" as the one *doing the work* (running a skill's scripts,
  reading a `SKILL.md` cold, following the workflow), read it as "you, the agent".
- Where it names a Claude-Code-only mechanism as an *example of what to avoid* in skills (`context:
  fork`, `hooks`, "subagent", "the Task tool", "the Artifact tool", "AskUserQuestion"), the rule
  still applies to you: skills here must stay agent-agnostic, so don't add your own agent's
  tool/feature names to skill bodies either.
- Skills install into each agent's own config directory (`.claude/skills/`, `.agents/skills/`,
  etc.) via `npx skills` — the commands in `CLAUDE.md`'s Installation section work unchanged.

## Keeping the two files in sync

Put new repo guidance in `CLAUDE.md`. Only add to this file when something is specific to
non-Claude agents and would be wrong or noise for Claude Code.
