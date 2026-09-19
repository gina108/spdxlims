"""Read-only relay to the instrument engine.

The engine binds loopback on the PC wired to the analyzers, so a workstation
cannot reach it and shows the instruments as disconnected. This backend runs on
that same PC, and the workstation already talks to it over an authenticated,
firewalled port - so it relays instead, and no second port has to be opened.

Deliberately read-only. The engine has no authentication of its own, so the
only safe thing to expose is observation: status, captures, and replay of a
capture already recorded. Nothing here can open, close or reconfigure a
session, because that would let any authenticated workstation take an analyzer
away from the lab. Starting and stopping captures stays on the machine that
owns the hardware (see spdxlims/engine_identity.py).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.core.config import settings
from app.core.deps import get_current_user

router = APIRouter()

_TIMEOUT = 10.0


def _engine_request(path: str, *, method: str = "GET", body: dict | None = None) -> Any:
    url = f"{settings.instrument_engine_url.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=502, detail=f"instrument engine returned {exc.code}: {detail[:200]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # The engine is a local service that can be stopped for maintenance.
        # 503 so the client can show "offline" rather than treat it as a bug.
        raise HTTPException(status_code=503, detail=f"instrument engine unreachable: {exc}") from exc
    try:
        return json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="instrument engine returned invalid JSON") from exc


@router.get("/health")
def engine_health(_user=Depends(get_current_user)):
    """Whether the engine is up, for the workstation's status indicator."""
    try:
        payload = _engine_request("/api/v1/health")
    except HTTPException as exc:
        if exc.status_code == 503:
            return {"status": "offline", "detail": exc.detail}
        raise
    return payload


@router.get("/status")
def runtime_status(_user=Depends(get_current_user)):
    return _engine_request("/api/v1/runtime/status")


@router.get("/captures")
def captures(
    limit: int = Query(default=100, ge=1, le=1000),
    profile_id: str | None = Query(default=None),
    _user=Depends(get_current_user),
):
    query: dict[str, Any] = {"limit": limit}
    if (profile_id or "").strip():
        query["profile_id"] = profile_id.strip()
    return _engine_request(f"/api/v1/captures?{urllib.parse.urlencode(query)}")


@router.post("/orders/pending")
def push_pending_order(payload: dict = Body(...), _user=Depends(get_current_user)):
    """Hand a worklist entry to the engine on behalf of a workstation.

    The one write in this router, and a deliberate exception to its read-only
    rule. Registering an order is ordinary clinical work that a workstation must
    be able to do - the engine writes the CM250's .ANA file and can answer an
    ASTM host query for that sample. Without it, orders placed on a workstation
    silently never reached the analyzer.

    It stays narrow on purpose: this adds work for a sample, it does not open,
    close or reconfigure a session. Deciding which machine owns an analyzer is
    still not something a workstation can do from here.
    """
    if not str(payload.get("sample_id") or "").strip():
        raise HTTPException(status_code=400, detail="sample_id is required")
    return _engine_request("/api/v1/orders/pending", method="POST", body=payload)


@router.post("/replay")
def replay(payload: dict = Body(...), _user=Depends(get_current_user)):
    """Re-parse a stored capture. Touches no hardware - it reads a saved file."""
    capture_id = str(payload.get("capture_id") or "").strip()
    profile_id = str(payload.get("profile_id") or "").strip()
    if not capture_id:
        raise HTTPException(status_code=400, detail="capture_id is required")
    return _engine_request(
        "/api/v1/replay",
        method="POST",
        body={"capture_id": capture_id, "profile_id": profile_id},
    )
