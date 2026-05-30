# `.codex/` helper files

Codex reads repository instructions from root `AGENTS.md`. These `.codex/` files are optional helper prompts/templates for repeatable mboxer work.

Use them by pasting the prompt into Codex from the repo root, or by invoking Codex with the file content in your own shell workflow.

Important:

- Do not assume edits to this directory affect an already-running Codex session.
- After changing `.codex/`, `AGENTS.md`, or other instruction-surface files, start a fresh Codex session before relying on the new instructions.
- These prompts intentionally avoid inventing a uScientDB API. They prepare mboxer as a clean future producer without coupling it to a server that is not ready yet.
