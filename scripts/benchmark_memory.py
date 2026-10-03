"""Measure archive payload memory using only disposable synthetic databases.

Compare the same script and arguments against two checkouts with explicit source
selection, for example: PYTHONPATH=/path/to/checkout/src python
scripts/benchmark_memory.py --messages 1000 16000 --output /tmp/memory.json
Python allocation peaks exclude corpus construction. Whole-process RSS also
includes imports, construction, SQLite caches, and native allocations. Timings
run under tracemalloc and are descriptive, never pass/fail thresholds.
"""
from __future__ import annotations

import argparse
import contextlib
import gc
import hashlib
import io
import json
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any


def positive(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def source_identity() -> dict[str, str]:
    import mboxer

    package = Path(mboxer.__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".sql"}:
            digest.update(path.relative_to(package).as_posix().encode() + b"\0")
            digest.update(path.read_bytes())
    return {"package_path": str(package), "source_sha256": digest.hexdigest()}


def sample(operation: str, count: int, body_chars: int, thread_chars: int) -> dict[str, Any]:
    from mboxer.accounts import create_account
    from mboxer.db import init_db
    from mboxer.exporters.jsonl import export_jsonl
    from mboxer.exporters.notebooklm import export_notebooklm
    from mboxer.limits import NotebookLMLimits
    from mboxer.security.scan import run_security_scan

    # Spaces prevent accidental pathological regex inputs; all content is synthetic.
    body = ("Synthetic local fixture words. " * (body_chars // 31 + 1))[:body_chars]
    config = {"security": {"default_export_profile": "scrubbed", "on_residual_findings": "block",
                           "redact_email_addresses": True, "redact_phone_numbers": True,
                           "redact_ssn_like_numbers": True, "redact_credit_card_like_numbers": True}}
    with tempfile.TemporaryDirectory(prefix="mboxer-memory-benchmark-") as directory:
        root = Path(directory)
        init_db(root / "fixture.sqlite")
        conn = sqlite3.connect(root / "fixture.sqlite")
        try:
            account_id = create_account(conn, "synthetic")
            conn.execute(
                "INSERT INTO mbox_sources (id,account_id,source_name,source_slug,file_path) "
                "VALUES (1,?,'synthetic','synthetic','synthetic.mbox')", (account_id,),
            )
            conn.executemany(
                "INSERT INTO messages (source_id,account_id,mbox_key,message_id,thread_key,subject,"
                "sender,recipients_json,cc_json,bcc_json,date_utc,body_text,body_hash,body_chars,"
                "body_word_count) VALUES (1,?,?,?,?, 'Synthetic', 'sender@example.invalid',"
                "'[]','[]','[]','2024-01-01',?,?,?,?)",
                ((account_id, str(i), f"message-{i}@example.invalid",
                  f"thread-{i}-" + "x" * thread_chars, body,
                  hashlib.sha256(body.encode()).hexdigest(), len(body), len(body.split()))
                 for i in range(count)),
            )
            conn.commit()
            gc.collect()
            tracemalloc.start()
            started = time.perf_counter()
            if operation == "jsonl":
                result = export_jsonl(conn, config, root / "output.jsonl",
                                      account_id=account_id, account_key="synthetic")
                if result["messages_written"] != count or result["residual_findings_total"]:
                    raise RuntimeError("synthetic export behavior changed")
            elif operation == "notebooklm":
                limits = NotebookLMLimits(
                    profile_name="synthetic", max_sources=1000, reserved_sources=0,
                    target_sources=1000, max_words_per_source=100000,
                    target_words_per_source=50000, max_bytes_per_source=8000000,
                    target_bytes_per_source=4000000, max_messages_per_source=1000,
                )
                result = export_notebooklm(conn, config, limits, root / "notebooklm",
                                           account_id=account_id, account_key="synthetic")
                if result["messages_exported"] != count or result["residual_findings_total"]:
                    raise RuntimeError("synthetic NotebookLM export behavior changed")
            else:
                result = run_security_scan(conn, config, account_id=account_id)
                if result != {"scanned": count, "findings": 0}:
                    raise RuntimeError("synthetic scan behavior changed")
            elapsed = time.perf_counter() - started
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            if operation == "jsonl":
                with (root / "output.jsonl").open(encoding="utf-8") as handle:
                    if sum(1 for _ in handle) != count:
                        raise RuntimeError("serialized record count changed")
            try:
                import resource
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                peak_rss = int(rss if sys.platform == "darwin" else rss * 1024)
            except ImportError:
                peak_rss = None
            return {"operation": operation, "messages": count, "body_chars": len(body),
                    "thread_padding_chars": thread_chars, "distinct_threads": count,
                    "python_peak_allocation_bytes": peak, "peak_process_rss_bytes": peak_rss,
                    "instrumented_wall_seconds": elapsed}
        finally:
            tracemalloc.stop()
            conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", type=positive, nargs="+", default=[1000, 16000])
    parser.add_argument("--body-chars", type=positive, default=2053)
    parser.add_argument("--thread-chars", type=positive, default=512)
    parser.add_argument("--operations", nargs="+", choices=["jsonl", "scan", "notebooklm"], default=["jsonl", "scan", "notebooklm"])
    parser.add_argument("--repeat", type=positive, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        with contextlib.redirect_stdout(io.StringIO()):
            result = sample(args.operations[0], args.messages[0], args.body_chars, args.thread_chars)
        print(json.dumps(result))
        return
    samples = []
    for operation in args.operations:
        for count in args.messages:
            for _ in range(args.repeat):
                child = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--worker", "--operations", operation,
                     "--messages", str(count), "--body-chars", str(args.body_chars),
                     "--thread-chars", str(args.thread_chars)],
                    capture_output=True, text=True, check=True, timeout=1800,
                )
                samples.append(json.loads(child.stdout))
    summary = []
    for operation in args.operations:
        for count in args.messages:
            rows = [row for row in samples if row["operation"] == operation and row["messages"] == count]
            summary.append({"operation": operation, "messages": count,
                            "median_python_peak_allocation_bytes": statistics.median(
                                row["python_peak_allocation_bytes"] for row in rows),
                            "median_peak_process_rss_bytes": statistics.median(
                                row["peak_process_rss_bytes"] for row in rows)
                            if all(row["peak_process_rss_bytes"] is not None for row in rows) else None})
    report = {"schema_version": 1, "workload": "synthetic-distinct-thread-memory-v1",
              "python": sys.version, "platform": platform.platform(), **source_identity(),
              "repeat": args.repeat, "summary": summary, "samples": samples}
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
