# Performance measurements

Run from the repository root after the [development setup](../CONTRIBUTING.md):

```bash
PYTHONPATH=src python scripts/benchmark.py --messages 1000 10000 --repeat 3 \
  --batch-size 500 --output /tmp/mboxer-benchmark.json
```

All archives, databases and exports are synthetic and confined to automatically
removed temporary directories. The command does not read existing user archives
or configuration. `--output` is the only retained file; omit it for JSON on stdout.
The benchmark uses the existing runtime dependencies and Python standard library.
`--messages` accepts one or more positive sizes; each size gets `--repeat` fresh
workers. `--batch-size` controls the ingest batch size. This script uses a fixed
in-memory configuration instead of loading a personal YAML file.

Each repetition runs in a fresh process and measures these operations separately:

- Initial ingest, including source hashing and batch commits.
- Repeated ingest of the same archive, checking that no duplicates are inserted.
- Thread rule classification and inheritance to every message, then a no-work repeat.
- Sensitivity scanning with known synthetic findings, then idempotent re-scanning.
- Scrubbed JSONL export with residual findings blocked.

The fixed corpus groups five messages per thread, adds labels, and places a
synthetic phone number in every tenth body. Corpus SHA-256, input/output/database
bytes, wall time, CPU time, throughput and process peak RSS accompany the raw
samples and median stage times. Behavior checks fail the command if messages are
lost, reingest duplicates them, classification misses them, scrubbing fails, or
foreign-key integrity breaks. These checks are independent of timing results.

Fixture generation and final output inspection are outside stage timings. Peak
RSS covers the **whole worker process**, including fixture creation; it is not a
per-stage allocation measurement. RSS is unavailable on platforms without
`resource`. Filesystem caches are not flushed: this measures repeated local
execution, not cold-disk throughput. Attachments, malformed mail, Markdown
packing and multi-account concurrency are not represented by this workload.

Compare the same workload, batch size, Python version and hardware across
revisions. The report identifies the imported package directory and records
separate hashes for the package's Python, SQL and YAML files and for the
benchmark script. When comparing checkouts with a shared virtual environment,
set `PYTHONPATH=/path/to/checkout/src`
explicitly so an editable install cannot silently select another revision.
Record the commit SHA alongside results. Use raw repetitions to assess
variation before inferring improvements. The current CI workflow does not run
this benchmark; run it explicitly when a performance comparison is needed. The
script has no elapsed-time gate. Counts and integrity remain mandatory, and
hosted-runner timing alone is weak evidence of a performance change.
For meaningful archive-scale measurements, increase `--messages` on the intended
local machine before changing memory layout, queries or batching defaults.

For export-specific allocation scaling, use the separate
[memory benchmark](export-memory.md), which traces allocations and uses a
different synthetic workload.

## Historical consolidation measurements (2026-10-03)

The consolidation delivered in
[PR #26](https://github.com/uscient/mboxer/pull/26) was compared with `4259676`
(the then-current `dev`) on Linux / Python 3.12.14,
using 4,000 synthetic messages and three fresh-process repetitions per revision.
Median ingest was 0.748 → 0.745 seconds; JSONL was 3.681 → 3.689 seconds.
All count/integrity checks passed and output byte counts matched. This supports
behavior preservation on this workload, not a material end-to-end throughput
improvement. These numbers describe that historical comparison; this document
does not retain the raw sample reports or the exact measured after-change source
hash. Rerun both revisions before making a new performance claim.

That change also made the regex detector count matches with an iterator instead
of retaining every match string. For `"synthetic@example.test " * 100_000`, peak traced Python
allocation during `RegexDetector().detect(text)` fell from 7,102,410 to 2,364
bytes with identical findings, count, and excerpt. The input was allocated before
`tracemalloc.start()`. This isolated measurement concerns match storage; it does
not include the input body or establish constant memory for the entire archive.
