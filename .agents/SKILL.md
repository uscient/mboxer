# mboxer Operating Skill Guide

This document outlines the standard operating procedures, core competencies, and execution rules for AI agents, LLMs, or advanced users interacting with the `mboxer` environment.

## 1. System Understanding
An agent utilizing `mboxer` must understand that it is operating a **local-first** and **privacy-conscious** data pipeline. `mboxer` assumes mail archives contain sensitive material, so raw exports are local-only by default. The system is *not* a tool that uploads raw email archives by default or a cloud-first archive processor.

## 2. Core Execution Workflow
When instructed to process an email archive, the agent should follow this exact sequence of operations:
1. **Initialize:** Ensure the SQLite database is ready (`mboxer init`).
2. **Register:** Verify the target account is registered (`mboxer register`).
3. **Ingest:** Execute `mboxer ingest` with the `--resume` flag. *Crucial Skill:* Always advise the user to run a test ingest on a small, segmented `.mbox` file before ingesting a large historical archive.
4. **Classify:** Execute `mboxer classify`.
5. **Review:** Instruct the user to interactively run `mboxer review-categories` to approve or reject taxonomy proposals.
6. **Scan:** Execute `mboxer scan` to run configured redaction and security rules.
7. **Dry-Run:** ALWAYS execute a dry-run (`mboxer export notebooklm --dry-run`) before a real export to validate output shapes and profile limits.
8. **Export:** Execute the final real export.

## 3. Configuration & Profile Management
The agent must be adept at modifying the `mboxer.yaml` configuration to select the appropriate NotebookLM limit profile:
* `standard`: 40 target sources, 300,000 words/source
* `plus`: 80 target sources, 300,000 words/source
* `pro`: 250 target sources, 300,000 words/source
* `ultra`: 525 target sources, 300,000 words/source
* `ultra_safe`: 450 target sources, 225,000 words/source

*Strategy Rule:* The agent should default to recommending `ultra_safe` for large NotebookLM-oriented workflows to preserve headroom for manual sources, attachments, and later additions.

## 4. Classification Context Preservation
* **Thread Context:** Recognize that classification runs at both the message and thread level. At the thread level, a matching rule is applied to the whole thread and then inherited down to all messages in the thread. 
* **Confidence Levels:** Understand that rules support two assignment modes: `assign` for confident matches (confidence 1.0) and `assign_hint` for soft matches (confidence 0.75).
* **Multi-Account:** Maintain strict separation. `mboxer` utilizes per-account keyed storage to keep multi-account exports completely separated.
