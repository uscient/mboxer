# Maintenance audit — 2026-10-03

Inspected baseline: `dev` at `aa1b9873baaeb6f0c3a5440c19b41c9a5741271d`.
At inspection, `master` contained the same source tree and there were no open PRs.
All reproductions used synthetic mail and temporary databases.

The original suite passed **349 tests**, with **94.33% branch coverage** on
Python 3.12.14. Passing tests did not cover the defects below. This audit is a
dated observation, not an additional source of project policy.

## Original repair groups (completed)

| Area | Verified gap | Upgrade |
| --- | --- | --- |
| Verification | Main CI and Bandit ignored PRs into `dev`; schema workflow validated the reference snapshot rather than runtime migrations | Run the existing checks on both integration and release PRs; keep a stable aggregate check; test installation and migrations |
| Installation | Default configuration resolved relative to the current directory and was absent from wheels | Bundle one default configuration and exercise an installed wheel outside the checkout |
| Configuration | Some example settings described unimplemented attachment scans, quarantine, and export controls | Label unused settings explicitly; preserve implemented behavior |
| Source identity | The migration-built database enforced globally unique MBOX paths despite account-scoped source lookups | Add a migration preserving identifiers and allowing the same path under different accounts |
| Recovery | Failed migrations could leave partial DDL; failed message writes could leave partial records | Atomic migration/version updates and message savepoints |
| Force ingest | Shrinking a replaced archive retained stale messages; failure could publish a new source hash over old evidence | Transactional source replacement with tested rollback and reclassification |
| Normalization | The UTC field retained original offsets; HTML retention setting was ineffective | Normalize known offsets to UTC and honor retention settings |
| Export policy | Disabling JSONL classification metadata also disabled per-message export policies | Resolve policy regardless of presentation settings |
| Output paths | Arbitrary account keys could become traversal/absolute path components | Reject unsafe path components without silently renaming identities |
| JSONL manifests | Removing two suffixes could collide with an output filename or another dated manifest | Replace only the output's final suffix |

These repairs merged into `dev` in [#23](https://github.com/uscient/mboxer/pull/23),
[#22](https://github.com/uscient/mboxer/pull/22), and
[#24](https://github.com/uscient/mboxer/pull/24). The table preserves the original
findings rather than describing outstanding defects. Ignored configuration
placeholders were initially labeled and have since been removed from the example.

## Measured optimization

SQLite chose account-only indexes for repeated classification and findings
lookups. Additive composite indexes on
`classifications(account_id, message_db_id, classifier_type)`,
`classifications(account_id, thread_key, target_type, classifier_type)` and
`security_findings(account_id, message_db_id)` address the measured lookup cost.

An isolated comparison used three fresh databases per variant, 4,000 synthetic
messages, five messages per thread, roughly 2 KB bodies, and one finding per
message. Median times on the same execution host were:

| Operation | Original indexes | Composite indexes |
| --- | ---: | ---: |
| Thread classification | 1.700 s | 0.086 s |
| Initial scan | 1.033 s | 0.411 s |
| Re-scan | 1.034 s | 0.410 s |
| Already-classified thread check | 3.280 s | 0.0023 s |

Both variants produced 800 classified threads, 4,000 initial findings, and zero
new findings on re-scan. These are workload-specific local measurements, not
performance guarantees. The reusable [benchmark](performance.md) measures a
different, explicitly described corpus with one finding per ten messages.

## Follow-up status

[#25](https://github.com/uscient/mboxer/pull/25) subsequently merged the remaining
NotebookLM publication, packing, and body-memory repairs into `dev`:

- Managed generations are staged before publication; prior manifest ownership
  controls stale-pack removal. Handled failures restore previous output.
- Packing counts complete rendered text and UTF-8 bytes and enforces the source
  budget. Dry runs use the same packing calculation.
- JSONL and NotebookLM use disk-backed staging; security scanning iterates body
  rows. [Memory measurements](export-memory.md) document the workload and limits.

The cleanup pass removes historical agent setup packs, speculative prompts, and
unused configuration scaffolding. AGENTS.md is now navigation and PROJECT.md
maps the current implementation.

## Remaining limitations

- **Scanning coverage:** body regex detection does not cover sensitive metadata,
  attachments, or malware. `reviewed` does not enforce human-review state.
- **Recovery boundaries:** handled errors are tested, but process termination,
  power loss, and concurrent publication need the operational care described in
  [publication behavior](notebooklm-limits.md).
- **Archive scaling:** staging trades temporary disk and I/O for lower body
  memory use. The largest message, thread processing, and configured source
  budget still matter; the measured workloads do not prove all archives fit.
- **Release administration:** source inspection does not verify environment
  reviewers, signed-tag policy, or PyPI Trusted Publisher settings.
