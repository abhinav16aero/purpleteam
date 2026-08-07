"""Vigil REST client — the blue drive-points (plan 06 §3.2).

The findings seam uses Vigil's EXISTING `/api/ingest/ingest-string` (plan 06 §1.5) — zero engine
patch — with the coordinator building the CanonicalFinding via `redblue.contracts.finding_from_decepticon`.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from ..contracts import CanonicalFinding


def finding_ingest_payload(finding: CanonicalFinding) -> dict[str, str]:
    """The exact form-encoded body `/api/ingest/ingest-string` expects. Pure — testable."""
    return {"data": json.dumps(finding.to_ingest()), "format": "json", "data_type": "finding"}


class VigilClient:
    def __init__(self, base_url: str = "http://backend:6987", token: str | None = None,
                 timeout: float = 30.0):
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self._base, headers=self._headers, timeout=self._timeout)

    # ── findings (red → blue) ──
    def push_finding(self, finding: CanonicalFinding) -> dict:
        with self._client() as c:
            r = c.post("/api/ingest/ingest-string", data=finding_ingest_payload(finding))
            r.raise_for_status()
            return r.json()

    def list_findings(self, data_source: str | None = None, limit: int = 50) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if data_source:
            params["data_source"] = data_source
        with self._client() as c:
            r = c.get("/api/findings", params=params)
            r.raise_for_status()
            d = r.json()
            return d if isinstance(d, list) else d.get("findings", d.get("data", []))

    # ── drive a blue playbook / investigation ──
    def trigger_workflow(self, workflow_id: str, finding_id: str | None = None,
                         case_id: str | None = None, triggered_by: str = "coordinator") -> dict:
        payload: dict[str, Any] = {"triggered_by": triggered_by}
        if finding_id:
            payload["finding_id"] = finding_id
        if case_id:
            payload["case_id"] = case_id
        with self._client() as c:
            r = c.post(f"/api/workflows/{workflow_id}/execute", json=payload)
            r.raise_for_status()
            return r.json()

    # ── HITL / approvals (the governance surface) ──
    def pending_approvals(self) -> list[dict]:
        with self._client() as c:
            r = c.get("/api/approvals/pending")
            r.raise_for_status()
            return r.json()

    def approve(self, action_id: str, approved_by: str = "redblue-coordinator") -> dict:
        with self._client() as c:
            r = c.post(f"/api/approvals/{action_id}/approve", json={"approved_by": approved_by})
            r.raise_for_status()
            return r.json()

    def reject(self, action_id: str, reason: str) -> dict:
        with self._client() as c:
            r = c.post(f"/api/approvals/{action_id}/reject", json={"reason": reason})
            r.raise_for_status()
            return r.json()

    def health(self) -> bool:
        try:
            with self._client() as c:
                return c.get("/api/health").status_code == 200
        except httpx.HTTPError:
            return False
