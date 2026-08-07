"""Drive Decepticon over the LangGraph Platform :2024 API (plan 06 §4.1).

`config.configurable` carries the engagement scope + per-run sandbox (multi-tenant fan-out hook).
The engagement slug MUST match Decepticon's regex — validated before every launch.
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from langgraph_sdk import get_client

# Decepticon engagement-label regex (engagement_scope.py:31) — the tenant scope key.
_ENGAGEMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def valid_engagement(slug: str) -> bool:
    return bool(_ENGAGEMENT_RE.match(slug))


class RedDriver:
    def __init__(self, url: str = "http://langgraph:2024"):
        self._url = url
        self._client = get_client(url=url)

    async def launch(
        self, *, engagement: str, workspace: str, sandbox_url: str, tenant: str,
        instruction: str, assistant: str = "decepticon", sandbox_token: str | None = None,
        target: dict | None = None,
    ) -> AsyncIterator[Any]:
        """Start a scoped engagement; yields stream chunks (bridged to evidence/scorecard by the loop)."""
        if not valid_engagement(engagement):
            raise ValueError(f"invalid engagement slug {engagement!r} (fails Decepticon regex)")
        thread = await self._client.threads.create()
        configurable: dict[str, Any] = {
            "engagement_name": engagement, "engagement_id": engagement, "org_id": tenant,
            "workspace_path": workspace, "sandbox_url": sandbox_url,
        }
        if sandbox_token:
            configurable["sandbox_token"] = sandbox_token
        if target:
            configurable.update(target)
        async for chunk in self._client.runs.stream(
            thread["thread_id"], assistant_id=assistant,
            input={"messages": [{"role": "user", "content": instruction}], "engagement_name": engagement},
            config={"configurable": configurable},
            stream_mode=["values", "updates", "custom"],
        ):
            yield chunk

    async def cancel(self, thread_id: str, run_id: str) -> None:
        await self._client.runs.cancel(thread_id, run_id)
