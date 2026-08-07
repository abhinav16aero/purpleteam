#!/usr/bin/env python3
"""decepticon-driver — Vigil MCP server to launch a scoped Decepticon engagement (plan 06 §4.2).

The GATED red surface: a blue operator/agent can start red from the SOC console, but every tool
here carries an offensive verb (launch/exploit/stop) so `tool_manager.get_tool_tier` returns
`requires_approval` (patch 0002) — it can NEVER auto-execute. Calls the LangGraph :2024 API via httpx
(no langgraph_sdk dep in Vigil's env). Registered in mcp-config.json (disabled by default).

Env: REDBLUE_LANGGRAPH_URL (default http://langgraph:2024).
"""
from __future__ import annotations

import os
import re

import httpx

_LANGGRAPH = os.environ.get("REDBLUE_LANGGRAPH_URL", "http://langgraph:2024")
_ENGAGEMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _require_slug(engagement: str) -> None:
    if not _ENGAGEMENT_RE.match(engagement):
        raise ValueError(f"invalid engagement slug {engagement!r} (fails Decepticon regex)")


def _launch(engagement: str, workspace: str, sandbox_url: str, tenant: str, instruction: str,
            assistant: str = "decepticon") -> dict:
    _require_slug(engagement)
    with httpx.Client(base_url=_LANGGRAPH, timeout=30.0) as c:
        thread = c.post("/threads", json={}).json()
        tid = thread["thread_id"]
        run = c.post(f"/threads/{tid}/runs", json={
            "assistant_id": assistant,
            "input": {"messages": [{"role": "user", "content": instruction}], "engagement_name": engagement},
            "config": {"configurable": {
                "engagement_name": engagement, "engagement_id": engagement, "org_id": tenant,
                "workspace_path": workspace, "sandbox_url": sandbox_url,
            }},
            "multitask_strategy": "interrupt",
        }).json()
        return {"thread_id": tid, "run_id": run.get("run_id"), "engagement": engagement}


def _stop(thread_id: str, run_id: str) -> dict:
    with httpx.Client(base_url=_LANGGRAPH, timeout=15.0) as c:
        c.post(f"/threads/{thread_id}/runs/{run_id}/cancel")
        return {"cancelled": True, "thread_id": thread_id, "run_id": run_id}


# ── MCP server (FastMCP). Tool names carry offensive verbs → gated by patch 0002. ──
try:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("decepticon-driver")

    @mcp.tool()
    def red_launch_engagement(engagement: str, workspace: str, sandbox_url: str,
                              tenant: str, instruction: str) -> dict:
        """Launch a scoped Decepticon engagement. requires_approval (control-plane, 00 §10)."""
        return _launch(engagement, workspace, sandbox_url, tenant, instruction)

    @mcp.tool()
    def red_exploit_target(engagement: str, workspace: str, sandbox_url: str,
                           tenant: str, target: str) -> dict:
        """Dispatch an exploit objective against a target. requires_approval."""
        return _launch(engagement, workspace, sandbox_url, tenant,
                       f"Exploit target {target} within RoE.")

    @mcp.tool()
    def red_stop_engagement(thread_id: str, run_id: str) -> dict:
        """Cancel a running engagement. requires_approval."""
        return _stop(thread_id, run_id)

    if __name__ == "__main__":
        mcp.run()
except ImportError:  # pragma: no cover — mcp lib absent (dev/import-only)
    if __name__ == "__main__":
        raise SystemExit("mcp library not available; install to run the decepticon-driver server")
