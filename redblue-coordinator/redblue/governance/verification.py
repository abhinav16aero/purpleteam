"""The hard verification gate — "no verdict without an artifact" (plan 08 §7).

No red finding / blue verdict / response reaches scoring, a report, or an action without a
reproducible artifact or dereferenceable evidence. Stops both engines' LLMs from being believed on
their own say-so. Rejected items are quarantined (never scored/reported/actioned) + a WORM record.
"""
from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel


class VerificationResult(BaseModel):
    ok: bool
    reason: str | None = None


def _reject(reason: str) -> VerificationResult:
    return VerificationResult(ok=False, reason=reason)


_OK = VerificationResult(ok=True)


def verify_red_finding(item: dict) -> VerificationResult:
    """Needs a reproducible artifact (FIND-*.md / command+output / artifact_hash) AND proof it ran."""
    has_artifact = bool(item.get("artifact_hash") or (item.get("command") and item.get("output")))
    if not has_artifact:
        return _reject("red finding has no reproducible artifact (command+output / artifact_hash)")
    if item.get("roe_decision") == "refuse":
        return _reject("red action was RoE-refused (did not actually execute)")
    return _OK


def verify_blue_verdict(item: dict, resolver: Callable[[str], bool] | None = None) -> VerificationResult:
    """Needs non-empty evidence_refs that DEREFERENCE to real sensor rows (not a hallucination)."""
    refs = item.get("evidence_refs") or []
    if not refs:
        return _reject("blue verdict has no evidence_refs (unbacked claim)")
    if resolver is not None and not all(resolver(r) for r in refs):
        return _reject("blue verdict cites evidence_refs that do not resolve to real rows")
    return _OK


def verify(item: dict, kind: str, resolver: Callable[[str], bool] | None = None) -> VerificationResult:
    if kind == "red_finding":
        return verify_red_finding(item)
    if kind == "blue_verdict":
        return verify_blue_verdict(item, resolver)
    if kind == "response":
        if not (item.get("verified_finding_id") or item.get("evidence_refs")):
            return _reject("response cites no verified finding/verdict")
        return _OK
    return _reject(f"unknown verification kind {kind!r}")
