from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .accounts import AccountError
from .config import ConfigError, deep_get, get_database_path, load_config
from .db import init_db
from .limits import resolve_notebooklm_limits, validate_notebooklm_limits


# ── Argument helpers ──────────────────────────────────────────────────────────

def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None, help="Path to mboxer YAML config")
    parser.add_argument("--db", default=None, help="Override SQLite database path")


def add_account_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", default=None, metavar="ACCOUNT_KEY",
                        help="Account key to operate on (required when multiple accounts exist)")


def load_runtime(args: argparse.Namespace) -> tuple[dict, Path]:
    config = load_config(args.config)
    db_path = get_database_path(config, args.db)
    return config, db_path


def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# ── Parser ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mboxer",
        description="Local-first MBOX archive processor for KM, RAG, and NotebookLM source packs.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── init-db ────────────────────────────────────────────────────────────────
    p_init = sub.add_parser("init-db", help="Initialize or migrate the SQLite database")
    add_common_args(p_init)
    p_init.set_defaults(func=cmd_init_db)

    # ── account ────────────────────────────────────────────────────────────────
    p_acct = sub.add_parser("account", help="Manage accounts")
    acct_sub = p_acct.add_subparsers(dest="account_cmd", required=True)

    p_acct_add = acct_sub.add_parser("add", help="Add a new account")
    add_common_args(p_acct_add)
    p_acct_add.add_argument("account_key", help="Unique account key (e.g. dad-gmail)")
    p_acct_add.add_argument("--display-name", default=None)
    p_acct_add.add_argument("--email", default=None, dest="email_address")
    p_acct_add.add_argument("--provider", default="gmail")
    p_acct_add.add_argument("--notes", default=None)
    p_acct_add.set_defaults(func=cmd_account_add)

    p_acct_list = acct_sub.add_parser("list", help="List all accounts")
    add_common_args(p_acct_list)
    p_acct_list.set_defaults(func=cmd_account_list)

    p_acct_show = acct_sub.add_parser("show", help="Show account details")
    add_common_args(p_acct_show)
    p_acct_show.add_argument("account_key")
    p_acct_show.set_defaults(func=cmd_account_show)

    p_acct_upd = acct_sub.add_parser("update", help="Update account display name or email")
    add_common_args(p_acct_upd)
    p_acct_upd.add_argument("account_key")
    p_acct_upd.add_argument("--display-name", default=None)
    p_acct_upd.add_argument("--email", default=None, dest="email_address")
    p_acct_upd.add_argument("--notes", default=None)
    p_acct_upd.set_defaults(func=cmd_account_update)

    # ── ingest ─────────────────────────────────────────────────────────────────
    p_ingest = sub.add_parser("ingest", help="Ingest an MBOX file into SQLite")
    add_common_args(p_ingest)
    add_account_arg(p_ingest)
    p_ingest.add_argument("mbox_path", help="Path to .mbox file")
    p_ingest.add_argument("--source-name", help="Human-readable source name")
    p_ingest.add_argument("--resume", action="store_true", help="Resume an interrupted ingest")
    p_ingest.add_argument("--extract-attachments", action="store_true")
    p_ingest.add_argument("--force", action="store_true")
    p_ingest.add_argument("--create-account", action="store_true",
                          help="Create the account if it does not exist")
    p_ingest.set_defaults(func=cmd_ingest)

    # ── classify ───────────────────────────────────────────────────────────────
    p_classify = sub.add_parser("classify", help="Classify messages using rules")
    add_common_args(p_classify)
    add_account_arg(p_classify)
    p_classify.add_argument("--model", default=None)
    p_classify.add_argument("--level", choices=["message", "thread"], default="thread")
    p_classify.set_defaults(func=cmd_classify)

    # ── review-categories ──────────────────────────────────────────────────────
    p_review = sub.add_parser("review-categories", help="Review category counts and pending proposals")
    add_common_args(p_review)
    add_account_arg(p_review)
    p_review.set_defaults(func=cmd_review_categories)

    # ── approve/reject-category ────────────────────────────────────────────────
    p_approve = sub.add_parser("approve-category", help="Approve a pending category proposal")
    add_common_args(p_approve)
    p_approve.add_argument("proposal_id", type=int)
    p_approve.add_argument("--note", default="")
    p_approve.set_defaults(func=cmd_approve_category)

    p_reject = sub.add_parser("reject-category", help="Reject a pending category proposal")
    add_common_args(p_reject)
    p_reject.add_argument("proposal_id", type=int)
    p_reject.add_argument("--note", default="")
    p_reject.set_defaults(func=cmd_reject_category)

    # ── security-scan ──────────────────────────────────────────────────────────
    p_security = sub.add_parser("security-scan", help="Run local security/sensitivity checks")
    add_common_args(p_security)
    add_account_arg(p_security)
    p_security.set_defaults(func=cmd_security_scan)

    # ── export ─────────────────────────────────────────────────────────────────
    p_export = sub.add_parser("export", help="Export processed mail")
    export_sub = p_export.add_subparsers(dest="export_type", required=True)

    p_nlm = export_sub.add_parser("notebooklm", help="Export NotebookLM Markdown source packs")
    add_common_args(p_nlm)
    add_account_arg(p_nlm)
    p_nlm.add_argument("--accounts", default=None, metavar="KEY1,KEY2",
                       help="Comma-separated account keys for explicit combined export")
    p_nlm.add_argument("--out", default=None)
    p_nlm.add_argument("--export-profile",
                       choices=["raw", "reviewed", "scrubbed", "metadata-only"], default=None)
    p_nlm.add_argument("--profile", default=None, help="NotebookLM limit profile")
    p_nlm.add_argument("--max-sources", type=int)
    p_nlm.add_argument("--reserved-sources", type=int)
    p_nlm.add_argument("--target-sources", type=int)
    p_nlm.add_argument("--target-words", type=int)
    p_nlm.add_argument("--max-words", type=int)
    p_nlm.add_argument("--target-mb", type=int)
    p_nlm.add_argument("--max-mb", type=int)
    p_nlm.add_argument("--allow-full-source-budget", action="store_true")
    p_nlm.add_argument("--force", action="store_true")
    p_nlm.add_argument("--dry-run", action="store_true")
    p_nlm.set_defaults(func=cmd_export_notebooklm)

    p_jsonl = export_sub.add_parser("jsonl", help="Export RAG JSONL")
    add_common_args(p_jsonl)
    add_account_arg(p_jsonl)
    p_jsonl.add_argument("--out", default=None)
    p_jsonl.add_argument("--export-profile",
                         choices=["raw", "reviewed", "scrubbed", "metadata-only"], default=None)
    p_jsonl.set_defaults(func=cmd_export_jsonl)

    return parser


