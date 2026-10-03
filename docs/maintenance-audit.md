# Maintenance audit — 2026-10-03

Inspected baseline: `dev` at `aa1b9873baaeb6f0c3a5440c19b41c9a5741271d`.
At inspection, `master` contained the same source tree and there were no open PRs.
All reproductions used synthetic mail and temporary databases.

The original suite passed **349 tests**, with **94.33% branch coverage** on
Python 3.12.14. Passing tests did not cover the defects below. This audit is a
dated observation, not an additional source of project policy.

## Proposed repair groups

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

These groups are independent review proposals; this document does not imply that
companion behavior changes have already merged.

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

## Remaining verified work

1. **NotebookLM publication can leave stale files.** Exporting three records,
   then excluding all three and exporting to the same destination, leaves the
   previous Markdown files even though the new manifest lists none. A complete
   fix needs staged publication and ownership-aware handling of previous output;
   deleting an arbitrary destination directory is not a safe repair. Existing
   export directories must be reviewed before sharing.
2. **NotebookLM limits are not uniformly enforced.** A one-source budget can
   still produce multiple source files; an individual rendered message can
   exceed the configured byte maximum. Packing must account for rendered
   metadata and oversized individual messages as well as body text.
3. **Whole-archive memory growth remains.** JSONL retains fetched rows and
   projected records; scanning fetches all bodies. In isolated allocation
   measurements with 2,053-character bodies, JSONL peaked near 7.6/24.0/90.2 MiB
   at 1k/4k/16k records; scanning near 2.1/8.3/33.4 MiB. A streaming design must
   preserve the current block-before-publication behavior for residual findings.
4. **Scanning is limited.** Regex detection and scrubbing concern body text;
   metadata, attachments and malware are not covered by those guarantees.
5. **Release controls require separate verification.** Publishing is triggered
   by a published GitHub Release and uses PyPI OIDC with the `pypi` environment.
   Source inspection alone cannot establish environment reviewer settings,
   signed-tag policy or current PyPI Trusted Publisher administration.
6. **Older agent setup material remains.** Optional prompts and setup notes
   still contain historical future-integration context. They do not constitute
   implementation evidence or an instruction to expand this maintenance work.

The priority after these repair groups is reliable NotebookLM publication and
packing, followed by archive-scale memory work supported by measurements.
