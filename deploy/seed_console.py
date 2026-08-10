#!/usr/bin/env python3
"""seed_console.py — sovereign, dependency-free console seed (complements demo-seed.sh).

Populates the coordinator STORE directly — NO Neo4j, NO Vigil, NO red engine — so the console's
Overview · Posture · MITRE · Engagements · Evidence tabs light up with realistic multi-engagement,
multi-tenant data. It uses the REAL contracts (`build_scorecard`, the WORM hash-chain, the store
repository), so every shape is authentic — this is seeding, not faking.

For the Neo4j-backed Graph tab you still need `deploy/demo-seed.sh` (it drives the live loop through
the full stack). This script is the offline/air-gapped path for everything else.

Run it with the coordinator's venv, pointed at the SAME store the coordinator uses, e.g.:

    REDBLUE_DB_URL="sqlite:////data/redblue.db" \
      /app/.venv/bin/python deploy/seed_console.py            # inside the container / on the host

The running coordinator serves the new rows immediately (SQLite committed reads are visible across
connections). Idempotent: re-running upserts the same engagement/scorecard ids.
"""
from __future__ import annotations

import os
import time

from redblue.contracts import Engagement, EngagementStatus, MatchState, build_scorecard
from redblue.contracts.correlation import CORRELATION_WINDOW_S
from redblue.evidence.store import EvidenceStore
from redblue.store.db import CoordinatorStore

DB_URL = os.environ.get("REDBLUE_DB_URL", "sqlite:///./redblue.db")

# Human labels for a richer MITRE matrix in the console.
TECH = {
    "T1046": "Network Service Discovery",
    "T1190": "Exploit Public-Facing Application",
    "T1110": "Brute Force",
    "T1059": "Command & Scripting Interpreter",
    "T1611": "Escape to Host",
    "T1552.005": "Cloud Instance Metadata API",
    "T1210": "Exploitation of Remote Services",
    "T1548": "Abuse Elevation Control",
}

# Each engagement: (id, tenant, target_name, target_url, roe, [ (technique, entity, detected, mttd, tool) ])
HOUR = 3600
NOW = int(time.time())
ENGAGEMENTS = [
    ("eng-proto-dvwa-01", "proto", "DVWA", "http://10.20.0.9", "RoE-2026-014", NOW - 2 * HOUR, [
        ("T1046", "10.20.0.9", True, 11.2, "nmap"),
        ("T1190", "10.20.0.9", True, 9.4, "sqlmap"),
        ("T1110", "10.20.0.9", False, None, "hydra"),
    ]),
    ("eng-proto-k8s-02", "proto", "k8s-payments", "http://10.20.0.30", "RoE-2026-013", NOW - 6 * HOUR, [
        ("T1046", "10.20.0.30", True, 8.9, "nmap"),
        ("T1190", "10.20.0.30", True, 13.7, "nuclei"),
        ("T1059", "pod/api-7f9", True, 21.0, "exec"),
        ("T1611", "node/worker-2", False, None, "escape"),
    ]),
    ("eng-bfsi-ibank-03", "bfsi-uat", "internet-banking", "http://10.30.1.10", "RoE-2026-011", NOW - 26 * HOUR, [
        ("T1046", "10.30.1.10", True, 14.1, "nmap"),
        ("T1190", "10.30.1.10", True, 18.6, "sqlmap"),
        ("T1110", "10.30.1.10", False, None, "hydra"),
        ("T1552.005", "169.254.169.254", False, None, "imds"),
    ]),
    ("eng-proto-range-04", "proto", "range-dvwa", "http://10.20.0.9", "RoE-2026-014", NOW - 3 * HOUR, [
        ("T1046", "10.20.0.9", True, 7.5, "nmap"),
        ("T1190", "10.20.0.9", True, 10.2, "sqlmap"),
        ("T1110", "10.20.0.9", True, 33.8, "hydra"),
    ]),
    ("eng-bfsi-core-05", "bfsi-uat", "core-banking", "http://10.30.2.20", "RoE-2026-009", NOW - 50 * HOUR, [
        ("T1046", "10.30.2.20", True, 12.9, "nmap"),
        ("T1190", "10.30.2.20", False, None, "nuclei"),
        ("T1210", "10.30.2.20", False, None, "metasploit"),
        ("T1548", "10.30.2.20", True, 27.4, "sudo-abuse"),
    ]),
]


