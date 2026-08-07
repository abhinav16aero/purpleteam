"""The authoritative action → base-tier mapping (plan 08 §1.3). Data, not logic.

Per-tenant overlays and confidence/risk/boundary may only RAISE a tier above the base here.
"""
from __future__ import annotations

from ..contracts import ActionType, Tier

# Blue (Vigil) ActionTypes — the base tier BEFORE time-boxed / mutating / boundary adjustments.
BLUE_BASE_TIER: dict[str, Tier] = {
    ActionType.EXECUTE_SPL_QUERY.value: Tier.AUTO,     # read-only enrichment; mutating → raised (§1.3)
    ActionType.QUARANTINE_FILE.value: Tier.AUTO,       # one file, reversible
    ActionType.BLOCK_IP.value: Tier.AUTO,              # iff time-boxed; else raised
    ActionType.BLOCK_DOMAIN.value: Tier.AUTO,          # iff time-boxed; else raised
    ActionType.WAF_BLOCK.value: Tier.HUMAN,            # CF account-wide
    ActionType.GATEWAY_BLOCK.value: Tier.HUMAN,        # CF org-wide
    ActionType.ISOLATE_HOST.value: Tier.HUMAN,         # isolates a production workload
    ActionType.DISABLE_USER.value: Tier.HUMAN,
    ActionType.ACCESS_REVOKE.value: Tier.HUMAN,
    ActionType.WORKFLOW_PHASE.value: Tier.HUMAN,       # is itself an approval checkpoint
    ActionType.CUSTOM.value: Tier.HUMAN,               # unknown blast radius ⇒ never auto (fail-safe)
}

# Red (Decepticon) action classes — keyed off the objective's ATT&CK technique + tool.
RED_BASE_TIER: dict[str, Tier] = {
    "recon": Tier.AUTO,               # bounded by RoE enforce (scope + egress)
    "exploit": Tier.HUMAN,
    "cred_dump": Tier.HUMAN,          # T1003
    "c2_deploy": Tier.HUMAN,
    "lateral": Tier.HUMAN,
    "rule_push": Tier.HUMAN,          # sigma_to_*/yara_to_* → mutes real alerts
    "destruction": Tier.NEVER,        # T1485/T1486 — never on production
}

# Mutating-SPL tokens (parse & classify; do not trust the caller) — §1.3.
MUTATING_SPL_TOKENS: tuple[str, ...] = ("| delete", "| outputlookup", "| collect", "| sendemail")

_TIER_ORDER: dict[Tier, int] = {Tier.AUTO: 0, Tier.HUMAN: 1, Tier.NEVER: 2}


def max_tier(a: Tier, b: Tier) -> Tier:
    return a if _TIER_ORDER[a] >= _TIER_ORDER[b] else b


def is_mutating_spl(query: str | None) -> bool:
    q = (query or "").lower()
    return any(tok in q for tok in MUTATING_SPL_TOKENS)
