"""Health + liveness (plan 07 §6.1)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "redblue-coordinator"}
