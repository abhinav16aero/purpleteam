"""AI-native defense — the injection shield (plan 08 §6).

Wraps vigil-llm as the log-substrate prompt-injection defense in front of ingestion. Two scanners:
  * HeuristicInjectionScanner — sovereign, offline, air-gapped: the same signatures vigil-llm's YARA
    rules encode (InstructionBypass / ContainsReAct / MarkdownExfiltration / SystemInstructions).
    Testable on this box with no service; the fallback + default.
  * VigilLlmHttpScanner — the real vigil-llm service (DeBERTa + YARA + vector-DB) over its Flask
    `POST /analyze/prompt` API (the live slice; higher recall).
Verdict policy (§6.2): BLOCK if any injection rule fires; FLAG weak signals; ALLOW otherwise.
Fail posture (§6.4): scanner error ⇒ fail-open-with-flag for high-volume ingestion (avoid a DoS),
fail-closed for tool-schema poisoning (caller passes fail_open=False).
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field

# ── signatures (extend vigil-llm/data/yara/*.yar) ──
# The instruction-bypass rule requires a bypass VERB + a reference-to-prior-context word + a target
# NOUN (in order, within a window). Requiring the reference word is what separates injections
# ("ignore ALL PREVIOUS instructions") from benign ops text ("skip messages older than 7 days",
# "forget cached responses") — vigil-llm's YARA rule required strict verb↔noun adjacency and both
# missed "ignore all previous instructions" AND false-positived on filler; this fixes both.
_INSTRUCTION_BYPASS = re.compile(
    r"\b(ignore|disregard|skip|forget|neglect|overlook|omit|bypass|pay no attention to|"
    r"do not follow|do not obey)\b[^.\n]{0,40}?"
    r"\b(previous|prior|preceding|above|foregoing|earlier|initial|all|any|your)\b[^.\n]{0,30}?"
    r"\b(instructions?|directives?|commands?|context|conversation|prompts?|rules?|"
    r"messages?|responses?)\b", re.IGNORECASE)
# Markdown-image exfil: an image whose URL carries a `?q=<data>` query (the Bing-chat vector).
# Matches any path depth and any (incl. empty) query value — the vigil-llm rule only matched an
# empty `?q=)` on a single-segment path, so it MISSED real `?q=SECRET)` exfil (eval-surfaced).
_MDEXFIL = re.compile(r"!\[[^\]]*\]\(\s*https?://[^)\s]*\?q=[^)]*\)")
_THOUGHT00 = re.compile(r'Thought:\s*```(?:json)?\s*{\s*"action"\s*:\s*"[^"]+",\s*'
                        r'"action_input"\s*:\s*"[^"]*"\s*}```')
_THOUGHT01 = re.compile(r"Thought:\s\w+[^\n]+")
_OBSERVATION = re.compile(r"Observation:\s*[^\n]+")
_ACTION = re.compile(r'Action:\s*```\s*{\s*"action"\s*:\s*"[^"]+",\s*"action_input"\s*:\s*"[^"]*"\s*}```')
_SYSTEM_TOKENS = (
    "System Instruction: ", "[system](#assistant)", "[system](#context)",
    "<s>[INST] <<SYS>>", "<</SYS>>", "<|im_start|>assistant", "<|im_start|>system",
    "{{#system~}}", "{{/system~}}",
)


class ScanAction(str, Enum):
    ALLOW = "allow"
    FLAG = "flag"
    BLOCK = "block"


class ScanVerdict(BaseModel):
    action: ScanAction
    matched: list[str] = Field(default_factory=list)   # rule names that fired
    scanner: str = "heuristic"
    detail: str | None = None


@runtime_checkable
class InjectionScanner(Protocol):
    def scan(self, text: str) -> ScanVerdict: ...


class HeuristicInjectionScanner:
    """Sovereign regex/substring scanner mirroring vigil-llm's injection YARA rules."""

    def scan(self, text: str) -> ScanVerdict:
        text = text or ""
        matched: list[str] = []
        if _INSTRUCTION_BYPASS.search(text):
            matched.append("InstructionBypass")
        if _MDEXFIL.search(text):
            matched.append("MarkdownExfiltration")
        if any(tok in text for tok in _SYSTEM_TOKENS):
            matched.append("SystemInstructions")
        t00, t01 = _THOUGHT00.search(text), _THOUGHT01.search(text)
        obs, act = _OBSERVATION.search(text), _ACTION.search(text)
        # react.yar condition, corrected: the third clause is (t01 AND obs). vigil-llm ships
        # `(t00 and obs)` which is dead (t00 alone already matches clause 1), so a plain
        # Thought:+Observation: hijack with no JSON Action fence went undetected.
        if t00 or (t01 and act) or (t01 and obs):
            matched.append("ContainsReAct")
        if matched:
            return ScanVerdict(action=ScanAction.BLOCK, matched=matched, scanner="heuristic")
        return ScanVerdict(action=ScanAction.ALLOW, scanner="heuristic")


class VigilLlmHttpScanner:
    """The real vigil-llm service (its Flask `POST /analyze/prompt`). Live slice — higher recall."""

    def __init__(self, url: str = "http://vigil-llm:5000", timeout: float = 10.0) -> None:
        self._url = url.rstrip("/")
        self._timeout = timeout

    def scan(self, text: str) -> ScanVerdict:
        r = httpx.post(f"{self._url}/analyze/prompt", json={"prompt": text}, timeout=self._timeout)
        r.raise_for_status()
        d = r.json()
        msgs = d.get("messages", []) or []
        # vigil-llm has no single score — BLOCK if any input scanner produced a message (dispatch.py).
        if msgs:
            return ScanVerdict(action=ScanAction.BLOCK, matched=[str(m)[:120] for m in msgs],
                               scanner="vigil-llm")
        return ScanVerdict(action=ScanAction.ALLOW, scanner="vigil-llm")


class InjectionShield:
    def __init__(self, scanner: InjectionScanner | None = None, fail_open: bool = True) -> None:
        self._scanner = scanner or HeuristicInjectionScanner()
        self._fail_open = fail_open                        # §6.4: True = flag on error (ingestion)

    def scan_untrusted_text(self, text: str, context: dict[str, Any] | None = None) -> ScanVerdict:
        try:
            return self._scanner.scan(text or "")
        except Exception as e:                             # fail posture (§6.4)
            action = ScanAction.FLAG if self._fail_open else ScanAction.BLOCK
            return ScanVerdict(action=action, scanner="error", detail=str(e))
