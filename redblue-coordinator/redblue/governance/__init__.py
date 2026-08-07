"""redblue.governance — tiered-autonomy policy engine, verification gate, kill switch (plan 08).

The single authoritative pre-action choke point. Deterministic code — an LLM never sets the tier.
"""
from .assets import DEFAULT_CONTROL_PLANE, AssetMap
from .envelope import ActionEnvelope, Boundary, Decision, PolicyDecision
from .injection import (
    HeuristicInjectionScanner,
    InjectionShield,
    ScanAction,
    ScanVerdict,
    VigilLlmHttpScanner,
)
from .injection_mcp import scan_untrusted_text
from .killswitch import KillSwitch
from .planner import default_response_planner
from .policy_engine import CONFIDENCE_GATE, PolicyEngine
from .policy_map import BLUE_BASE_TIER, RED_BASE_TIER, is_mutating_spl, max_tier
from .verification import VerificationResult, verify, verify_blue_verdict, verify_red_finding

__all__ = [
    "BLUE_BASE_TIER",
    "CONFIDENCE_GATE",
    "DEFAULT_CONTROL_PLANE",
    "RED_BASE_TIER",
    "ActionEnvelope",
    "AssetMap",
    "Boundary",
    "Decision",
    "HeuristicInjectionScanner",
    "InjectionShield",
    "KillSwitch",
    "PolicyDecision",
    "PolicyEngine",
    "ScanAction",
    "ScanVerdict",
    "VerificationResult",
    "VigilLlmHttpScanner",
    "default_response_planner",
    "is_mutating_spl",
    "max_tier",
    "scan_untrusted_text",
    "verify",
    "verify_blue_verdict",
    "verify_red_finding",
]
