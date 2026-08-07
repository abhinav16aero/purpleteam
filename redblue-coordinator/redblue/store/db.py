"""Store factory + repository (plan 07 §6.2). SQLite MVP → Postgres (00 §6)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ..contracts import Engagement, EvidenceRecord
from .models import Base, EngagementRow, EvidenceRow, ScorecardRow


def make_engine(db_url: str):
    if db_url.startswith("sqlite") and (":memory:" in db_url or db_url.endswith("://")):
        # shared in-memory DB across sessions (tests)
        return create_engine(db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if db_url.startswith("sqlite"):
        return create_engine(db_url, connect_args={"check_same_thread": False})
    return create_engine(db_url)


class CoordinatorStore:
    def __init__(self, db_url: str = "sqlite://") -> None:
        self._engine = make_engine(db_url)
        Base.metadata.create_all(self._engine)
        self._Session: sessionmaker[Session] = sessionmaker(self._engine, expire_on_commit=False)

    # ── engagements ──
    def upsert_engagement(self, eng: Engagement, *, mode: str = "on_demand", ts: float = 0.0) -> None:
        with self._Session() as s:
            row = s.get(EngagementRow, eng.engagement_id)
            if row is None:
                row = EngagementRow(engagement_id=eng.engagement_id, created_at=ts)
                s.add(row)
            row.tenant_id = eng.tenant_id
            row.mode = mode
            row.status = eng.status.value if hasattr(eng.status, "value") else str(eng.status)
            row.scope = eng.scope
            row.target = eng.target
            row.roe_ref = eng.roe_ref
            row.thread_id = eng.decepticon.get("thread_id") or eng.engagement_id
            row.updated_at = ts
            s.commit()

    def set_status(self, engagement_id: str, status: str, ts: float = 0.0) -> None:
        with self._Session() as s:
            row = s.get(EngagementRow, engagement_id)
            if row:
                row.status = status
                row.updated_at = ts
                s.commit()

    def get_engagement(self, engagement_id: str) -> dict | None:
        with self._Session() as s:
            row = s.get(EngagementRow, engagement_id)
            return _eng_dict(row) if row else None

    def list_engagements(self, tenant_id: str | None = None,
                         status: str | None = None) -> list[dict]:
        stmt = select(EngagementRow)
        if tenant_id:
            stmt = stmt.where(EngagementRow.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(EngagementRow.status == status)
        with self._Session() as s:
            return [_eng_dict(r) for r in s.scalars(stmt)]

    # ── scorecards ──
    def upsert_scorecard(self, card: dict, ts: float = 0.0) -> None:
        with self._Session() as s:
            row = s.get(ScorecardRow, card["scorecard_id"])
            if row is None:
                row = ScorecardRow(scorecard_id=card["scorecard_id"], created_at=ts)
                s.add(row)
            row.engagement_id = card["engagement_id"]
            row.tenant_id = card["tenant_id"]
            row.version = card.get("version", 1)
            row.detection_rate = card.get("detection_rate")
            row.data = card
            s.commit()

    def get_scorecard(self, engagement_id: str, version: int | None = None) -> dict | None:
        stmt = select(ScorecardRow).where(ScorecardRow.engagement_id == engagement_id)
        stmt = (stmt.where(ScorecardRow.version == version) if version
                else stmt.order_by(ScorecardRow.version.desc()))
        with self._Session() as s:
            row = s.scalars(stmt).first()
            return row.data if row else None

    def list_scorecards(self, tenant_id: str | None = None) -> list[dict]:
        """The LATEST scorecard per engagement (for the posture aggregate, plan 09 §1.4)."""
        stmt = select(ScorecardRow)
        if tenant_id:
            stmt = stmt.where(ScorecardRow.tenant_id == tenant_id)
        with self._Session() as s:
            rows = s.scalars(stmt).all()
        latest: dict[str, ScorecardRow] = {}
        for r in rows:
            cur = latest.get(r.engagement_id)
            if cur is None or r.version > cur.version:
                latest[r.engagement_id] = r
        return [r.data for r in latest.values()]

    # ── evidence (query mirror of the chain) ──
    def save_evidence(self, records: list[EvidenceRecord]) -> None:
        with self._Session() as s:
            # scalars() over a single column yields the values directly (ints), not rows.
            existing = set(s.scalars(
                select(EvidenceRow.seq).where(
                    EvidenceRow.engagement_id == (records[0].engagement_id if records else "")
                )
            ))
            for rec in records:
                if rec.seq in existing:
                    continue
                s.add(EvidenceRow(
                    engagement_id=rec.engagement_id, tenant_id=rec.tenant_id, seq=rec.seq, ts=rec.ts,
                    actor=rec.actor, record_type=rec.record_type, ref=rec.ref,
                    payload_hash=rec.payload_hash, prev_hash=rec.prev_hash, this_hash=rec.this_hash,
                ))
            s.commit()

    def get_evidence(self, engagement_id: str) -> list[dict]:
        stmt = select(EvidenceRow).where(
            EvidenceRow.engagement_id == engagement_id
        ).order_by(EvidenceRow.seq)
        with self._Session() as s:
            return [_ev_dict(r) for r in s.scalars(stmt)]


def _eng_dict(r: EngagementRow) -> dict:
    return {"engagement_id": r.engagement_id, "tenant_id": r.tenant_id, "mode": r.mode,
            "status": r.status, "scope": r.scope, "target": r.target, "roe_ref": r.roe_ref,
            "thread_id": r.thread_id, "created_at": r.created_at, "updated_at": r.updated_at}


def _ev_dict(r: EvidenceRow) -> dict[str, Any]:
    return {"seq": r.seq, "ts": r.ts, "actor": r.actor, "record_type": r.record_type,
            "ref": r.ref, "payload_hash": r.payload_hash, "prev_hash": r.prev_hash,
            "this_hash": r.this_hash}
