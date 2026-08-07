"""Coordinator application store — SQLAlchemy models (plan 07 §6.2).

The LangGraph checkpointer owns loop state; THIS store owns the durable business records the API
queries. MVP tables: engagements, scorecards, evidence (query mirror of the hash chain).
response_actions + correlations land with the governance work (P5).
"""
from __future__ import annotations

from sqlalchemy import JSON, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EngagementRow(Base):
    __tablename__ = "engagements"
    engagement_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="on_demand")
    status: Mapped[str] = mapped_column(String(24), default="scheduled", index=True)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    roe_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[float] = mapped_column(Float, default=0.0)


class ScorecardRow(Base):
    __tablename__ = "scorecards"
    __table_args__ = (UniqueConstraint("engagement_id", "version", name="uq_scorecard_engagement_version"),)
    scorecard_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    detection_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)          # the full Scorecard.model_dump()
    created_at: Mapped[float] = mapped_column(Float, default=0.0)


class EvidenceRow(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("engagement_id", "seq", name="uq_evidence_engagement_seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[float] = mapped_column(Float)
    actor: Mapped[str] = mapped_column(String(32))
    record_type: Mapped[str] = mapped_column(String(48))
    ref: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(80))
    prev_hash: Mapped[str] = mapped_column(String(80))
    this_hash: Mapped[str] = mapped_column(String(80))
