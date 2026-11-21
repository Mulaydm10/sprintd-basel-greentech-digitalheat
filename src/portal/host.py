"""Host API (contract portal v1, P2): ``/v1/host/...`` for the owner of the house where GPU nodes sit
(role ``host:<site_id>``). A host sees only its own site and the nodes registered there.

HTTP only: role checks, validation, response models. State goes through P1's ``coordinator.portal_store``; a node
that is not at this host's site comes back as ``None`` and is answered 404. The pause/resume override is the
owner's "I'm away / too warm" switch: the store makes the scheduler see zero heat demand for the site, so running
units hold through the existing hold path within one tick; it is idempotent and audited in the store.

Mounted by the coordinator (P1)::

    app.include_router(portal.host.make_router(principal, lambda: coord))
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

ID = r"^[a-z0-9-]{1,64}$"
PathId = Annotated[str, Path(pattern=ID)]
NodeState = Literal["online", "suspect", "offline", "paused", "tampered"]
MAX_PAUSE = timedelta(days=30)  # an override longer than this is almost certainly a mistake (input bound)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class PauseIn(Strict):
    until: datetime | None = None  # ISO-8601; naive times are read as UTC


class NodeSummary(Open):
    node_id: str


class HostSite(Open):
    site_id: str
    demand_kw: float | None = None
    tank_level_kwh: float | None = None
    degraded: bool = False
    paused: bool = False
    paused_until: str | None = None
    nodes: list[NodeSummary] = []
    heat_today_kwh: float = 0.0
    heat_month_kwh: float = 0.0
    dumped_today_kwh: float = 0.0
    chf_heat_value_today: float = 0.0


class HostNode(NodeSummary):
    watts: float | None = None
    running_unit: str | None = None
    progress: float | None = None
    last_heartbeat_s: float | None = None
    state: NodeState


class HistoryRow(Open):
    ts: str
    heat_kwh: float
    dumped_kwh: float
    demand_kwh: float


def _store_module():
    return importlib.import_module("coordinator.portal_store")  # P1 (#83); imported lazily


def make_router(principal: Callable[..., Any], coord: Callable[[], Any], store: Any = None,
                now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> APIRouter:
    """``principal``: the app's auth + rate-limit dependency; ``coord``: returns the running Coordinator;
    ``store``: ``portal_store``-like object (default: the real module); ``now``: UTC clock for validating ``until``."""
    r = APIRouter(prefix="/v1/host", tags=["host"])

    def ps():
        return store if store is not None else _store_module()

    def site_id(p=Depends(principal)) -> str:
        sid = getattr(p, "site_id", None)
        if getattr(p, "role", None) != "host" or not sid:
            raise HTTPException(403, "host token required")
        return sid

    def found(x, what: str):
        if x is None:
            raise HTTPException(404, f"{what} not found")
        return x

    @r.get("/site", response_model=HostSite)
    def site(sid: str = Depends(site_id)):
        return found(ps().host_site(coord(), sid), "site")

    @r.get("/nodes/{node_id}", response_model=HostNode)
    def node(node_id: PathId, sid: str = Depends(site_id)):
        return found(ps().host_node(coord(), sid, node_id), "node")

    @r.post("/site/pause", response_model=HostSite)
    def pause(body: Annotated[PauseIn | None, Body()] = None, sid: str = Depends(site_id)):
        until_ts = None
        if body is not None and body.until is not None:
            until = body.until if body.until.tzinfo else body.until.replace(tzinfo=timezone.utc)
            t = now()
            if until <= t:
                raise HTTPException(422, "until must be in the future")
            if until - t > MAX_PAUSE:
                raise HTTPException(422, f"until must be within {MAX_PAUSE.days} days")
            until_ts = until.timestamp()
        return ps().set_site_override(coord(), sid, paused=True, until_ts=until_ts)

    @r.post("/site/resume", response_model=HostSite)
    def resume(sid: str = Depends(site_id)):
        return ps().set_site_override(coord(), sid, paused=False, until_ts=None)

    @r.get("/history", response_model=list[HistoryRow])
    def history(hours: Annotated[int, Query(ge=1, le=720)] = 24, sid: str = Depends(site_id)):
        return ps().host_history(coord(), sid, hours=hours)

    return r
