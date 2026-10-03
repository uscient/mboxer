"""Resolve retained classification evidence into one effective message policy."""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing, contextmanager
from typing import Any, Iterator

from ..config import ConfigError
from ..security.policy import EXPORT_PROFILES, resolve_export_profile


class ExportPolicyConflict(ConfigError):
    """Competing classifications do not determine a safe export policy."""


@contextmanager
def policy_read_snapshot(conn: sqlite3.Connection) -> Iterator[None]:
    """Keep message and policy reads consistent without committing caller work."""
    conn.execute("SAVEPOINT mboxer_policy_read")
    try:
        yield
    finally:
        conn.execute("ROLLBACK TO mboxer_policy_read")
        conn.execute("RELEASE mboxer_policy_read")


def resolve_message_classification(
    conn: sqlite3.Connection,
    message_id: int,
    config_default: str | None,
    *,
    override_profile: str | None = None,
) -> dict[str, Any] | None:
    """Select greatest confidence, then explicit message rules over inheritance.

    NULL confidence is unranked and yields to any numeric confidence. Equally
    ranked rows must agree on the effective export policy; an explicit run
    override can resolve that ambiguity. Compatible ties retain the oldest
    metadata row. Evidence is never deleted, and only one row is kept in memory.
    """
    if override_profile is not None and override_profile not in EXPORT_PROFILES:
        raise ExportPolicyConflict("Invalid explicit export profile; choose a supported profile.")
    chosen: dict[str, Any] | None = None
    best_rank: tuple[float, bool] | None = None
    selected_policy: str | None = None
    conflict = False
    # Match the classification to its message's account even for unscoped
    # exports. The message index bounds this lookup to one message's evidence.
    with closing(conn.execute(
        "SELECT c.category_path, c.sensitivity, c.export_profile, c.confidence, c.classifier_type "
        "FROM classifications c JOIN messages m ON m.id = c.message_db_id "
        "WHERE c.message_db_id = ? AND c.target_type = 'message' "
        "AND c.account_id IS m.account_id ORDER BY c.id",
        (message_id,),
    )) as rows:
        for row in rows:
            confidence = row[3]
            if confidence is None:
                score = -math.inf
            elif isinstance(confidence, (int, float)) and math.isfinite(confidence):
                score = float(confidence)
            else:
                raise ExportPolicyConflict(
                    f"Invalid classification confidence for message {message_id}; review its classifications."
                )
            rank = (score, row[4] in {"rule", "rule_hint"})
            effective = resolve_export_profile(override_profile or row[2], config_default)
            if best_rank is None or rank > best_rank:
                chosen = dict(zip(
                    ("category_path", "sensitivity", "export_profile", "confidence", "classifier_type"),
                    row,
                ))
                best_rank, selected_policy, conflict = rank, effective, False
            elif rank == best_rank and effective != selected_policy:
                conflict = True
    if conflict:
        raise ExportPolicyConflict(
            f"Conflicting export policies for message {message_id}; "
            "resolve its classifications or choose an explicit --export-profile."
        )
    return chosen