def correlations_for(spec: list, base_ts: int) -> list[dict]:
    cors = []
    for i, (tech, ent, detected, mttd, tool) in enumerate(spec):
        red_ts = base_ts + i * 30
        cors.append({
            "technique": tech,
            "entity": ent,
            "state": MatchState.DETECTED if detected else MatchState.MISSED,
            "mttd_seconds": mttd if detected else None,
            "red_ts": float(red_ts),
            "blue_ts": float(red_ts + mttd) if detected else None,
            "red_action_id": f"{tool}-{i}",
            "finding_id": f"FIND-{tech}-{i}" if detected else None,
        })
    return cors


def main() -> None:
    store = CoordinatorStore(DB_URL)
    total_a = total_d = 0
    for eng_id, tenant, tname, turl, roe, base_ts, spec in ENGAGEMENTS:
        cors = correlations_for(spec, base_ts)
        eng = Engagement(
            engagement_id=eng_id, tenant_id=tenant, name=tname, roe_ref=roe,
            scope={"in_scope": [c["entity"] for c in cors]},
            target={"name": tname, "url": turl},
            status=EngagementStatus.COMPLETED,
            decepticon={"thread_id": f"thr-{eng_id}"},
        )
        store.upsert_engagement(eng, mode="on_demand", ts=float(base_ts))

        window = {"start": float(base_ts), "end": float(base_ts + 900),
                  "window_s": CORRELATION_WINDOW_S}
        card = build_scorecard(engagement_id=eng_id, tenant_id=tenant, window=window,
                               correlations=cors)
        cd = card.model_dump(mode="json")
        store.upsert_scorecard(cd, ts=float(base_ts + 900))

        # WORM evidence chain: created -> per red_action -> per detection -> scorecard
        ev = EvidenceStore()
        ev.append(engagement_id=eng_id, tenant_id=tenant, actor="coordinator",
                  record_type="engagement_created",
                  payload={"target": tname, "roe_ref": roe, "mode": "on_demand"}, ts=float(base_ts))
        for i, c in enumerate(cors):
            ev.append(engagement_id=eng_id, tenant_id=tenant, actor="red",
                      record_type="red_action",
                      payload={"technique": c["technique"], "entity": c["entity"],
                               "tool": c["red_action_id"]}, ts=c["red_ts"])
            if c["state"] == MatchState.DETECTED:
                ev.append(engagement_id=eng_id, tenant_id=tenant, actor="vigil",
                          record_type="detection",
                          payload={"technique": c["technique"], "finding_id": c["finding_id"],
                                   "mttd_seconds": c["mttd_seconds"]}, ts=c["blue_ts"])
        ev.append(engagement_id=eng_id, tenant_id=tenant, actor="coordinator",
                  record_type="scorecard",
                  payload={"scorecard_id": cd["scorecard_id"],
                           "detection_rate": cd["detection_rate"]}, ts=float(base_ts + 900))
        store.save_evidence(ev.chain(eng_id))
        store.set_status(eng_id, "completed", ts=float(base_ts + 900))

        a = len(cors); d = sum(1 for c in cors if c["state"] == MatchState.DETECTED)
        total_a += a; total_d += d
        rate = cd["detection_rate"]
        print(f"  ✓ {eng_id:22} {tenant:9} attacked={a} detected={d} "
              f"rate={rate:.2f}" if rate is not None else
              f"  ✓ {eng_id:22} {tenant:9} attacked={a} detected={d} rate=—")

    techs = sorted({c[0] for _, _, _, _, _, _, spec in ENGAGEMENTS for c in spec})
    print(f"\nSeeded {len(ENGAGEMENTS)} engagements · {len(techs)} techniques "
          f"({', '.join(techs)}) · overall detection {total_d}/{total_a} = "
          f"{total_d / total_a:.0%} into {DB_URL}")
    print("Reload the console (LIVE mode) — Overview · Posture · MITRE · Engagements · Evidence are now populated.")


if __name__ == "__main__":
    main()
