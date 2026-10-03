# Export memory benchmark

Run the same script against explicit source checkouts, using a Python environment
with MBoxer's normal dependencies:

```bash
PYTHONPATH=/path/to/checkout/src python scripts/benchmark_memory.py \
  --messages 1000 16000 --output /tmp/mboxer-memory.json
```

The standard-library script creates disposable synthetic databases. Every sample
runs in a fresh child process. It uses 2,053-character bodies and distinct thread
keys with 512 characters of padding, checks record counts and residual findings,
and records the source fingerprint, Python version, platform, and raw samples.
Use `--repeat` for repeated measurements. No real mail is read.

Representative measurements on Linux / Python 3.12.14, one sample per size:

| Operation | Baseline Python peak, 1k → 16k messages | Updated Python peak, 1k → 16k messages | Baseline → updated process RSS at 16k |
| --- | ---: | ---: | ---: |
| JSONL | 6.31 → 68.90 MB | 2.19 → 2.17 MB | 129.02 → 25.77 MB |
| NotebookLM | 5.14 → 64.17 MB | 1.52 → 1.67 MB | 109.75 → 26.25 MB |
| Security scan | 2.19 → 35.17 MB | 0.0063 → 0.0063 MB | 62.09 → 22.08 MB |

MB means 1,000,000 bytes. The baseline is the export-boundary upgrade before
streaming (`f91f7fc`, equivalent remote tree `43e246f`). Python peaks use
`tracemalloc` during the operation and exclude corpus construction. Process RSS
also includes imports, corpus construction, SQLite caches, and native allocations;
it is available where Python's `resource` module supports it. Instrumented wall
times are descriptive and are not throughput benchmarks.

These measurements establish payload scaling on this workload, not constant
memory for every possible archive. The largest individual message and configured
source budget still matter. Disk staging, sorting, and publication copies trade
temporary storage and I/O for lower memory use. See
[packing and publication](notebooklm-limits.md) for disk and recovery behavior.
