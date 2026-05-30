# CLAUDE.md

@AGENTS.md

This file intentionally imports the repository-level `AGENTS.md` so Claude Code and Codex share one project instruction source.

Claude-specific reminders:

- Keep this file short. Put durable project rules in `AGENTS.md` unless they are Claude-only.
- After editing `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.codex/`, hooks, skills, commands, or related instruction files, report the change and recommend a fresh Claude Code session before assuming the new guidance is active.
- Use `.claude/commands/` for optional task prompts, not for always-loaded doctrine.
