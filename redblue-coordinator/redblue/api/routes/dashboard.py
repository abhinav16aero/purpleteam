"""Serve the single-file RedBlue console dashboard at `/` and `/dashboard`.

Served by the coordinator itself so the browser loads it from the SAME origin as `/api/*` — no CORS,
no build, no CDN. Tunnel :8900 and open http://localhost:8900/ .
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_HTML = (Path(__file__).resolve().parent.parent / "static" / "dashboard.html").read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(_HTML)
