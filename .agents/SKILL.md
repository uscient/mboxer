# mboxer Operating Skill Guide

This document outlines the standard operating procedures, core competencies, and execution rules for AI agents, LLMs, or advanced users interacting with the `mboxer` environment.

## 1. System Understanding
An agent utilizing `mboxer` must understand that it is operating a **local-first** and **privacy-conscious** data pipeline. `mboxer` assumes mail archives contain sensitive material, so raw exports are local-only by default. The system is *not* a tool that uploads raw email archives by default or a cloud-first archive processor.

## 2. Core Execution Workflow
When instructed to process an email archive, the agent should follow this exact sequence of operations (pass `--config config/mboxer.yaml` on each command unless the user specifies another config path):
1. **Initialize:** Ensure the SQLite database is ready (`mboxer init-db --config config/mboxer.yaml`).
2. **Register:** Add or verify the target account (`mboxer account add <account-key> --email <address> --config config/mboxer.yaml`).
3. **Ingest:** Execute `mboxer ingest ... --resume --account <account-key>`. *Crucial Skill:* Always advise the user to run a test ingest on a small, segmented `.mbox` file before ingesting a large historical archive.
4. **Classify:** Execute `mboxer classify --account <account-key>`.
5. **Review:** Instruct the user to run `mboxer review-categories --account <account-key>` and, when needed, `mboxer approve-category` / `mboxer reject-category`.
6. **Scan:** Execute `mboxer security-scan --account <account-key>` to run configured redaction and security rules.
7. **Dry-Run:** ALWAYS execute a dry-run (`mboxer export notebooklm --dry-run --account <account-key>`) before a real export to validate output shapes and profile limits.
8. **Export:** Execute the final real export (`mboxer export notebooklm` and/or `mboxer export jsonl`).

## 3. Configuration & Profile Management
The agent must be adept at modifying `config/mboxer.yaml` (from `config/mboxer.example.yaml`) to select the appropriate NotebookLM limit profile:
* `standard`: 40 target sources, 300,000 words/source
* `plus`: 80 target sources, 300,000 words/source
* `pro`: 250 target sources, 300,000 words/source
* `ultra`: 525 target sources, 300,000 words/source
* `ultra_safe`: 450 target sources, 225,000 words/source

*Strategy Rule:* The agent should default to recommending `ultra_safe` for large NotebookLM-oriented workflows to preserve headroom for manual sources, attachments, and later additions.

## 4. Classification Context Preservation
* **Provider:** Classification is deterministic rule-based today (`classification.provider: rules`). Ollama/LLM classification is future-facing unless a task explicitly implements it.
* **Thread Context:** Recognize that classification runs at both the message and thread level. At the thread level, a matching rule is applied to the whole thread and then inherited down to all messages in the thread.
* **Confidence Levels:** Understand that rules support two assignment modes: `assign` for confident matches (confidence 1.0) and `assign_hint` for soft matches (confidence 0.75).
* **Multi-Account:** Maintain strict separation. `mboxer` utilizes per-account keyed storage to keep multi-account exports completely separated.
