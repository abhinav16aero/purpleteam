"""The `scan_untrusted_text` MCP seam (plan 08 §6.2).

This is the single tool BOTH engines call to scan untrusted text before it enters an agent prompt:
  * Vigil — from `prompt_security.wrap_tool_result` + the daemon sensor-log ingestion path.
  * Decepticon — from the existing PromptInjectionShield middleware slot (target-output ingestion).
  * Coordinator — at the loop boundary before scoring (collect_detections).

The callable `scan_untrusted_text(...)` is importable + testable here; `serve_stdio()` is the live
MCP stdio wrapper (needs the `mcp` package + a running vigil-llm for the HTTP scanner).
"""
from __future__ import annotations

from typing import Any

from .injection import InjectionShield, ScanVerdict

# JSON-schema for the MCP tool registration (mirrors mcp-config.json tool shape).
TOOL_SCHEMA: dict[str, Any] = {
    "name": "scan_untrusted_text",
    "description": "Scan untrusted text (sensor log / tool result / target output) for prompt "
                   "injection before it enters an agent prompt. Returns block|flag|allow.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "context": {"type": "object"},
        },
        "required": ["text"],
    },
}

_DEFAULT_SHIELD = InjectionShield()


def scan_untrusted_text(text: str, context: dict | None = None,
                        shield: InjectionShield | None = None) -> ScanVerdict:
    return (shield or _DEFAULT_SHIELD).scan_untrusted_text(text, context)


def serve_stdio() -> None:  # pragma: no cover - live MCP wrapper
    """Run as an MCP stdio server exposing `scan_untrusted_text` (live; requires the `mcp` package)."""
    raise NotImplementedError(
        "live MCP stdio server — install `mcp` and point the scanner at a running vigil-llm; "
        "the coordinator uses the in-process shield (scan_untrusted_text) directly.")
