"""Coordinator evidence store — append-only, hash-chained (plan 07 §6.2; WORM hardening → plan 08).

MVP is in-memory + per-engagement chains (tenant isolation). The hashing/verification is the
contracts.governance chain (already tested). Plan 08 swaps the backing for a WORM/tamper-evident
persistent store; the append/verify contract pinned here does not change.
"""
from __future__ import annotations

import threading
import time

from ..contracts import GENESIS_HASH, EvidenceRecord, verify_chain


class EvidenceStore:
    def __init__(self) -> None:
        self._chains: dict[str, list[EvidenceRecord]] = {}
        self._lock = threading.Lock()

    def append(
        self, *, engagement_id: str, tenant_id: str, actor: str, record_type: str,
        payload: dict, ref: dict | None = None, ts: float | None = None,
    ) -> EvidenceRecord:
        with self._lock:
            chain = self._chains.setdefault(engagement_id, [])
            prev = chain[-1].this_hash if chain else GENESIS_HASH
            rec = EvidenceRecord.create(
                seq=len(chain), ts=ts if ts is not None else time.time(),
                engagement_id=engagement_id, tenant_id=tenant_id, actor=actor,
                record_type=record_type, payload=payload, prev_hash=prev, ref=ref,
            )
            chain.append(rec)
            return rec

    def chain(self, engagement_id: str) -> list[EvidenceRecord]:
        return list(self._chains.get(engagement_id, []))

    def verify(self, engagement_id: str) -> bool:
        return verify_chain(self.chain(engagement_id))
