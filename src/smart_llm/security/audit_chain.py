"""Tamper-evident hash-chaining for agent-action audit records.

The tool-policy gate emits an ``agent_action_audit`` record per tool decision
(``args`` already stored as a SHA-256 digest, never raw). Those records were
independently hashed for content correlation but **not chained** — a row could
be altered or deleted without detection.

This links each record to the previous one: ``record_hash = sha256(prev_hash ||
canonical(record))``. Any edit, deletion, or reordering breaks the chain, which
:func:`verify_chain` detects. The chaining is a pure, in-memory helper — the host
persists ``prev_hash`` / ``record_hash`` alongside each audit row and, across
runs, seeds an :class:`AuditChain` with the last persisted ``record_hash`` so the
whole history forms one verifiable chain.
"""

import hashlib
import json
from typing import Any

# 64 zeros — the chain seed (no genuine record_hash is all-zero).
GENESIS = "0" * 64

# Fields that carry the chain itself and must be excluded from the hashed body.
_CHAIN_FIELDS = ("prev_hash", "record_hash")


def canonical(record: dict[str, Any]) -> str:
    """Deterministic serialization of a record's content (excluding chain fields)."""
    payload = {k: v for k, v in record.items() if k not in _CHAIN_FIELDS}
    return json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)


def compute_hash(prev_hash: str, record: dict[str, Any]) -> str:
    """``sha256(prev_hash || canonical(record))`` — the link for one record."""
    return hashlib.sha256(
        f"{prev_hash}\n{canonical(record)}".encode("utf-8")
    ).hexdigest()


class AuditChain:
    """Running chain head. ``stamp`` links a record and advances the head.

    One instance per agent run maintains the chain across that run's audit
    records; seed ``head`` with the last persisted ``record_hash`` to continue a
    tenant's chain across runs."""

    def __init__(self, head: str = GENESIS):
        self.head = head or GENESIS

    def stamp(self, record: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of ``record`` with ``prev_hash`` + ``record_hash`` set,
        advancing the chain head."""
        prev = self.head
        record_hash = compute_hash(prev, record)
        out = dict(record)
        out["prev_hash"] = prev
        out["record_hash"] = record_hash
        self.head = record_hash
        return out


def verify_chain(records: list[dict[str, Any]], *, head: str = GENESIS) -> bool:
    """True iff ``records`` form an unbroken chain from ``head`` — every
    ``prev_hash`` links to the prior ``record_hash`` and every ``record_hash``
    recomputes. A mutated, deleted, inserted, or reordered record fails."""
    prev = head or GENESIS
    for rec in records:
        if rec.get("prev_hash") != prev:
            return False
        if rec.get("record_hash") != compute_hash(prev, rec):
            return False
        prev = rec["record_hash"]
    return True


__all__ = ["AuditChain", "GENESIS", "canonical", "compute_hash", "verify_chain"]