# ── Command implementations ───────────────────────────────────────────────────

def cmd_init_db(args: argparse.Namespace) -> None:
    config, db_path = load_runtime(args)
    init_db(db_path)
    print(f"Database ready: {db_path}")


def cmd_account_add(args: argparse.Namespace) -> None:
    from .accounts import create_account, get_account
    config, db_path = load_runtime(args)
    init_db(db_path)
    conn = open_db(db_path)
    try:
        if get_account(conn, args.account_key):
            raise SystemExit(f"Account '{args.account_key}' already exists.")
        account_id = create_account(
            conn, args.account_key,
            display_name=args.display_name,
            email_address=args.email_address,
            provider=args.provider,
            notes=args.notes,
        )
        label = args.display_name or args.account_key
        print(f"Added account: {args.account_key}  ({label})  id={account_id}")
    finally:
        conn.close()


def cmd_account_list(args: argparse.Namespace) -> None:
    from .accounts import list_accounts
    config, db_path = load_runtime(args)
    init_db(db_path)
    conn = open_db(db_path)
    try:
        accounts = list_accounts(conn)
        if not accounts:
            print("No accounts configured. Add one: mboxer account add <account-key>")
            return
        print(f"\n{'Key':<25} {'Display Name':<30} {'Email':<35} {'Provider'}")
        print("-" * 95)
        for a in accounts:
            print(f"{a['account_key']:<25} {(a['display_name'] or ''):<30} "
                  f"{(a['email_address'] or ''):<35} {a['provider'] or ''}")
    finally:
        conn.close()


