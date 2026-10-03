"""Measure a deterministic synthetic pipeline; never opens user archives.

Run from a checkout with mboxer installed, e.g.
python scripts/benchmark.py --messages 1000 10000 --repeat 3 --output /tmp/mboxer.json
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import mailbox
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"Benchmark behavior check failed: {message}")


def measure(action: Callable[[], Any], count: int) -> tuple[Any, dict[str, float]]:
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    result = action()
    cpu = time.process_time() - started_cpu
    wall = time.perf_counter() - started_wall
    return result, {"wall_seconds": wall, "cpu_seconds": cpu, "messages_per_second": count / wall}


def sample(count: int, batch_size: int) -> dict[str, Any]:
    from mboxer.accounts import create_account
    from mboxer.classify import run_rule_classification
    from mboxer.db import init_db
    from mboxer.exporters.jsonl import export_jsonl
    from mboxer.ingest import ingest_mbox
    from mboxer.security.scan import run_security_scan

    with tempfile.TemporaryDirectory(prefix="mboxer-benchmark-") as directory:
        root = Path(directory)
        source = root / "synthetic.mbox"
        box = mailbox.mbox(str(source))
        try:
            for index in range(count):
                thread = index // 5
                # Explicit envelope timestamps make corpus bytes repeatable.
                raw = (
                    "From benchmark@example.invalid Mon Jan 01 00:00:00 2024\n"
                    "From: benchmark@example.invalid\nTo: recipient@example.invalid\n"
                    f"Subject: Statement {thread}\nMessage-ID: <message-{index}@example.invalid>\n"
                    "Date: Mon, 01 Jan 2024 00:00:00 +0000\n"
                    + (f"References: <message-{thread * 5}@example.invalid>\n" if index % 5 else "")
                    + "X-Gmail-Labels: Inbox,Benchmark\n\n"
                    + f"Synthetic record {index}. "
                    + "Deterministic local archive performance fixture. " * 40
                    + ("Call 555-123-4567.\n" if index % 10 == 0 else "\n")
                )
                message = mailbox.mboxMessage(raw)
                message.set_from("benchmark@example.invalid Mon Jan 01 00:00:00 2024")
                box.add(message)
            box.flush()
        finally:
            box.close()

        with source.open("rb") as handle:
            corpus_hash = hashlib.file_digest(handle, "sha256").hexdigest()
        config = {
            "ingest": {"batch_commit_size": batch_size, "max_body_chars": 50000},
            "security": {"default_export_profile": "scrubbed", "on_residual_findings": "block",
                         "redact_email_addresses": True, "redact_phone_numbers": True,
                         "redact_ssn_like_numbers": True, "redact_credit_card_like_numbers": True},
            "rules": [{"name": "statements", "match": {"subject_contains": ["statement"]},
                       "assign": {"category_path": "benchmark", "export_profile": "scrubbed"}}],
        }
        db = root / "benchmark.sqlite"
        init_db(db)
        conn = sqlite3.connect(db)
        try:
            account_id = create_account(conn, "benchmark")
            stages: dict[str, dict[str, float]] = {}
            ingested, stages["ingest"] = measure(
                lambda: ingest_mbox(source, db_path=db, config=config, account_key="benchmark"), count)
            require(ingested["inserted"] == count and ingested["errors"] == 0, "complete ingest")
            repeated, stages["reingest"] = measure(
                lambda: ingest_mbox(source, db_path=db, config=config, account_key="benchmark"), count)
            require(repeated["inserted"] == 0 and repeated["skipped"] == count
                    and repeated["errors"] == 0, "idempotent reingest")
            _, stages["classify"] = measure(
                lambda: run_rule_classification(conn, config, account_id=account_id, level="thread"), count)
            classified = conn.execute(
                "SELECT COUNT(DISTINCT message_db_id) FROM classifications WHERE target_type = 'message'"
            ).fetchone()[0]
            require(classified == count, "every message classified")
            reclassified, stages["reclassify"] = measure(
                lambda: run_rule_classification(conn, config, account_id=account_id, level="thread"), count)
            require(reclassified["classified"] == 0, "completed threads are not reclassified")
            scanned, stages["scan"] = measure(
                lambda: run_security_scan(conn, config, account_id=account_id), count)
            require(scanned["scanned"] == count and scanned["findings"] == (count + 9) // 10,
                    "all expected synthetic findings detected")
            rescanned, stages["rescan"] = measure(
                lambda: run_security_scan(conn, config, account_id=account_id), count)
            require(rescanned["scanned"] == count and rescanned["findings"] == 0,
                    "findings are not duplicated on rescan")
            output = root / "messages.jsonl"
            exported, stages["jsonl"] = measure(
                lambda: export_jsonl(conn, config, output, account_id=account_id, account_key="benchmark"), count)
            require(exported["messages_written"] == count, "all projected messages exported")
            with output.open(encoding="utf-8") as handle:
                actual = 0
                for line in handle:
                    record = json.loads(line)
                    require("555-123-4567" not in (record["body_text"] or ""), "body scrubbed")
                    actual += 1
            require(actual == count, "serialized record count")
            require(not conn.execute("PRAGMA foreign_key_check").fetchall(), "foreign keys valid")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak_rss_bytes = int(rss if sys.platform == "darwin" else rss * 1024)
        except ImportError:
            peak_rss_bytes = None
        return {"messages": count, "batch_size": batch_size, "stages": stages,
                "corpus_sha256": corpus_hash, "input_bytes": source.stat().st_size,
                "database_bytes": db.stat().st_size, "output_bytes": output.stat().st_size,
                "peak_process_rss_bytes": peak_rss_bytes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", type=positive_int, nargs="+", default=[1000, 10000])
    parser.add_argument("--repeat", type=positive_int, default=3)
    parser.add_argument("--batch-size", type=positive_int, default=500)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        # Keep stdout machine-readable while exercising the real library functions.
        with contextlib.redirect_stdout(io.StringIO()):
            result = sample(args.messages[0], args.batch_size)
        print(json.dumps(result))
        return

    samples = []
    for count in args.messages:
        for _ in range(args.repeat):
            try:
                child = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--worker", "--messages", str(count),
                     "--batch-size", str(args.batch_size)],
                    capture_output=True, text=True, check=True, timeout=1800,
                )
            except subprocess.CalledProcessError as exc:
                raise SystemExit(f"Benchmark worker failed:\n{exc.stderr}") from exc
            samples.append(json.loads(child.stdout))
    summary = []
    for count in args.messages:
        rows = [row for row in samples if row["messages"] == count]
        require(len({row["corpus_sha256"] for row in rows}) == 1, "identical repeated corpus")
        summary.append({"messages": count, "median_wall_seconds": {
            stage: statistics.median(row["stages"][stage]["wall_seconds"] for row in rows)
            for stage in rows[0]["stages"]}})
    import mboxer
    package_directory = Path(mboxer.__file__).resolve().parent
    source_digest = hashlib.sha256()
    for path in sorted(package_directory.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".sql", ".yaml"}:
            source_digest.update(path.relative_to(package_directory).as_posix().encode())
            source_digest.update(b"\0")
            source_digest.update(path.read_bytes())
            source_digest.update(b"\0")
    report = {"schema_version": 1, "workload": "synthetic-thread-pipeline-v1",
              "python": sys.version, "platform": platform.platform(), "mboxer_version": mboxer.__version__,
              "package_directory": str(package_directory), "source_sha256": source_digest.hexdigest(),
              "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "repeat": args.repeat, "summary": summary, "samples": samples}
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
