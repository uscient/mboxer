# NotebookLM Export Limits

NotebookLM limits should be treated as configuration, not hardcoded implementation details.

The exporter must resolve a profile from `config/mboxer.yaml` and then apply CLI overrides.

## Profiles

Configured profiles:

- `standard`
- `plus`
- `pro`
- `ultra`
- `ultra_safe`

The default should be `ultra_safe` for Google AI Ultra workflows because it leaves room for manually uploaded documents, attachments, PDFs, and later additions.

## Required fields

Each NotebookLM profile must define:

```text
max_sources
reserved_sources
target_sources
max_words_per_source
target_words_per_source
max_bytes_per_source
target_bytes_per_source
max_messages_per_source
```

## Effective source budget

```text
effective_source_budget = max_sources - reserved_sources
```

The exporter should not exceed the effective source budget unless an explicit `--allow-full-source-budget` flag is passed.

## Splitting policy

The exporter should close a Markdown source pack when any configured hard limit is reached:

- max words
- max bytes
- max messages
- source budget

The exporter should prefer closing early at target limits:

- target words
- target bytes
- target sources

Thread integrity should be preserved when possible. If one thread exceeds source limits by itself, split it and mark the split in the Markdown source header.

## Validation policy

Recommended validation:

- fail if `max_bytes_per_source` exceeds 200 MB unless `--force` is used
- warn if `max_words_per_source` exceeds 500,000
- warn if `target_sources` exceeds `max_sources - reserved_sources`
- warn if generated source count exceeds `target_sources`
- fail if generated source count exceeds `max_sources` unless `--allow-full-source-budget` is used