def cmd_account_show(args: argparse.Namespace) -> None:
    from .accounts import get_account
    config, db_path = load_runtime(args)
    conn = open_db(db_path)
    try:
        account = get_account(conn, args.account_key)
        if not account:
            raise SystemExit(f"Account not found: {args.account_key}")
        for k, v in account.items():
            print(f"  {k}: {v}")
    finally:
        conn.close()


def cmd_account_update(args: argparse.Namespace) -> None:
    from .accounts import update_account
    config, db_path = load_runtime(args)
    conn = open_db(db_path)
    try:
        ok = update_account(
            conn, args.account_key,
            display_name=args.display_name,
            email_address=args.email_address,
            notes=args.notes,
        )
        if not ok:
            raise SystemExit(f"Account not found or nothing to update: {args.account_key}")
        print(f"Updated account: {args.account_key}")
    finally:
        conn.close()


def cmd_ingest(args: argparse.Namespace) -> None:
    from .accounts import resolve_account
    from .ingest import ingest_mbox
    config, db_path = load_runtime(args)
    init_db(db_path)
    conn = open_db(db_path)
    try:
        if args.create_account and args.account:
            from .accounts import get_account, create_account
            if not get_account(conn, args.account):
                create_account(conn, args.account)
                print(f"Created account: {args.account}")
        account = resolve_account(conn, args.account, command="ingest")
    finally:
        conn.close()

    counts = ingest_mbox(
        args.mbox_path,
        config=config,
        db_path=db_path,
        account_key=account["account_key"],
        source_name=args.source_name,
        resume=args.resume,
        extract_attachments_flag=args.extract_attachments,
        force=args.force,
    )
    print(f"seen={counts['seen']} inserted={counts['inserted']} "
          f"skipped={counts['skipped']} errors={counts['errors']}")


def cmd_classify(args: argparse.Namespace) -> None:
    from .accounts import resolve_account
    from .classify import run_rule_classification
    from .taxonomy import seed_categories_from_config
    config, db_path = load_runtime(args)
    conn = open_db(db_path)
    try:
        account = resolve_account(conn, args.account, command="classify")
        account_id = account["id"]
        seeded = seed_categories_from_config(conn, config)
        if seeded:
            print(f"Seeded {seeded} global categories from config.")
        result = run_rule_classification(conn, config, level=args.level, account_id=account_id)
        print(f"Rule classification [{account['account_key']}]: "
              f"{result['classified']} classified, {result['skipped']} unmatched")
        if args.model:
            print(f"LLM classification with model={args.model} not yet implemented.")
    finally:
        conn.close()


def cmd_review_categories(args: argparse.Namespace) -> None:
    from .accounts import resolve_account
    from .taxonomy import get_all_categories, get_category_message_counts, list_pending_proposals
    config, db_path = load_runtime(args)
    conn = open_db(db_path)
    try:
        account = resolve_account(conn, args.account, command="review-categories")
        account_id = account["id"]
        cats = get_all_categories(conn, account_id)
        counts = get_category_message_counts(conn, account_id)
        proposals = list_pending_proposals(conn, account_id)

        print(f"\nCategories for account: {account['account_key']}")
        print(f"{'Category':<50} {'Messages':>10} {'Locked':>8} {'Scope':>8}")
        print("-" * 80)
        for cat in cats:
            n = counts.get(cat["path"], 0)
            locked = "yes" if cat["is_locked"] else ""
            scope = "global" if cat["is_global"] else "account"
            print(f"{cat['path']:<50} {n:>10} {locked:>8} {scope:>8}")

        if proposals:
            print(f"\n{len(proposals)} pending proposal(s):")
            for p in proposals:
                conf = f"{p['confidence']:.2f}" if p["confidence"] else "?"
                print(f"  [{p['id']}] {p['proposed_path']}  (confidence={conf})  {p['reason'] or ''}")
        else:
            print("\nNo pending category proposals.")
    finally:
        conn.close()


def cmd_approve_category(args: argparse.Namespace) -> None:
    from .taxonomy import approve_proposal
    config, db_path = load_runtime(args)
    conn = open_db(db_path)
    try:
        path = approve_proposal(conn, args.proposal_id, args.note)
        print(f"Approved proposal {args.proposal_id} -> {path}")
    finally:
        conn.close()


