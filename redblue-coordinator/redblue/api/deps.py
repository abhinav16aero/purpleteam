"""API dependencies (plan 07 §6.1). App wiring lives on `app.state` (set in create_app)."""
from __future__ import annotations

from fastapi import Request


def get_graph(request: Request):
    return request.app.state.graph


def get_store(request: Request):
    return request.app.state.store


def get_deps(request: Request):
    return request.app.state.deps
