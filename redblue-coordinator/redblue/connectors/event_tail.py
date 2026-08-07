"""Tail Decepticon's events.jsonl → EngagementEvent (plan 06 §3).

Offset-checkpointed, torn-line-tolerant (mirrors Decepticon's `read_events`), so a coordinator
restart resumes and a half-written final line is held until complete. Race-free because the writer
appends under an fsync'd lock.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

from ..contracts import EngagementEvent


class EventTail:
    def __init__(self, events_path: str | Path, from_offset: int = 0):
        self._path = Path(events_path)
        self._offset = from_offset

    @property
    def offset(self) -> int:
        return self._offset

    def poll(self) -> Iterator[EngagementEvent]:
        """Yield new complete events since the last poll; advance the checkpoint. Torn final line waits."""
        if not self._path.exists():
            return
        with self._path.open("rb") as fh:
            fh.seek(self._offset)
            for raw in fh:
                if not raw.endswith(b"\n"):
                    break                      # torn final line — wait for the next poll
                self._offset = fh.tell()
                try:
                    yield EngagementEvent(**json.loads(raw))
                except (ValueError, TypeError):
                    continue                   # skip malformed (mirror read_events tolerance)

    async def run(self, on_event: Callable[[EngagementEvent], Awaitable[None]], interval: float = 1.0) -> None:
        while True:
            for ev in self.poll():
                await on_event(ev)
            await asyncio.sleep(interval)
