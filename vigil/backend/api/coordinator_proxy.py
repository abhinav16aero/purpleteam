"""RedBlue coordinator reverse-proxy (plan 09 §1.2) — ADDITIVE overlay file.

Forwards `/api/coordinator/*` to the RedBlue coordinator (:8900) so the unified console stays
single-origin: it keeps Vigil's cookie+CSRF auth, CSP, and the `streamFetch` SSE machinery, and gives
one auth choke point for the privileged red control plane. Same shape as Vigil's vstrike proxy.

Mounted in backend/main.py behind AUTH_DEPENDENCY at prefix `${VIGIL_CONTEXT_PATH}/api/coordinator`
(see patch 0006). Coordinator routes are `/api/engagements`, `/api/posture`, `/api/kill`, `/metrics`…
so `/api/coordinator/posture` → coordinator `/api/posture`.
"""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

router = APIRouter()

_COORD = os.getenv("REDBLUE_COORDINATOR_URL", "http://redblue-coordinator:8900").rstrip("/")
_TIMEOUT = float(os.getenv("REDBLUE_COORDINATOR_TIMEOUT", "180"))
_HOP = {"host", "cookie", "content-length", "connection", "keep-alive", "transfer-encoding"}


def _fwd_headers(request: Request) -> dict[str, str]:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
    token = os.getenv("REDBLUE_SERVICE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"     # coordinator service auth (never the user cookie)
    return headers


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    url = f"{_COORD}/api/{path}"
    body = await request.body()
    params = dict(request.query_params)
    headers = _fwd_headers(request)

    # SSE passthrough (the live engagement timeline) — stream, don't buffer.
    if "text/event-stream" in request.headers.get("accept", ""):
        client = httpx.AsyncClient(timeout=None)
        req = client.build_request(request.method, url, params=params, content=body, headers=headers)
        upstream = await client.send(req, stream=True)

        async def body_iter():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(
            body_iter(), status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "text/event-stream"),
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.request(request.method, url, params=params, content=body, headers=headers)
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))
    except httpx.HTTPError as e:
        return Response(content=f'{{"error":"coordinator unreachable: {e}"}}',
                        status_code=502, media_type="application/json")
