"""Per-tenant policy (plan 08 §1.4). Overlays may only RAISE a tier; new tenants are safe-by-default.

`force_manual=True` by default ⇒ a tenant opts *into* autonomy, never out of it (00 §10). The
coordinator owns per-tenant semantics because Vigil's native force_manual knob is system-wide (§3).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..contracts import Tier


class TenantPolicy(BaseModel):
    tenant_id: str
    force_manual: bool = True                              # safe-by-default (plan 08 §1.4)
    overrides: dict[str, Tier] = Field(default_factory=dict)   # action kind → minimum tier (raise-only)
    required_approvers_t2: int = 2                         # two-person rule for T2_NEVER_AUTO


class TenantPolicyRegistry:
    def __init__(self, policies: list[TenantPolicy] | None = None) -> None:
        self._p: dict[str, TenantPolicy] = {p.tenant_id: p for p in (policies or [])}

    def get(self, tenant_id: str) -> TenantPolicy:
        return self._p.get(tenant_id) or TenantPolicy(tenant_id=tenant_id)

    def put(self, policy: TenantPolicy) -> None:
        self._p[policy.tenant_id] = policy
