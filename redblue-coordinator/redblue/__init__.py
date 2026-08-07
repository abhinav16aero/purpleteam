"""RedBlue AI coordinator — the LangGraph brain that closes the purple-team loop.

Package layout (plan 07 §1.3):
    loop/        the closed-loop state machine (plan_engagement → ... → report_evidence, watch_drift)
    connectors/  engine/infra I/O (Decepticon :2024, Vigil REST, Neo4j KG, sensors)
    scoring/     attacked-vs-detected correlation + metrics (detection-rate, MTTD, MTTR, coverage)
    governance/  tiered-autonomy policy engine + gate (plan 08)
    evidence/    append-only hash-chained WORM store (plan 08)
    store/       SQLAlchemy business records (engagements, scorecards, correlations, evidence)
    api/         FastAPI :8900 control plane
    config/      settings (REDBLUE_ env) + per-tenant policy

Env prefix: REDBLUE_ . API :8900 · metrics :8902 (plan 00 §4).
"""

__version__ = "0.0.1"
