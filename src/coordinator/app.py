"""HTTP API of the coordinator (contracts/src/coordinator.md v1). The URL is public (Tailscale Funnel), so:
every endpoint except /healthz needs a Bearer token (401), the right role (403), stays under the per-token
rate limit (429) and the body limit (413), and accepts only validated input (422). Path ids match
[a-z0-9-]{1,64}; no request value is ever used as a filesystem path.

Checkpoint upload (deviation from "multipart" in the contract, flagged on the PR): the body is the raw
encrypted envelope bytes (application/octet-stream, <= 32 MB) and the metadata travels in headers
X-Next-Chunk, X-Out-Bytes, X-Sha256. Same information, no extra parser dependency, size limit enforced
before parsing.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import BodyLimit, ConnCap, Principal, RateLimiter, authenticate, load_tokens
from .core import MAX_CHUNKS, MAX_ROUNDS, VERSION, CoordError, Coordinator

log = logging.getLogger("coordinator")

ID = r"^[a-z0-9-]{1,64}$"
Id = Annotated[str, Field(pattern=ID)]
PathId = Annotated[str, PathParam(pattern=ID)]
SHA = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
BODY_MAX = 1 << 20  # 1 MB
CKPT_MAX = 32 << 20  # 32 MB
RATE, BURST = 20.0, 40.0
CLASSES = Literal["public", "swiss-only", "certified"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttestationIn(Strict):
    node_id: Id
    evidence: Annotated[dict[str, str | bool | int | float], Field(max_length=16)]
    signature_b64: Annotated[str, Field(min_length=8, max_length=512, pattern=r"^[A-Za-z0-9+/=]+$")]
    mock: bool = True


class RegisterIn(Strict):
    node_id: Id
    site_id: Id
    eligible_classes: Annotated[list[CLASSES], Field(min_length=1, max_length=3)]
    server_kw_el: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]
    attestation: AttestationIn


class HeartbeatIn(Strict):
    watts: Annotated[float, Field(ge=0, le=1e6, allow_inf_nan=False)] | None = None
    watts_source: Annotated[str, Field(max_length=32)] | None = None
    running_unit: Annotated[str, Field(pattern=ID)] | None = None
    progress: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    tank_level_kwh: Annotated[float, Field(ge=0, le=1e4, allow_inf_nan=False)] | None = None
    demand_kw: Annotated[float, Field(ge=0, le=1e4, allow_inf_nan=False)] | None = None
    last_error: Annotated[str, Field(max_length=500)] | None = None


class CompleteIn(Strict):
    result_sha256: SHA
    chunk_ids: Annotated[list[Annotated[int, Field(ge=0, le=100_000)]], Field(min_length=1, max_length=10_000)]


class JobIn(Strict):
    job_type: Id | Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]
    customer_id: Id
    access_class: CLASSES | None = None
    deadline_h: Annotated[float, Field(gt=0, le=24 * 365, allow_inf_nan=False)] | None = None
    force: bool = False
    rounds: Annotated[int, Field(ge=1, le=MAX_ROUNDS)] | None = None  # v2.1: runner rounds per chunk
    chunks: Annotated[int, Field(ge=1, le=MAX_CHUNKS)] | None = None  # v2.1: runner chunks per unit


class SignalIn(Strict):
    """v1.1 site heat signal; tank_level_kwh <= the tank capacity is checked in core (422)."""
    demand_kw: Annotated[float, Field(ge=0, le=1e4, allow_inf_nan=False)]
    tank_level_kwh: Annotated[float, Field(ge=0, le=1e4, allow_inf_nan=False)]
    ts: Annotated[float, Field(ge=0, le=1e11, allow_inf_nan=False)]


def create_app(state_dir: Path, tokens: dict[str, str] | None = None, clock=time.time,
               assumptions: dict | None = None, monotonic=time.monotonic,
               registry: dict | None = None) -> FastAPI:
    """registry: v1.2 operator node registry; None -> load state_dir/nodes.json (missing -> deny all)."""
    state_dir = Path(state_dir)
    tokens = tokens if tokens is not None else load_tokens(state_dir / "tokens.json")
    coord = Coordinator(state_dir, clock, assumptions, registry)
    limiter = RateLimiter(RATE, BURST, clock=monotonic)  # monotonic source, never the injected app clock (v1.1)
    app = FastAPI(title="DigitalHeat coordinator", version=VERSION, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.coord = coord
    app.state.limiter = limiter
    app.add_middleware(BodyLimit, default=BODY_MAX, large=CKPT_MAX,
                       large_path=re.compile(r"^/v1/leases/[a-z0-9-]{1,64}/checkpoint$"))
    app.add_middleware(ConnCap, per_client=16)  # added last = outermost: runs before body read and auth (F34)

    @app.exception_handler(CoordError)
    async def _coord_err(_req, e: CoordError):
        return JSONResponse({"detail": e.detail}, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_req, e: RequestValidationError):
        # never echo the offending input back (NaN/inf would even break JSON encoding -> 500)
        errs = [{"loc": [str(x) for x in err.get("loc", ())], "msg": str(err.get("msg", "")), "type": err.get("type")}
                for err in e.errors()]
        return JSONResponse({"detail": errs}, status_code=422)

    @app.exception_handler(Exception)
    async def _any(_req, e: Exception):  # never leak internals on a public URL
        log.exception("unhandled error")
        return JSONResponse({"detail": "internal error"}, status_code=500)

    def principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
        p = authenticate(authorization, tokens)
        if p is None:
            raise HTTPException(401, "missing or unknown bearer token", headers={"WWW-Authenticate": "Bearer"})
        if not limiter.allow(p.token_id):
            raise HTTPException(429, "rate limit exceeded")
        return p

    def node_only(p: Principal, node_id: str) -> None:
        if p.role != "node" or p.node_id != node_id:
            raise HTTPException(403, "this token may only act for its own node")

    def node_token(p: Principal) -> str:
        if p.role != "node":
            raise HTTPException(403, "node token required")
        return p.node_id

    def admin_only(p: Principal) -> None:
        if p.role != "admin":
            raise HTTPException(403, "admin token required")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": VERSION}

    @app.post("/v1/nodes/register")
    def register(body: RegisterIn, p: Principal = Depends(principal)):
        node_only(p, body.node_id)
        return coord.register(body.node_id, body.site_id, list(body.eligible_classes), body.server_kw_el,
                              body.attestation.model_dump())

    @app.post("/v1/nodes/{node_id}/heartbeat")
    def heartbeat(node_id: PathId, body: HeartbeatIn, p: Principal = Depends(principal)):
        node_only(p, node_id)
        return coord.heartbeat(node_id, body.model_dump())

    @app.post("/v1/nodes/{node_id}/lease")
    def lease(node_id: PathId, p: Principal = Depends(principal)):
        node_only(p, node_id)
        return coord.lease(node_id)

    @app.post("/v1/leases/{lease_id}/renew")
    def renew(lease_id: PathId, p: Principal = Depends(principal)):
        return coord.renew(node_token(p), lease_id)

    @app.post("/v1/leases/{lease_id}/checkpoint")
    async def checkpoint(lease_id: PathId, request: Request,
                         x_next_chunk: Annotated[int, Header(ge=0, le=100_000)],
                         x_out_bytes: Annotated[int, Header(ge=0, le=1 << 40)],
                         x_sha256: Annotated[str, Header(pattern=r"^[0-9a-f]{64}$")],
                         p: Principal = Depends(principal)):
        node = node_token(p)
        body = await request.body()
        if not body:
            raise HTTPException(422, "empty checkpoint body")
        return coord.checkpoint(node, lease_id, body, x_next_chunk, x_out_bytes, x_sha256)

    @app.post("/v1/leases/{lease_id}/complete")
    def complete(lease_id: PathId, body: CompleteIn, p: Principal = Depends(principal)):
        return coord.complete(node_token(p), lease_id, body.result_sha256, body.chunk_ids)

    @app.get("/v1/checkpoints/{unit_id}/latest")
    def latest(unit_id: PathId, p: Principal = Depends(principal)):
        data, headers = coord.latest_checkpoint(node_token(p), unit_id)
        return Response(data, media_type="application/octet-stream", headers=headers)

    @app.post("/v1/jobs")
    def submit(body: JobIn, p: Principal = Depends(principal)):
        admin_only(p)
        return coord.submit_job(body.job_type, body.customer_id, body.access_class, body.deadline_h, body.force,
                                body.rounds, body.chunks)

    @app.post("/v1/sites/{site_id}/signal")
    def site_signal(site_id: PathId, body: SignalIn, p: Principal = Depends(principal)):
        if not (p.role == "admin" or (p.role == "site" and p.site_id == site_id)):
            raise HTTPException(403, "admin or this site's token required")
        return coord.site_signal(site_id, body.demand_kw, body.tank_level_kwh, body.ts)

    @app.post("/v1/nodes/{node_id}/tamper")
    def tamper(node_id: PathId, p: Principal = Depends(principal)):
        admin_only(p)
        return coord.tamper(node_id)

    @app.get("/v1/status")
    def status(p: Principal = Depends(principal)):
        if p.role not in ("observer", "admin"):
            raise HTTPException(403, "observer or admin token required")
        return coord.status()

    return app
