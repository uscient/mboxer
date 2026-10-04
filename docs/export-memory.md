# Export memory benchmark

Run from the repository root after the [development setup](../CONTRIBUTING.md).
Select the source checkout explicitly, especially when sharing a virtual
environment between worktrees:

```bash
PYTHONPATH=/path/to/checkout/src python scripts/benchmark_memory.py \
  --messages 1000 16000 --output /tmp/mboxer-memory.json
```

The script creates disposable synthetic databases directly; it does not measure
MBOX parsing or ingestion. Each operation/size/repetition runs in a fresh child
process. Defaults are 2,053-character bodies and distinct thread keys with 512
characters of padding. Override them with `--body-chars` and `--thread-chars`,
select `jsonl`, `notebooklm`, or `scan` with `--operations`, and use `--repeat` for
repeated measurements. No real mail or user configuration is read. The NotebookLM
sample uses its own synthetic limits, not a bundled service profile.

Export checks require the expected returned message count and zero residual
findings; JSONL also checks serialized line count. Scanning requires the expected
message count and zero findings. These are behavior checks, not timing gates.
The report retains raw samples, medians, Python/platform details, package path,
and a fingerprint of the imported package's `.py` and `.sql` files. That
fingerprint excludes YAML and the benchmark script: record the commit and script
revision separately when comparing runs. Only `--output` is retained; omit it
for JSON on stdout.

## Historical streaming comparison (2026-10-03)

The following measurements were recorded during the streaming work delivered in
[PR #25](https://github.com/uscient/mboxer/pull/25), on Linux / Python 3.12.14 with
one sample per size. They are historical observations, not measurements of every
subsequent revision or hardware-specific guarantees.

| Operation | Before streaming, Python peak, 1k → 16k messages | After streaming, Python peak, 1k → 16k messages | Before → after process RSS at 16k |
| --- | ---: | ---: | ---: |
| JSONL | 6.31 → 68.90 MB | 2.19 → 2.17 MB | 129.02 → 25.77 MB |
| NotebookLM | 5.14 → 64.17 MB | 1.52 → 1.67 MB | 109.75 → 26.25 MB |
| Security scan | 2.19 → 35.17 MB | 0.0063 → 0.0063 MB | 62.09 → 22.08 MB |

MB means 1,000,000 bytes. The baseline was the pre-upgrade code at `aa1b987`
(tree `e979add`). The original comparison does not identify the exact measured
after-change source hash in this document; do not treat the numbers as a fresh
benchmark of the merge commit. Python peaks use
`tracemalloc` during the operation and exclude corpus construction. Process RSS
also includes imports, corpus construction, SQLite caches, and native allocations;
it is available where Python's `resource` module supports it. Instrumented wall
times are descriptive and are not throughput benchmarks. Use the separate
[pipeline benchmark](performance.md) for uninstrumented stage timings.

These measurements show payload scaling at the sampled sizes, not constant
memory for every possible archive. The largest individual message and configured
source budget still matter. NotebookLM records per-source metadata, and its
memory/disk needs change with packing settings and the size of any prior manifest.
Disk staging, sorting, and publication copies trade temporary storage and I/O
for lower memory use. See
[packing and publication](notebooklm-limits.md) for disk and recovery behavior.
