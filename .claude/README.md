# `.claude/` helper files

This directory contains optional Claude Code command prompts for repeatable mboxer work.

Root `CLAUDE.md` imports `AGENTS.md`, so durable project instructions should live in `AGENTS.md` unless they are Claude-only.

No active project-level `settings.json` is included on purpose. Avoid committing Claude settings that silently change permissions, hooks, or tool behavior for every collaborator unless there is a deliberate review.

After changing `.claude/`, `CLAUDE.md`, `AGENTS.md`, hooks, skills, commands, or related files, start a fresh Claude Code session before relying on the new instructions.
