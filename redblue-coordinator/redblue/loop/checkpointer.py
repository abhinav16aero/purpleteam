"""Checkpointer factory (plan 07 §1.3 / §2.1).
Durable loop state so a coordinator restart resumes mid-engagement (SQLite MVP → Postgres, 00 §6).
`memory` is used by tests; `sqlite` (file) is the default runtime backing.
"""
from __future__ import annotations
from typing import Any


def make_checkpointer(kind: str = "sqlite", path: str = "./redblue_checkpoints.db") -> Any:
    if kind == "memory":
        from langgraph.checkpoint.memory import InMemorySaver
        return InMemorySaver()
    if kind == "sqlite":
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        conn = aiosqlite.connect(path)
        return AsyncSqliteSaver(conn)
    raise ValueError(f"unknown checkpointer kind {kind!r} (want 'memory' | 'sqlite')")