def cmd_reject_category(args: argparse.Namespace) -> None:
    from .taxonomy import reject_proposal
    config, db_path = load_runtime(args)
    conn = open_db(db_path)
    try:
        reject_proposal(conn, args.proposal_id, args.note)
        print(f"Rejected proposal {args.proposal_id}.")
    finally:
        conn.close()


def cmd_security_scan(args: argparse.Namespace) -> None:
    from .accounts import resolve_account
    from .security.scan import run_security_scan
    config, db_path = load_runtime(args)
    conn = open_db(db_path)
    try:
        account = resolve_account(conn, args.account, command="security-scan")
        result = run_security_scan(conn, config, account_id=account["id"])
        print(f"[{account['account_key']}] Scanned {result['scanned']} messages, "
              f"found {result['findings']} potential findings.")
    finally:
        conn.close()


def cmd_export_notebooklm(args: argparse.Namespace) -> None:
    from .accounts import resolve_account
    from .exporters.notebooklm import export_notebooklm
    config, db_path = load_runtime(args)
    limits = resolve_notebooklm_limits(
        config, args.profile,
        max_sources=args.max_sources,
        reserved_sources=args.reserved_sources,
        target_sources=args.target_sources,
        target_words=args.target_words,
        max_words=args.max_words,
        target_mb=args.target_mb,
        max_mb=args.max_mb,
    )
    warnings = validate_notebooklm_limits(
        limits,
        allow_full_source_budget=args.allow_full_source_budget,
        force=args.force,
    )

    out_base = args.out or deep_get(config, "paths.notebooklm_dir") or "exports/notebooklm"

    # Resolve account(s)
    conn = open_db(db_path)
    try:
        if args.accounts:
            account_keys = [k.strip() for k in args.accounts.split(",") if k.strip()]
            from .accounts import get_account
            accounts_to_export = []
            for k in account_keys:
                a = get_account(conn, k)
                if not a:
                    raise SystemExit(f"Account not found: {k}")
                accounts_to_export.append(a)
        else:
            account = resolve_account(conn, args.account, command="export notebooklm")
            accounts_to_export = [account]
    finally:
        conn.close()

    print("NotebookLM export configuration")
    print(f"  db={db_path}")
    print(f"  out={out_base}")
    print(f"  profile={limits.profile_name}")
    print(f"  max_sources={limits.max_sources}  reserved={limits.reserved_sources}  "
          f"effective_budget={limits.effective_source_budget}")
    print(f"  accounts: {', '.join(a['account_key'] for a in accounts_to_export)}")
    for w in warnings:
        print(f"WARNING: {w}")

    for account in accounts_to_export:
        conn = open_db(db_path)
        try:
            stats = export_notebooklm(
                conn, config, limits, Path(out_base),
                account_id=account["id"],
                account_key=account["account_key"],
                account_email=account.get("email_address"),
                account_display_name=account.get("display_name"),
                export_profile=args.export_profile,
                dry_run=args.dry_run,
                db_path=str(db_path),
            )
        finally:
            conn.close()

        if args.dry_run:
            print(f"  [{account['account_key']}] Dry run: {stats.get('groups', 0)} "
                  f"category/band groups would become source files.")
        else:
            print(f"  [{account['account_key']}] Exported {stats['files_written']} files, "
                  f"{stats['messages_exported']} messages.")


def cmd_export_jsonl(args: argparse.Namespace) -> None:
    from .accounts import resolve_account
    from .exporters.jsonl import export_jsonl
    config, db_path = load_runtime(args)
    conn = open_db(db_path)
    try:
        account = resolve_account(conn, args.account, command="export jsonl")
        account_key = account["account_key"]
        account_id = account["id"]
    finally:
        conn.close()

    default_out = deep_get(config, "exports.jsonl.output_file") or "exports/rag/messages.jsonl"
    out_str = args.out or default_out
    # Inject account_key into the output path if it doesn't already include it
    out_path = Path(out_str)
    if account_key not in out_path.parts:
        out_path = out_path.parent / account_key / out_path.name

    conn = open_db(db_path)
    try:
        result = export_jsonl(
            conn, config, out_path,
            account_id=account_id,
            account_key=account_key,
            account_display_name=account.get("display_name"),
            account_email_address=account.get("email_address"),
        )
    finally:
        conn.close()
    print(f"[{account_key}] Wrote {result['messages_written']} messages to {out_path}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (ConfigError, AccountError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
