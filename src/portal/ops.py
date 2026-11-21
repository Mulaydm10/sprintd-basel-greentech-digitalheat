"""Operator API (contract portal v1, P3): ``/v1/ops/...``. Role ``admin``; ``observer`` gets the GETs only.

This module is HTTP only: routing, auth/role checks, input validation and response models (so ``/openapi.json``
describes every route for the frontend's codegen). All state reads and writes go through a backend object
(``portal.backend.Backend``: the coordinator's ``portal_store`` functions in production, a fake in unit tests), and
each action runs in one store transaction there, together with its event row.
"""
from __future__ import annotations

from typing import Annotated, Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

ID = r"^[a-z0-9-]{1,64}$"
CURSOR = r"^[A-Za-z0-9_=-]{1,128}$"
PathId = Annotated[str, Path(pattern=ID)]
Limit = Annotated[int, Query(ge=1, le=200)]
Cursor = Annotated[str | None, Query(pattern=CURSOR)]
READ_ROLES = ("admin", "observer")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Open(BaseModel):
    """Backend rows: documented fields, extra fields allowed (the store may add columns before the contract)."""
    model_config = ConfigDict(extra="allow")


class NodeCounts(Open):
    online: int = 0
    suspect: int = 0
    offline: int = 0


class JobCounts(Open):
    queued: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0


class AuditState(Open):
    ok: bool
    head: str
    length: int


class Overview(Open):
    nodes: NodeCounts
    jobs: JobCounts
    leases_active: int
    heat_used_kwh_today: float
    dumped_kwh_today: float
    missed_deadline_pct: float
    degraded_sites: list[str]
    audit: AuditState


class Page(Open):
    items: list[dict[str, Any]]
    next_cursor: str | None = None


class AuditPage(Page):
    verify: AuditState


class DrainResult(Open):
    node_id: str
    drained: bool
    changed: bool


class KillResult(Open):
    node_id: str
    revoked_lease: str | None = None


class TamperResult(Open):
    node_id: str


class ScenarioIn(Strict):
    replay: Literal["coldest", "july"]


class ScenarioResult(Open):
    site_id: str
    replay: Literal["coldest", "july"]
    changed: bool


def make_router(principal: Callable[..., Any], backend: Callable[[], Any]) -> APIRouter:
    """``principal``: the app's auth dependency (returns ``auth.Principal``); ``backend``: returns the Backend."""
    r = APIRouter(prefix="/v1/ops", tags=["ops"])

    def reader(p=Depends(principal)):
        if p.role not in READ_ROLES:
            raise HTTPException(403, "admin or observer token required")
        return p

    def admin(p=Depends(principal)):
        if p.role != "admin":
            raise HTTPException(403, "admin token required")
        return p

    @r.get("/overview", response_model=Overview)
    def overview(_p=Depends(reader)):
        return backend().ops_overview()

    @r.get("/nodes", response_model=Page)
    def nodes(limit: Limit = 50, cursor: Cursor = None, _p=Depends(reader)):
        return backend().ops_nodes(limit, cursor)

    @r.get("/jobs", response_model=Page)
    def jobs(limit: Limit = 50, cursor: Cursor = None, _p=Depends(reader)):
        return backend().ops_jobs(limit, cursor)

    @r.get("/sites", response_model=Page)
    def sites(limit: Limit = 50, cursor: Cursor = None, _p=Depends(reader)):
        return backend().ops_sites(limit, cursor)

    @r.get("/audit", response_model=AuditPage)
    def audit(limit: Limit = 50, cursor: Cursor = None, _p=Depends(reader)):
        return backend().ops_audit(limit, cursor)

    @r.post("/nodes/{node_id}/drain", response_model=DrainResult)
    def drain(node_id: PathId, _p=Depends(admin)):
        return backend().drain_node(node_id, True)

    @r.post("/nodes/{node_id}/undrain", response_model=DrainResult)
    def undrain(node_id: PathId, _p=Depends(admin)):
        return backend().drain_node(node_id, False)

    @r.post("/nodes/{node_id}/kill", response_model=KillResult)
    def kill(node_id: PathId, _p=Depends(admin)):
        return backend().kill_node(node_id)

    @r.post("/nodes/{node_id}/tamper", response_model=TamperResult)
    def tamper(node_id: PathId, _p=Depends(admin)):
        return backend().tamper(node_id)

    @r.post("/sites/{site_id}/scenario", response_model=ScenarioResult)
    def scenario(site_id: PathId, body: ScenarioIn, _p=Depends(admin)):
        return backend().set_site_scenario(site_id, body.replay)

    return r
