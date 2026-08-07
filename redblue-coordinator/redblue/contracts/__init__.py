"""redblue.contracts — the canonical cross-boundary data contracts (plan 05).

Single source of truth for every schema that crosses a component boundary: the connectors (06),
the loop/scoring (07), and governance/evidence (08) all code against these typed models. Data
shapes only — logic (scoring, policy, hashing) lives in the sibling packages and imports from here.
"""
from .correlation import CORRELATION_WINDOW_S, MatchState, correlate
from .engagement import (
    Engagement,
    EngagementStatus,
    GapItem,
    PerFindingScore,
    Scorecard,
    TechniqueScore,
    build_scorecard,
)
from .events import EngagementEvent, EventType
from .finding import (
    EMBEDDING_DIM,
    FINDING_ID_RE,
    ID_HASH_WIDTH,
    TECHNIQUE_RE,
    CanonicalFinding,
    finding_from_decepticon,
    make_finding_id,
    normalize_entity_context,
)
from .governance import (
    GENESIS_HASH,
    ActionStatus,
    ActionType,
    EvidenceRecord,
    Tier,
    TieredAutonomyDecision,
    compute_this_hash,
    payload_hash,
    verify_chain,
)
from .graph import ENGAGEMENT_PROP, EdgeKind, KGEdge, KGNode, NodeKind

__all__ = [
    "CORRELATION_WINDOW_S",
    "EMBEDDING_DIM",
    "ENGAGEMENT_PROP",
    "FINDING_ID_RE",
    "GENESIS_HASH",
    "ID_HASH_WIDTH",
    "TECHNIQUE_RE",
    "ActionStatus",
    "ActionType",
    "CanonicalFinding",
    "EdgeKind",
    "Engagement",
    "EngagementEvent",
    "EngagementStatus",
    "EventType",
    "EvidenceRecord",
    "GapItem",
    "KGEdge",
    "KGNode",
    "MatchState",
    "NodeKind",
    "PerFindingScore",
    "Scorecard",
    "TechniqueScore",
    "Tier",
    "TieredAutonomyDecision",
    "build_scorecard",
    "compute_this_hash",
    "correlate",
    "finding_from_decepticon",
    "make_finding_id",
    "normalize_entity_context",
    "payload_hash",
    "verify_chain",
]
