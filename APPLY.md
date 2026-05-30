# Apply this agent setup to `uscient/mboxer`

This package is intentionally wrapped in a top-level `mboxer-agent-setup/` directory so it cannot overwrite your repo by accident.

The public GitHub listing already shows some agent/context-related directories such as `.agents/`, `.claude/`, and `prompts/`. Review the current repo before copying anything.

From the root of a clean local checkout:

```bash
cd ~/projects/uscient/mboxer
git status --short
find . -maxdepth 3 -type f \
  \( -name 'AGENTS.md' -o -name 'CLAUDE.md' -o -path './.agents/*' -o -path './.claude/*' -o -path './.codex/*' -o -path './prompts/*' \) \
  | sort
```

Unzip somewhere outside the repo:

```bash
unzip /path/to/mboxer-agent-setup.zip -d /tmp/mboxer-agent-setup
find /tmp/mboxer-agent-setup/mboxer-agent-setup -type f | sort
```

Recommended cautious copy:

```bash
# Adds new files and prompts before overwriting existing ones.
cp -ain /tmp/mboxer-agent-setup/mboxer-agent-setup/. .
git status --short
```

If `cp -i` asks before overwriting existing `.claude` files, inspect the existing file and merge manually instead of blindly replacing it.

Recommended first commit after review:

```bash
git add AGENTS.md CLAUDE.md .codex .claude APPLY.md
git commit -m "Add agent guidance for mboxer"
```

After merging, switching branches, or changing instruction-surface files, start a fresh Codex or Claude Code session so the new guidance is definitely loaded.
