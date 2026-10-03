# Performance measurements

Run the synthetic pipeline benchmark from a development install:

```bash
python scripts/benchmark.py --messages 1000 10000 --repeat 3 --output /tmp/mboxer-benchmark.json
```

All archives, databases and exports are synthetic and confined to automatically
removed temporary directories. The command does not read existing user archives
or configuration. `--output` is the only retained file; omit it for JSON on stdout.
The benchmark uses the existing runtime dependencies and Python standard library.

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
revisions. The report identifies the imported package directory and hashes the
package's Python, SQL and YAML files plus the benchmark script. When comparing
checkouts with a shared virtual environment, set `PYTHONPATH=/path/to/checkout/src`
explicitly so an editable install cannot silently select another revision.
Record the commit SHA alongside results. Use raw repetitions to assess
variation before inferring improvements. Hosted-runner timing is informational;
there is no arbitrary elapsed-time gate. Counts and integrity remain mandatory.
For meaningful archive-scale measurements, increase `--messages` on the intended
local machine before changing memory layout, queries or batching defaults.
