"""redblue.api — FastAPI control plane on :8900 (plan 07 §6)."""
from .app import create_app

__all__ = ["create_app"]
