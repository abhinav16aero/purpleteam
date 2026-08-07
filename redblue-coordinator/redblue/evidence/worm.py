"""WORM-hardened evidence store (plan 08 §4) — per-tenant HMAC + tamper localization.

Extends the P4 hash chain with a per-tenant HMAC (so a tenant's chain can't be forged without its
key) and `verify_ledger` returning `first_bad_seq` (which record broke). Lifted from Decepticon's
proven `_audit_sink.py` construction. The persistent append-only DB backing + Object-Lock mirror
(§4.2) is a later slice; the chain semantics are fixed here.
"""
from __future__ import annotations

import hashlib
import hmac

from ..contracts import GENESIS_HASH, compute_this_hash
from .store import EvidenceStore


class WormEvidenceStore(EvidenceStore):
    def __init__(self, hmac_keys: dict[str, str] | None = None) -> None:
        super().__init__()
        self._keys = dict(hmac_keys or {})                 # tenant_id → hex key
        self._hmacs: dict[str, list[str]] = {}             # engagement_id → [hmac per seq]

    def append(self, *, engagement_id, tenant_id, actor, record_type, payload, ref=None, ts=None):
        rec = super().append(engagement_id=engagement_id, tenant_id=tenant_id, actor=actor,
                             record_type=record_type, payload=payload, ref=ref, ts=ts)
        key = self._keys.get(tenant_id)
        tag = (hmac.new(bytes.fromhex(key), rec.this_hash.encode(), hashlib.sha256).hexdigest()
               if key else "")
        self._hmacs.setdefault(engagement_id, []).append(tag)
        return rec

    def verify_ledger(self, engagement_id: str) -> dict:
        """Return {ok, first_bad_seq}. Walks prev-links, recomputes hashes, checks HMAC when keyed."""
        chain = self.chain(engagement_id)
        tags = self._hmacs.get(engagement_id, [])
        prev = GENESIS_HASH
        for i, r in enumerate(chain):
            if r.prev_hash != prev:
                return {"ok": False, "first_bad_seq": r.seq}
            if r.this_hash != compute_this_hash(r.prev_hash, r.payload_hash, r.seq, r.ts, r.record_type):
                return {"ok": False, "first_bad_seq": r.seq}
            key = self._keys.get(r.tenant_id)
            if key:
                expect = hmac.new(bytes.fromhex(key), r.this_hash.encode(), hashlib.sha256).hexdigest()
                if i >= len(tags) or not hmac.compare_digest(expect, tags[i]):
                    return {"ok": False, "first_bad_seq": r.seq}
            prev = r.this_hash
        return {"ok": True, "first_bad_seq": None}
