"""Tenant asset inventory + the boundary predicate (plan 08 §3.2/§3.3).

`crosses_boundary` is evaluated FIRST in the policy engine and can only ratchet the tier UP to
T2_NEVER_AUTO. Unknown targets are treated as foreign (fail-closed). Control-plane assets — the
sovereign cloud's brain — are out of scope for red and untouchable-by-auto for blue, always.
"""
from __future__ import annotations

import re

from .envelope import ActionEnvelope, Boundary

# The sovereign-cloud control plane (plan 08 §3.2) — host tokens matched by exact or suffix.
DEFAULT_CONTROL_PLANE: frozenset[str] = frozenset({
    "ollama", "litellm", "bifrost", "neo4j", "redblue-coordinator", "coordinator",
    "langgraph", "wazuh.manager", "wazuh-manager", "suricata", "falco", "backend",
    "169.254.169.254", "metadata.google.internal", "kubernetes.default",
})


class AssetMap:
    def __init__(self, control_plane: frozenset[str] | None = None,
                 tenant_assets: dict[str, str] | None = None) -> None:
        self._cp = set(control_plane if control_plane is not None else DEFAULT_CONTROL_PLANE)
        self._assets = dict(tenant_assets or {})          # raw (ip/host/user) → owning tenant_id

    def add_asset(self, raw: str, tenant_id: str) -> None:
        self._assets[raw] = tenant_id

    def is_control_plane(self, raw: str) -> bool:
        # Case-insensitive (DNS is), and tokenize on '.', ':', '_', '-' so hyphenated deployment
        # hostnames match — the real container/service names are 'redblue-ollama', 'vigil-backend',
        # 'deeptempo-neo4j', etc. Errs toward over-matching (a tenant host named like a control-plane
        # component is blocked, not auto-run) — the safe direction. Seed exact hosts per deployment.
        low = str(raw).lower()
        if low in self._cp:
            return True
        tokens = set(re.split(r"[.:_\-/]", low))
        return any(cp in tokens or low.endswith("." + cp) for cp in self._cp)

    def tenant_of(self, raw: str) -> str | None:
        return self._assets.get(raw)

    def crosses_boundary(self, env: ActionEnvelope) -> Boundary:
        raw = env.target.get("raw") if env.target else None
        if not raw:
            return Boundary.TENANT                          # fail-closed: no target ⇒ assume foreign
        if self.is_control_plane(str(raw)):
            return Boundary.CONTROL_PLANE
        owner = self.tenant_of(str(raw))
        if owner is None:
            return Boundary.TENANT                          # unknown target ⇒ assume foreign
        if owner != env.tenant_id:
            return Boundary.TENANT
        return Boundary.NONE
