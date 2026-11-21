"""LIVE mode for page 04 (#91): local-only proxy from the dashboard to the coordinator's ops API (portal v1, P3).

    GET  /api/live/state            {enabled, coordinator, kill_node, tamper_node, heat_site, heat, overview?, events?}
    POST /api/live/kill             -> drain + kill DH_LIVE_KILL_NODE ("pull the plug"): the unit must move to ANOTHER
                                       node (#97: kill alone let the scheduler re-lease it to the same node)
    POST /api/live/restore          -> undrain DH_LIVE_KILL_NODE (also automatic once the unit runs elsewhere, or after
                                       DRAIN_RESTORE_S = 60 s)
    POST /api/live/heat {replay}    -> POST /v1/ops/sites/{DH_LIVE_SITE}/scenario {replay: july|coldest}
    POST /api/live/tamper           -> POST /v1/ops/nodes/{DH_LIVE_TAMPER_NODE}/tamper

Safety (the admin token can kill and tamper):
- Off unless ``DH_LIVE_ACTIONS=1``. The admin token is read server-side from ``DH_ADMIN_TOKEN_FILE`` on every call and
  never sent to the browser.
- Only loopback clients (127.0.0.1 / ::1); ``python -m dashboard`` binds 127.0.0.1 anyway.
- Actions need the ``X-DH-Live: 1`` header, which a cross-site page cannot send without a CORS preflight (the
  dashboard has no CORS), and a present ``Origin`` must be this dashboard's own origin: no CSRF through the
  presenter's browser.
- Targets come from the server's environment, never from the request; the tamper target can never be a demo node.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

LOOPBACK = {"127.0.0.1", "::1"}
NEVER_TAMPER = frozenset({"node-mac", "node-omen2"})  # same hard guard as tools.demo
TIMEOUT_S = 5.0
transport: Any = None  # test seam: an httpx transport (e.g. ASGITransport onto an in-process coordinator)
_heat: dict[str, str] = {}  # last scenario this dashboard set, per site (for the toggle label)
DRAIN_RESTORE_S = 60.0
# node -> {"unit": unit it was running when killed (or None), "at": monotonic time, "timer": threading.Timer}
_drained: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()

router = APIRouter(prefix="/api/live", tags=["live"])


class HeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replay: Literal["july", "coldest"]


def _cfg() -> dict[str, str]:
    return {"coordinator": os.environ.get("DH_COORDINATOR_URL", "http://127.0.0.1:8710").rstrip("/"),
            "kill_node": os.environ.get("DH_LIVE_KILL_NODE", "node-omen2"),
            "tamper_node": os.environ.get("DH_LIVE_TAMPER_NODE", "node-demo-tamper"),
            "heat_site": os.environ.get("DH_LIVE_SITE", "site-mac")}


def _enabled() -> bool:
    return os.environ.get("DH_LIVE_ACTIONS") == "1"


def _local_only(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in LOOPBACK:
        raise HTTPException(403, "LIVE controls answer local clients only")


def _same_origin(request: Request) -> None:
    if request.headers.get("x-dh-live") != "1":
        raise HTTPException(403, "missing X-DH-Live header")
    origin = request.headers.get("origin")
    if origin is not None:
        own = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin != own:
            raise HTTPException(403, "cross-origin LIVE action refused")


def _token() -> str:
    f = os.environ.get("DH_ADMIN_TOKEN_FILE", "")
    tok = Path(f).read_text().strip() if f else ""
    if not tok:
        raise HTTPException(503, "DH_ADMIN_TOKEN_FILE is not set or empty")
    return tok


def _call(method: str, path: str, json: dict | None = None) -> httpx.Response:
    kw = {"transport": transport} if transport is not None else {}
    try:
        with httpx.Client(base_url=_cfg()["coordinator"], timeout=TIMEOUT_S, **kw) as c:
            return c.request(method, path, json=json, headers={"Authorization": f"Bearer {_token()}"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"coordinator unreachable: {type(e).__name__}") from None


def _relay(r: httpx.Response, summary: str) -> dict[str, Any]:
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", r.text[:200])
        except ValueError:
            detail = r.text[:200]
        raise HTTPException(r.status_code if 400 <= r.status_code < 600 else 502, f"coordinator: {detail}")
    return {"ok": True, "summary": summary, "result": r.json()}


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    _local_only(request)
    cfg = _cfg()
    out: dict[str, Any] = {"enabled": _enabled(), **cfg, "heat": _heat.get(cfg["heat_site"])}
    if not out["enabled"]:
        return out | {"note": "LIVE controls off: set DH_LIVE_ACTIONS=1, DH_COORDINATOR_URL, DH_ADMIN_TOKEN_FILE"}
    try:
        out["restored"] = _auto_restore()
    except HTTPException as e:
        out["restored"] = [{"undrained": False, "why": e.detail}]
    with _lock:
        out["drained"] = sorted(_drained)
    try:
        ov, ev = _call("GET", "/v1/ops/overview"), _call("GET", "/v1/events/poll", None)
        out["overview"] = ov.json() if ov.status_code == 200 else {"error": ov.status_code}
        out["events"] = ev.json().get("events", [])[-20:] if ev.status_code == 200 else []
    except HTTPException as e:
        out["error"] = e.detail
    return out


def _guarded(request: Request) -> dict[str, str]:
    _local_only(request)
    if not _enabled():
        raise HTTPException(403, "LIVE controls are off (DH_LIVE_ACTIONS != 1)")
    _same_origin(request)
    return _cfg()


def _running_units() -> dict[str, str | None]:
    r = _call("GET", "/v1/ops/nodes?limit=200")
    if r.status_code != 200:
        return {}
    return {n["node_id"]: n.get("running_unit") for n in r.json().get("items", [])}


def _undrain(node: str, why: str) -> dict[str, Any] | None:
    with _lock:
        d = _drained.pop(node, None)
    if d is None:
        return None
    if d.get("timer"):
        d["timer"].cancel()
    try:
        r = _call("POST", f"/v1/ops/nodes/{node}/undrain")
        return {"node": node, "undrained": r.status_code == 200, "why": why}
    except HTTPException as e:  # coordinator down: put it back so a later poll/restore retries
        with _lock:
            _drained.setdefault(node, {"unit": d.get("unit"), "at": d["at"], "timer": None})
        return {"node": node, "undrained": False, "why": f"{why}; undrain failed: {e.detail}"}


def _auto_restore() -> list[dict[str, Any]]:
    """Undrain killed nodes whose unit now runs on another node, or after DRAIN_RESTORE_S."""
    with _lock:
        pending = dict(_drained)
    if not pending:
        return []
    out, running = [], None
    for node, d in pending.items():
        if time.monotonic() - d["at"] >= DRAIN_RESTORE_S:
            out.append(_undrain(node, f"{DRAIN_RESTORE_S:.0f} s elapsed"))
            continue
        if d.get("unit"):
            running = running if running is not None else _running_units()
            elsewhere = [m for m, u in running.items() if u == d["unit"] and m != node]
            if elsewhere:
                out.append(_undrain(node, f"{d['unit']} now runs on {elsewhere[0]}"))
    return [x for x in out if x]


@router.post("/kill")
def kill(request: Request) -> dict[str, Any]:
    """Drain, then kill: no new lease for the node, and its unit is revoked, so the scheduler gives it to another node."""
    cfg = _guarded(request)
    node = cfg["kill_node"]
    unit = _running_units().get(node)
    d = _call("POST", f"/v1/ops/nodes/{node}/drain")
    if d.status_code != 200:
        return _relay(d, "drain")  # raises with the coordinator's detail
    out = _relay(_call("POST", f"/v1/ops/nodes/{node}/kill"), f"pulled the plug on {node}; drained until its unit moves")
    timer = threading.Timer(DRAIN_RESTORE_S, lambda: _undrain(node, f"{DRAIN_RESTORE_S:.0f} s elapsed"))
    timer.daemon = True
    with _lock:
        old = _drained.pop(node, None)
        _drained[node] = {"unit": unit, "at": time.monotonic(), "timer": timer}
    if old and old.get("timer"):
        old["timer"].cancel()
    timer.start()
    return out | {"drained": True, "unit": unit, "restore_after_s": DRAIN_RESTORE_S}


@router.post("/restore")
def restore(request: Request) -> dict[str, Any]:
    cfg = _guarded(request)
    node = cfg["kill_node"]
    got = _undrain(node, "restored by the presenter")
    if got is None:  # not drained by us (e.g. dashboard restarted): undrain anyway, idempotent at the coordinator
        return _relay(_call("POST", f"/v1/ops/nodes/{node}/undrain"), f"{node} accepts leases again")
    if not got["undrained"]:
        raise HTTPException(502, got["why"])
    return {"ok": True, "summary": f"{node} accepts leases again"}


@router.post("/heat")
def heat(request: Request, body: HeatIn) -> dict[str, Any]:
    cfg = _guarded(request)
    out = _relay(_call("POST", f"/v1/ops/sites/{cfg['heat_site']}/scenario", {"replay": body.replay}),
                 f"{cfg['heat_site']} → {body.replay}")
    _heat[cfg["heat_site"]] = body.replay
    return out


@router.post("/tamper")
def tamper(request: Request) -> dict[str, Any]:
    cfg = _guarded(request)
    if cfg["tamper_node"] in NEVER_TAMPER:
        raise HTTPException(403, f"refusing to tamper {cfg['tamper_node']}: demo nodes are never tampered")
    return _relay(_call("POST", f"/v1/ops/nodes/{cfg['tamper_node']}/tamper"), f"tampered {cfg['tamper_node']}")
