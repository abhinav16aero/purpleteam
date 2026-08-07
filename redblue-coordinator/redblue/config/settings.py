"""Coordinator settings — env prefix REDBLUE_ (plan 00 §7, plan 07 §6.1)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDBLUE_", env_file=".env", extra="ignore")

    # engine endpoints (00 §4 / §5 — containerized service names on redblue-shared)
    langgraph_url: str = "http://langgraph:2024"
    vigil_url: str = "http://backend:6987"
    vigil_token: str = ""                                  # P4 enclave = DEV_MODE; P5 = service JWT (06/C2)
    decepticon_neo4j_uri: str = "bolt://neo4j:7687"
    decepticon_neo4j_user: str = "neo4j"
    decepticon_neo4j_password: str = ""
    decepticon_neo4j_database: str = "neo4j"
    ollama_url: str = "http://ollama:11434"

    # coordinator store + checkpointer (00 §6: SQLite MVP → Postgres)
    db_url: str = "sqlite:///./redblue.db"
    checkpointer: str = "sqlite"                           # "memory" | "sqlite"
    checkpointer_path: str = "./redblue_checkpoints.db"

    # loop knobs (plan 07 §2.3 / §5.3)
    telemetry_settle_s: float = 120.0
    sandbox_url: str = "http://sandbox:9999"
    drift_debounce_s: float = 300.0            # collapse chatty infra events (§5.3)
    max_replays_per_hour: int = 6              # CART budget cap (§5.3)

    # api
    service_token: str = ""                                # REDBLUE_SERVICE_TOKEN (plan 07 §6.1)
    api_port: int = 8900
    metrics_port: int = 8902


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
