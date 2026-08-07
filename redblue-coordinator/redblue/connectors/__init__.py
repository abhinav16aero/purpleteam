"""redblue.connectors — engine/infra I/O (plan 06). Every call idempotent + retried at the loop layer.

- vigil.py       Vigil REST client (push findings, trigger workflows, approvals)
- event_tail.py  tail Decepticon events.jsonl → EngagementEvent (the red timeline)
- kg_reader.py   read-only, engagement-scoped Neo4j reader (shared attack graph)
- red_driver.py  drive Decepticon over the LangGraph :2024 API
"""
from .event_tail import EventTail
from .kg_reader import RedKGReader, ScopeError, require_scoped
from .red_driver import RedDriver, valid_engagement
from .vigil import VigilClient, finding_ingest_payload

__all__ = [
    "EventTail",
    "RedDriver",
    "RedKGReader",
    "ScopeError",
    "VigilClient",
    "finding_ingest_payload",
    "require_scoped",
    "valid_engagement",
]
