"""Node 4 — collect_detections (plan 07 §3.3, plan 08 §6.3/§7).

Pull attacked ground-truth (AttackSource) and sensor-origin blue detections (DetectionSource) inside
the window, then run detections through the AI-native defenses BEFORE they can reach scoring:
  * injection shield (§6) — a BLOCK (a real injection signature in the log/finding text) quarantines
    the detection so a poisoned log can't corrupt the scorecard; a FLAG is kept but surfaced.
  * verification gate (§7) — a detection with no dereferenceable evidence is quarantined (unbacked).
Both are optional (absent ⇒ P4/P5 behavior). Quarantines + flags are evidence-logged.
"""
from __future__ import annotations

from ...governance.injection import ScanAction
from ...governance.verification import verify_blue_verdict
from ..ports import Deps
from ..state import LoopState


def make_collect_detections(deps: Deps):
    async def collect_detections(state: LoopState) -> dict:
        eng, tenant = state["engagement_id"], state["tenant_id"]
        window = state.get("window", {})
        attacks = deps.attack_source.attacks(eng, window)
        raw = deps.detection_source.detections(eng, window)

        clean: list[dict] = []
        quarantined: list[dict] = []
        flags: list[dict] = []
        refs: list[str] = []

        for d in raw:
            # ── injection shield (§6) ──
            text = d.get("text") or ""
            if deps.shield is not None and text:
                v = deps.shield.scan_untrusted_text(text, context={"engagement": eng})
                if v.action == ScanAction.BLOCK:
                    rec = deps.evidence.append(
                        engagement_id=eng, tenant_id=tenant, actor="coordinator",
                        record_type="injection_block", ts=deps.clock(),
                        payload={"finding_id": d.get("finding_id"), "matched": v.matched,
                                 "scanner": v.scanner})
                    refs.append(rec.this_hash)
                    quarantined.append({"finding_id": d.get("finding_id"), "reason": "injection",
                                        "matched": v.matched})
                    continue
                if v.action == ScanAction.FLAG:
                    flags.append({"finding_id": d.get("finding_id"), "detail": v.detail})

            # ── verification gate (§7) — no verdict without dereferenceable evidence ──
            if deps.verify_detections:
                res = verify_blue_verdict(
                    {"evidence_refs": d.get("evidence_refs")
                     or ([d["finding_id"]] if d.get("finding_id") else [])},
                    deps.evidence_resolver)
                if not res.ok:
                    rec = deps.evidence.append(
                        engagement_id=eng, tenant_id=tenant, actor="coordinator",
                        record_type="verification_reject", ts=deps.clock(),
                        payload={"finding_id": d.get("finding_id"), "reason": res.reason})
                    refs.append(rec.this_hash)
                    quarantined.append({"finding_id": d.get("finding_id"), "reason": "unverified",
                                        "detail": res.reason})
                    continue

            clean.append(d)

        rec = deps.evidence.append(
            engagement_id=eng, tenant_id=tenant, actor="coordinator",
            record_type="telemetry.collected", ts=deps.clock(),
            payload={"attacks": len(attacks), "detections": len(clean),
                     "quarantined": len(quarantined), "flagged": len(flags), "window": window})
        refs.append(rec.this_hash)
        return {"attacks": attacks, "detections": clean, "quarantined": quarantined,
                "injection_flags": flags, "evidence_refs": refs}

    return collect_detections
