"""redblue.loop — the LangGraph closed-loop state machine (plan 07 §2).

    build_graph(deps, checkpointer)  → CompiledStateGraph
    Deps                             → the injected engine/infra seam (ports.py)
    LoopState                        → the channel schema
"""
from .checkpointer import make_checkpointer
from .graph import build_graph
from .ports import (
    AttackSource,
    CoverageOracle,
    Deps,
    DetectionSource,
    RedRunner,
)
from .state import LoopState

__all__ = [
    "AttackSource",
    "CoverageOracle",
    "Deps",
    "DetectionSource",
    "LoopState",
    "RedRunner",
    "build_graph",
    "make_checkpointer",
]
