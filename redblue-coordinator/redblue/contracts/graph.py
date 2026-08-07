"""Shared attack-graph schema — Decepticon's engagement-scoped Neo4j (plan 05 §4).

Single source of truth for ground truth; blue reads it and may annotate it (DetectionFired).
Node/Edge kind VALUES are the Neo4j labels/relationship-types used directly (no translation).
This is the loop-MVP subset of `Decepticon/.../types/kg.py`; the full AD/ADCS/Solidity sets are
not consumed by the loop.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

ENGAGEMENT_PROP = "engagement"      # the enforced multi-tenant scope property (store.py binds $engagement)


class NodeKind(str, Enum):
    # Infrastructure / progression (core loop subset)
    HOST = "Host"
    SERVICE = "Service"
    TECHNIQUE = "Technique"
    CROWN_JEWEL = "CrownJewel"
    ATTACK_PATH = "AttackPath"
    FINDING = "Finding"
    TECHNOLOGY = "Technology"        # AI attack surface (Ollama/vLLM/LiteLLM fingerprints)
    # Defense (natively purple — blue write-back needs no schema change)
    DETECTION_FIRED = "DetectionFired"
    DEFENSE_ACTION = "DefenseAction"


class EdgeKind(str, Enum):
    EXPLOITS = "EXPLOITS"
    LEADS_TO = "LEADS_TO"
    REACHES = "REACHES"
    # Defense
    DETECTED = "DETECTED"
    USES_RULE = "USES_RULE"


class KGNode(BaseModel):
    id: str                          # sha1("<kind>::<key>")[:16]
    kind: str                        # NodeKind value (raw str for forward-compat)
    label: str
    props: dict[str, Any] = Field(default_factory=dict)   # carries `engagement`, provenance, etc.

    @property
    def engagement(self) -> str | None:
        return self.props.get(ENGAGEMENT_PROP)


class KGEdge(BaseModel):
    id: str
    src: str
    dst: str
    kind: str
    weight: float = 1.0
    props: dict[str, Any] = Field(default_factory=dict)


def scoped_read_cypher(match: str = "(n)") -> str:
    """Every KG read MUST bind $engagement (store.py enforces this). Helper to keep reads scoped."""
    return f"MATCH {match} WHERE n.{ENGAGEMENT_PROP} = $engagement RETURN n"
