# Configuration reference

The canonical example is [defaults.yaml](../src/mboxer/defaults.yaml). Print the
copy bundled with your installed version with `mboxer config-example`:

```bash
mkdir -p config
mboxer config-example > config/mboxer.yaml
mboxer init-db --config config/mboxer.yaml
```

Pass `--config config/mboxer.yaml` on subsequent commands as well. Configuration
and database flags belong after the leaf command, for example
`mboxer export jsonl --config config/mboxer.yaml --db var/example.sqlite`.

## File selection and defaults

Configuration is loaded in this order:

1. An explicit `--config` path. A missing file, invalid YAML, or a non-mapping
   root is an error; it does not fall back to another file.
2. When `--config` is omitted, an existing `config/mboxer.example.yaml` in the
   working directory is used for compatibility with older checkouts.
3. Otherwise, the installed package's `defaults.yaml` is used.

`config/mboxer.yaml` is **not** discovered automatically. An empty YAML file
loads as an empty mapping. A chosen file is not deeply merged with the bundled
example: individual runtime settings have fallbacks, but rules, taxonomy, and
NotebookLM profile definitions are not copied into a partial configuration.
Starting from `config-example` preserves those definitions and the enabled
redaction switches.

Paths are relative to the process's current working directory, not the YAML
file's directory. YAML values do not expand `~` or environment variables. Use
absolute paths when commands may run from different directories.

## Active settings

| Key or section | Current behavior |
| --- | --- |
| `paths.database` | SQLite file; `--db` overrides it. Missing/empty values fall back through legacy `project.default_database` to `var/mboxer.sqlite`. |
| `paths.attachments_dir` | Extracted attachment root; absent means `data/attachments`. An explicit empty string means the current directory; null and non-string values are errors. Ingest validates this setting even when extraction is disabled. |
| `paths.notebooklm_dir` | NotebookLM output root; `--out` overrides it. Missing/empty values fall back to `exports/notebooklm`. |
| `ingest.batch_commit_size` | Normal ingest checkpoint/commit interval; absent means `500`. Forced replacement uses one replacement transaction. |
| `ingest.store_body_html` | Whether normalized HTML is retained in SQLite; absent means `false`. Exporters use normalized text. |
| `ingest.max_body_chars` | Stored normalized text character cap; absent means `50000`. Larger text bodies are truncated before downstream classification, scanning, and export. Retained HTML is not capped by this setting. |
| `classification.level` | `thread` or `message`; absent means `thread`. `classify --level` overrides it. |
| `taxonomy.locked_categories` | Category paths seeded as global locked metadata when classifying. This is not an allowlist for rule assignments. |
| `rules` | Ordered rules with match predicates and `assign`/`assign_hint` metadata. An omitted list supplies no rules. See [classification](../README.md#classification-and-categories). |
| `security.default_export_profile` | Fallback content profile; absent/unknown values resolve to `scrubbed`. |
| `security.scan_enabled` | Controls the standalone `security-scan` command; absent means `true`. It does not disable export residual checks. |
| `security.scrub_enabled` | Controls body redaction during export; absent means `true`. Individual redaction switches must also be enabled. |
| `security.redact_email_addresses`, `redact_phone_numbers`, `redact_ssn_like_numbers`, `redact_credit_card_like_numbers` | Enable the corresponding body-text redactions. The bundled example enables all four; omitted switches in a custom file are disabled. |
| `security.on_residual_findings` | `allow`, `warn`, or `block` for residual body findings during export; absent/unknown values resolve to `warn`. `--findings-policy` overrides it. |
| `exports.notebooklm.profile` | Selected packing preset; absent means the name `ultra_safe`. Its definition must exist in the chosen configuration. `--profile` overrides the name. |
| `exports.notebooklm.profiles` | Complete named limit definitions. Custom files must supply the profiles they use; they are not merged with bundled profiles. See [packing limits](notebooklm-limits.md). |
| `exports.jsonl.output_file` | JSONL destination; `--out` overrides it. Missing/empty values fall back to `exports/rag/messages.jsonl`. |
| `exports.jsonl.include_classification` | Includes classification columns in JSONL when true; absent means `true`. Turning it off does not bypass export policy. |

`exports.notebooklm.format` and `exports.notebooklm.split_strategy` are
descriptive metadata copied to manifests. Changing them does not change
rendering, category/year grouping, or thread preservation. Other unrecognized
keys are not a supported extension mechanism. There is no general configuration
schema validator: validation is performed by individual consumers, so use YAML
booleans and the documented value types rather than quoted substitutes.

## Export policy and redaction boundaries

`--profile` selects NotebookLM packing limits. `--export-profile` selects the
content policy (`raw`, `reviewed`, `scrubbed`, or `metadata-only`). These are
independent options. An explicit content override takes precedence over stored
classification policy, including `exclude`; use it deliberately.

`reviewed` uses the same body-redaction path as `scrubbed`; it is not evidence of
human approval. Redaction and residual detection operate on normalized body text,
not on sender/recipient fields, subjects, attachment names, or attachment bytes.
`metadata-only` removes the body but still exports identifying metadata. See
[security behavior](security-roadmap.md) for the implemented boundaries.

## Removed or inactive configuration

Older configurations may contain Ollama/model settings, top-level account
defaults, or extra directory settings. They do not activate integrations or
account selection. There is no model-backed classifier or `classify --model`
option. `paths.database` is the preferred database setting; the legacy
`project.default_database` fallback is still supported.
