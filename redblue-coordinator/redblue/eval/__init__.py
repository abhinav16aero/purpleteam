"""redblue.eval — the red-team-of-the-AI eval harness (plan 08 §8). Quality gate + demo asset."""
from .corpus import HELD_OUT_CORPUS, CaseKind, InjectionCase
from .harness import EvalHarness, InjectionEvalReport

__all__ = [
    "HELD_OUT_CORPUS",
    "CaseKind",
    "EvalHarness",
    "InjectionCase",
    "InjectionEvalReport",
]
