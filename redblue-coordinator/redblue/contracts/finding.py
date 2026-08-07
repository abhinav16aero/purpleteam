"""The Vigil canonical finding — the platform's most important contract (plan 05 §1, §2).

Every sensor alert and every red action becomes one of these before blue can act. The model
ENFORCES the plan-05 §1.5 drift rules so a producer can't silently drop data:
  * extra top-level fields are FORBIDDEN (a stray `technique`/`host` raises → forces it into
    mitre_predictions / entity_context)
  * mitre_predictions keys are coerced to technique-IDs only (tactic-names dropped, §1.4)
  * embedding is padded/truncated to 768; anomaly_score clamped 0-1; entity_context plural→singular
"""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMBEDDING_DIM = 768                       # vigil models.py EMBEDDING_DIM
ID_HASH_WIDTH = 16                        # vigil ingestion_service.py (sha256[:16])
TECHNIQUE_RE = re.compile(r"^T\d{4}(\.\d{3})?$")
FINDING_ID_RE = re.compile(r"^f-\d{8}-[0-9a-f]{16}$")

# plural-list + alias → scalar canonical key (plan 05 §1.3; mirrors Vigil ENTITY_FIELD_ALIASES).
_ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "src_ip": ("src_ip", "source_ip", "srcip", "ip1", "saddr", "focal_ip", "src_ips"),
    "dst_ip": ("dst_ip", "dest_ip", "destination_ip", "dstip", "ip2", "daddr", "engaged_ip", "dest_ips"),
    "src_port": ("src_port", "source_port", "sport", "srcport"),
    "dst_port": ("dst_port", "dest_port", "destination_port", "dport", "dstport"),
    "proto": ("proto", "protocol", "ip_proto"),
}


def _date(ts: Any | None) -> str:
    if isinstance(ts, datetime):
        return ts.strftime("%Y%m%d")
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y%m%d")
        except ValueError:
            pass
    return datetime.now(UTC).strftime("%Y%m%d")


def _iso(ts: Any | None) -> str:
    if isinstance(ts, datetime):
        return ts.astimezone(UTC).isoformat()
    if isinstance(ts, str) and ts:
        return ts
    return datetime.now(UTC).isoformat()


def make_finding_id(data_source: str, stable_key: str, ts: Any | None = None) -> str:
    """Canonical `f-<YYYYMMDD>-<sha256[:16]>` (plan 05 §2.1 / 00 §7)."""
    digest = hashlib.sha256(f"{data_source}:{stable_key}".encode()).hexdigest()[:ID_HASH_WIDTH]
    return f"f-{_date(ts)}-{digest}"


def _scalar(v: Any) -> Any:
    return (v[0] if v else None) if isinstance(v, (list, tuple)) else v


def normalize_entity_context(ec: dict | None) -> dict:
    """Fold plural-list/alias keys into the singular canonical keys the correlator reads (§1.3, §8)."""
    ec = dict(ec or {})
    for canon, aliases in _ENTITY_ALIASES.items():
        if ec.get(canon) not in (None, "", []):
            ec[canon] = _scalar(ec[canon])
            continue
        for a in aliases:
            if ec.get(a) not in (None, "", []):
                ec[canon] = _scalar(ec[a])
                break
    return {k: v for k, v in ec.items() if v is not None}


def _sev_score(severity: str | None) -> float:
    return {"critical": 0.95, "high": 0.8, "medium": 0.5, "low": 0.2}.get((severity or "").lower(), 0.5)


class CanonicalFinding(BaseModel):
    """The exact 13-field ingest contract for Vigil's `ingest_finding` (plan 05 §1.2)."""

    model_config = ConfigDict(extra="forbid")   # enforce the §1.5 drift trap

    finding_id: str
    data_source: str
    timestamp: str
    status: str = "new"
    external_id: str | None = None
    severity: str | None = None
    anomaly_score: float = 0.0
    mitre_predictions: dict[str, float] = Field(default_factory=dict)
    embedding: list[float] = Field(default_factory=lambda: [0.0] * EMBEDDING_DIM)
    description: str | None = None
    entity_context: dict[str, Any] = Field(default_factory=dict)
    evidence_links: list[dict] | None = None
    cluster_id: str | None = None

    @field_validator("finding_id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not FINDING_ID_RE.match(v):
            raise ValueError(f"finding_id must be f-YYYYMMDD-<16 hex>, got {v!r}")
        return v

    @field_validator("mitre_predictions", mode="before")
    @classmethod
    def _clean_mitre(cls, v: Any) -> dict:
        # keep ONLY well-formed technique-IDs; tactic-names are dropped (plan 05 §1.4)
        return {k: float(s) for k, s in (v or {}).items() if isinstance(k, str) and TECHNIQUE_RE.match(k)}

    @field_validator("embedding", mode="before")
    @classmethod
    def _pad_embedding(cls, v: Any) -> list[float]:
        vec = [float(x) for x in (v or [])]
        if len(vec) < EMBEDDING_DIM:
            vec = vec + [0.0] * (EMBEDDING_DIM - len(vec))
        return vec[:EMBEDDING_DIM]

    @field_validator("anomaly_score")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("entity_context", mode="before")
    @classmethod
    def _norm_ec(cls, v: Any) -> dict:
        return normalize_entity_context(v)

    def to_ingest(self) -> dict:
        """The dict Vigil's `ingest_finding` accepts. `to_ingest()` == the wire payload."""
        return self.model_dump()


def finding_from_decepticon(
    *,
    engagement_id: str,
    red_action_id: str,
    technique_ids: list[str],
    target: str | None = None,
    src: str | None = None,
    severity: str | None = None,
    description: str | None = None,
    ts: Any | None = None,
    tenant_id: str | None = None,
    extra_ctx: dict | None = None,
) -> CanonicalFinding:
    """Map a Decepticon red finding → CanonicalFinding (plan 05 §2). `external_id` is the real dedup key."""
    external_id = f"{engagement_id}:{red_action_id}"
    ctx: dict[str, Any] = {
        "engagement_id": engagement_id, "tenant_id": tenant_id, "red_action_id": red_action_id,
        "dst_ip": target, "src_ip": src, "red_source": "decepticon",
    }
    ctx.update(extra_ctx or {})
    return CanonicalFinding(
        finding_id=make_finding_id("decepticon", external_id, ts),
        external_id=external_id,
        data_source="decepticon",
        timestamp=_iso(ts),
        severity=(severity or "medium").lower(),
        anomaly_score=_sev_score(severity),
        # red is ground truth but NOT self-scored 1.0 — leave room for blue's mitre_analyst
        mitre_predictions={t: 0.7 for t in technique_ids},
        description=description or "Decepticon finding",
        entity_context=ctx,
        cluster_id=engagement_id,          # indexed per-engagement filter (plan 05 §8)
    )
