"""Kill switch — global / per-tenant / .abort (plan 08 §5). Un-gated (stopping never needs approval).

Sets an in-process HALT flag (new actions blocked in <2s), best-effort writes Decepticon's
`<workspace>/.abort` marker (halts the next gated red tool call), and logs a KillSwitchRecord to WORM.
In-flight LangGraph thread cancellation is the live slice (needs the :2024 API).
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..evidence.store import EvidenceStore


class KillSwitch:
    def __init__(self, evidence: EvidenceStore | None = None,
                 workspace_root: str = "/workspace") -> None:
        self._global = False
        self._tenants: set[str] = set()
        self._evidence = evidence
        self._root = Path(workspace_root)

    def is_halted(self, tenant_id: str | None = None) -> bool:
        return self._global or (tenant_id is not None and tenant_id in self._tenants)

    def kill(self, *, scope: str, by: str, reason: str, tenant_id: str | None = None,
             engagement_ids: Iterable[str] = ()) -> dict:
        if scope == "global":
            self._global = True
        elif scope == "tenant" and tenant_id:
            self._tenants.add(tenant_id)
        else:
            raise ValueError("scope must be 'global', or 'tenant' with tenant_id")

        aborted: list[str] = []
        for eng in engagement_ids:                          # best-effort .abort (live)
            try:
                marker = self._root / eng / ".abort"
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(f"killed by {by}: {reason}\n")
                aborted.append(eng)
            except OSError:
                pass

        if self._evidence is not None:
            self._evidence.append(
                engagement_id=(tenant_id or "*"), tenant_id=(tenant_id or "*"),
                actor=f"human:{by}", record_type="kill_switch",
                payload={"scope": scope, "reason": reason, "aborted_engagements": aborted},
            )
        return {"scope": scope, "tenant_id": tenant_id, "aborted": aborted, "halted": True}

    def clear(self, tenant_id: str | None = None) -> None:
        if tenant_id is None:
            self._global = False
        else:
            self._tenants.discard(tenant_id)
