"""Phone fleet for wow moment #2 (volunteers join by QR; server phones heat while running a job; STOP moves it on).

Served by the public dashboard (same origin as the join page, so no CORS and no coordinator token ever reaches a phone).

    POST /api/phones/join      {code, name?}         -> {device_id, token, role, label}   (cap: DH_PHONES_CAP, default 20)
    POST /api/phones/hb        {device_id, token, battery?, temp_hint?}
                                                     -> {state, job?: {job_id, step, total, label}}
    POST /api/phones/progress  {device_id, token, job_id, step}   (server phone: work done so far)
    POST /api/phones/stop      {device_id, token}    -> the job is released WITH its progress and re-queued
    POST /api/phones/resume    {device_id, token}    -> back in the pool
    POST /api/phones/submit    {device_id, token}    -> {job_id}  (client phone)
    GET  /api/phones/my        ?device_id=&token=    -> my jobs (client) / my current job (server)
    GET  /api/phones/state                           -> public, anonymised fleet state for the big screen
    GET  /api/phones/qr.svg                          -> QR of the join URL (code included) for the big screen
    POST /api/phones/reset     header X-DH-Admin: $DH_PHONES_ADMIN -> empty fleet (the funnel makes every client look
                               like loopback, so a secret, not the client address, guards it)

Roles: the first joiner of every 4 is a client, the others are servers (3 : 1). A job = TOTAL_STEPS steps of work
(1 step per second of heating, ~25 s). Progress belongs to the job, not the phone: STOP hands the next server phone the
exact step it reached. A server phone silent for HB_TIMEOUT_S is treated as stopped (the job moves on the same way).
The heat itself is the volunteers' phones running phone-heat-test (CPU + GPU load) only while they hold a job.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
TOTAL_STEPS = int(os.environ.get("DH_PHONES_STEPS", "25"))
HB_TIMEOUT_S = 8.0
ONLINE_S = 60.0  # a phone silent this long (tab closed, page reloaded) no longer counts against the cap (#138)
STEP_S = 1.0  # a server phone does 1 step per second of heating: faster reports are capped (#138, no skipping work)
STEP_SLACK = 2  # network jitter allowance on top of the elapsed seconds
CAP = int(os.environ.get("DH_PHONES_CAP", "20"))
CLIENT_EVERY = 4
ID = r"^[a-z0-9-]{1,40}$"

router = APIRouter(prefix="/api/phones", tags=["phones"])
_lock = threading.RLock()
S: dict[str, Any] = {"devices": {}, "jobs": {}, "events": [], "seq": 0, "joined": 0}
_clock = time.time


def _code() -> str:
    return os.environ.get("DH_EVENT_CODE", "")


def _state_file() -> Path:
    return Path(os.environ.get("DH_PHONES_STATE", str(ROOT / "runs" / "phones" / "state.json")))


def _save() -> None:
    p = _state_file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(S))
        os.replace(tmp, p)
    except OSError:
        pass


def _load() -> None:
    p = _state_file()
    if p.is_file():
        try:
            S.update(json.loads(p.read_text()))
        except (OSError, ValueError):
            pass


_load()


def _event(kind: str, **data: Any) -> None:
    S["seq"] += 1
    S["events"].append({"id": S["seq"], "t": round(_clock(), 3), "type": kind, **data})
    del S["events"][:-300]


def _auth(device_id: str, token: str) -> dict:
    d = S["devices"].get(device_id)
    if d is None or not hmac.compare_digest(d["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
        raise HTTPException(403, "unknown device or bad token")
    return d


class JoinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=24)


class DevIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(pattern=ID)
    token: str = Field(min_length=16, max_length=128)
    battery: float | None = Field(default=None, ge=0, le=1)


class ProgIn(DevIn):
    job_id: str = Field(pattern=ID)
    step: int = Field(ge=0, le=10_000)


def _idle_servers() -> list[dict]:
    now = _clock()
    return sorted((d for d in S["devices"].values() if d["role"] == "server" and d["state"] == "idle"
                   and now - d["seen"] < HB_TIMEOUT_S), key=lambda d: d["idle_since"])


def _assign() -> None:
    """Merit-free and simple on purpose: oldest queued job -> the server phone idle the longest."""
    queued = sorted((j for j in S["jobs"].values() if j["state"] == "queued"), key=lambda j: j["created"])
    for j in queued:
        free = _idle_servers()
        if not free:
            return
        d = free[0]
        j.update(state="running", device=d["id"], hops=j["hops"] + [d["id"]], leased=_clock(), mark_step=j["step"])
        d.update(state="busy", job=j["id"])
        _event("job.assigned", job=j["id"], device=d["id"], step=j["step"], moved=len(j["hops"]) > 1)


def _release(d: dict, why: str) -> None:
    j = S["jobs"].get(d.get("job") or "")
    if j and j["state"] == "running" and j["device"] == d["id"]:
        j.update(state="queued", device=None)
        _event("job.moved", job=j["id"], device=d["id"], step=j["step"], reason=why)
    d.update(job=None)


def _sweep() -> None:
    now = _clock()
    for d in S["devices"].values():
        if d["role"] == "server" and d["state"] == "busy" and now - d["seen"] >= HB_TIMEOUT_S:
            d["state"] = "gone"
            _release(d, "phone went silent")
            _event("device.gone", device=d["id"])
    _assign()


@router.post("/join")
def join(body: JoinIn, request: Request) -> dict:
    code = _code()
    if not code or not hmac.compare_digest(body.code.encode(), code.encode()):  # bytes: non-ASCII str raised (#138)
        raise HTTPException(403, "wrong event code")
    with _lock:
        now = _clock()
        live = [d for d in S["devices"].values() if d["state"] not in ("left", "gone") and now - d["seen"] < ONLINE_S]
        if len(live) >= CAP:
            raise HTTPException(429, f"fleet is full ({CAP} devices)")
        S["joined"] += 1
        n = S["joined"]
        role = "client" if n % CLIENT_EVERY == 1 else "server"
        dev_id = f"ph-{n:02d}-{secrets.token_hex(2)}"
        token = secrets.token_urlsafe(24)
        label = (body.name or "").strip()[:24] or f"Volunteer {n}"
        now = _clock()
        S["devices"][dev_id] = {"id": dev_id, "n": n, "label": label, "role": role, "state": "idle", "job": None,
                                "token_hash": hashlib.sha256(token.encode()).hexdigest(), "joined": now, "seen": now,
                                "idle_since": now, "steps_done": 0, "battery": None}
        _event("device.joined", device=dev_id, role=role, label=label)
        _sweep()
        _save()
    return {"device_id": dev_id, "token": token, "role": role, "label": label, "total_steps": TOTAL_STEPS}


@router.post("/hb")
def hb(body: DevIn) -> dict:
    with _lock:
        d = _auth(body.device_id, body.token)
        d["seen"] = _clock()
        if body.battery is not None:
            d["battery"] = body.battery
        if d["state"] == "gone":
            d.update(state="idle", idle_since=_clock())
            _event("device.back", device=d["id"])
        _sweep()
        j = S["jobs"].get(d.get("job") or "")
        out = {"state": d["state"], "role": d["role"]}
        if j and d["role"] == "server" and j["state"] == "running":
            out["job"] = {"job_id": j["id"], "step": j["step"], "total": j["total"], "label": j["label"],
                          "hops": len(j["hops"]), "client": j["client_label"]}
        return out


@router.post("/progress")
def progress(body: ProgIn) -> dict:
    with _lock:
        d = _auth(body.device_id, body.token)
        d["seen"] = _clock()
        j = S["jobs"].get(body.job_id)
        if not j or j["state"] != "running" or j["device"] != d["id"]:
            raise HTTPException(410, "you no longer hold this job")
        cap = j.get("mark_step", 0) + int((_clock() - j.get("leased", _clock())) / STEP_S) + STEP_SLACK
        step = max(j["step"], min(body.step, j["total"], cap))   # never back; never faster than the work (#138)
        d["steps_done"] += step - j["step"]
        j["step"] = step
        if step >= j["total"]:
            j.update(state="done", device=None, done=_clock())
            d.update(state="idle", job=None, idle_since=_clock())
            _event("job.done", job=j["id"], device=d["id"], hops=len(j["hops"]))
            _assign()
        _save()
        return {"ok": True, "step": j["step"], "state": j["state"]}


@router.post("/stop")
def stop(body: DevIn) -> dict:
    with _lock:
        d = _auth(body.device_id, body.token)
        d["seen"] = _clock()
        had = d.get("job")
        step = S["jobs"][had]["step"] if had in S["jobs"] else None
        _release(d, "heat need met: STOP")
        d.update(state="stopped")
        _event("device.stopped", device=d["id"], job=had, step=step)
        _assign()
        _save()
        j = S["jobs"].get(had or "")
        return {"ok": True, "released": had, "step": step, "now_on": j["device"] if j else None}


@router.post("/resume")
def resume(body: DevIn) -> dict:
    with _lock:
        d = _auth(body.device_id, body.token)
        d["seen"] = _clock()
        if d["state"] == "busy" and d.get("job"):  # resume while holding a job: a no-op (it orphaned the job, #138)
            return {"ok": True, "state": "busy"}
        d.update(state="idle", idle_since=_clock())
        _event("device.resumed", device=d["id"])
        _assign()
        _save()
        return {"ok": True}


@router.post("/submit")
def submit(body: DevIn) -> dict:
    with _lock:
        d = _auth(body.device_id, body.token)
        if d["role"] != "client":
            raise HTTPException(403, "only client phones submit jobs")
        mine = [j for j in S["jobs"].values() if j["client"] == d["id"] and j["state"] in ("queued", "running")]
        if len(mine) >= 2:
            raise HTTPException(429, "you already have 2 jobs running")
        if len(S["jobs"]) >= 200:
            raise HTTPException(429, "job limit for this demo reached")
        jid = f"pj-{len(S['jobs']) + 1:03d}"
        kinds = ["image tagging · 40 photos", "speech-to-text · 3 min", "embeddings · 2,000 docs", "OCR · 25 pages"]
        S["jobs"][jid] = {"id": jid, "client": d["id"], "client_label": d["label"], "label": kinds[len(S["jobs"]) % 4],
                          "state": "queued", "step": 0, "total": TOTAL_STEPS, "device": None, "hops": [],
                          "created": _clock(), "done": None}
        _event("job.submitted", job=jid, client=d["id"])
        _assign()
        _save()
        return {"job_id": jid, "total": TOTAL_STEPS}


@router.get("/my")
def my(device_id: str, token: str) -> dict:
    with _lock:
        d = _auth(device_id, token)
        jobs = [{"job_id": j["id"], "label": j["label"], "state": j["state"], "step": j["step"], "total": j["total"],
                 "on": S["devices"].get(j["device"] or "", {}).get("label"), "hops": len(j["hops"]),
                 "hop_labels": [S["devices"].get(h, {}).get("label", h) for h in j["hops"]]}
                for j in S["jobs"].values() if j["client"] == d["id"]]
        return {"role": d["role"], "state": d["state"], "jobs": sorted(jobs, key=lambda x: x["job_id"], reverse=True)}


@router.get("/state")
def state(after: int = 0) -> dict:
    with _lock:
        _sweep()
        devs = [{"id": d["id"], "label": d["label"], "role": d["role"], "state": d["state"], "job": d["job"],
                 "steps_done": d["steps_done"], "online": _clock() - d["seen"] < HB_TIMEOUT_S, "n": d["n"]}
                for d in S["devices"].values()]
        jobs = [{k: j[k] for k in ("id", "label", "state", "step", "total", "device", "hops", "client_label")}
                for j in S["jobs"].values()]
        return {"cap": CAP, "total_steps": TOTAL_STEPS, "devices": devs, "jobs": jobs,
                "events": [e for e in S["events"] if e["id"] > after][-100:], "last_id": S["seq"],
                "join_open": bool(_code())}


@router.get("/qr.svg")
def qr(request: Request) -> Response:
    code = _code()
    if not code:
        raise HTTPException(404, "set DH_EVENT_CODE to open joining")
    base = os.environ.get("DH_PUBLIC_SITE", str(request.base_url)).rstrip("/")
    url = f"{base}/phone-join.html#code={code}"
    try:
        import segno  # tiny pure-python QR library
        import io
        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="svg", scale=8, border=2, dark="#141414", light="#f8f6f1")
        return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
    except ImportError:
        raise HTTPException(501, "QR library missing: pip install segno") from None


@router.get("/join-url")
def join_url(request: Request) -> dict:
    code = _code()
    base = os.environ.get("DH_PUBLIC_SITE", str(request.base_url)).rstrip("/")
    return {"url": f"{base}/phone-join.html#code={code}" if code else None}


@router.post("/reset")
def reset(request: Request) -> dict:
    secret = os.environ.get("DH_PHONES_ADMIN", "")
    if not secret or not hmac.compare_digest(request.headers.get("x-dh-admin", ""), secret):
        raise HTTPException(403, "reset needs the admin secret")
    with _lock:
        S.update(devices={}, jobs={}, events=[], seq=0, joined=0)
        _save()
    return {"ok": True}
