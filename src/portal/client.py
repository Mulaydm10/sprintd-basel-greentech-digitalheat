"""Client API (contract portal v1, P2): ``/v1/client/...`` for compute customers (role ``client:<client_id>``).

HTTP only: routing, role checks, input validation and response models (so ``/openapi.json`` describes every route
for the frontend's codegen). All reads and writes go through P1's ``coordinator.portal_store`` functions, which
enforce ownership inside the query: an unknown OR foreign id comes back as ``None`` and is answered 404, never 403,
so job ids cannot be probed. Business errors are the store's ``CoordError`` and reach the app's handler, except the
admission rejection on submit, which is returned unwrapped as ``{status: "rejected", reason}`` per the contract.

Mounted by the coordinator (P1) the same way as P3's routers::

    app.include_router(portal.client.make_router(principal, lambda: coord))
"""
from __future__ import annotations

import asyncio
import importlib
from typing import Annotated, Any, Callable, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from coordinator.core import MAX_CHUNKS, MAX_ROUNDS, CoordError

ID = r"^[a-z0-9-]{1,64}$"
JOB_TYPE = r"^[a-z0-9_-]{1,64}$"  # catalogue names use underscores (e.g. whisper_transcription)
CURSOR = r"^[A-Za-z0-9_=-]{1,128}$"
PathId = Annotated[str, Path(pattern=ID)]
Limit = Annotated[int, Query(ge=1, le=200)]
Cursor = Annotated[str | None, Query(pattern=CURSOR)]
Classes = Literal["public", "swiss-only", "certified"]
JobStatus = Literal["queued", "running", "paused", "done", "failed", "cancelled"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Open(BaseModel):
    """Store rows: documented fields, extra fields allowed (the store may add columns before the contract does)."""
    model_config = ConfigDict(extra="allow")


# ------------------------------------------------------------------ request bodies
class SubmitIn(Strict):
    type: Annotated[str, Field(pattern=JOB_TYPE)]
    access_class: Classes
    deadline_h: Annotated[float, Field(ge=0.25, le=720, allow_inf_nan=False)] | None = None  # required except live (#127)
    idempotency_key: Annotated[str, Field(pattern=ID)]
    rounds: Annotated[int, Field(ge=1, le=MAX_ROUNDS)] | None = None
    chunks: Annotated[int, Field(ge=1, le=MAX_CHUNKS)] | None = None
    client_pub: Annotated[str, Field(max_length=400)] | None = None  # live v2: the phone's per-job P-256 key


# ------------------------------------------------------------------ responses
class ClientMe(Open):
    client_id: str
    jobs_total: int
    jobs_running: int
    server_h_used: float
    chf_spent: float


class CatalogueItem(Open):
    type: str
    label: str
    access_classes: list[str]
    est_unit_min: float
    price_chf_server_h: float


class Admitted(Open):
    job_id: str
    status: Literal["admitted"]
    eta: str | None = None


class Rejected(Open):
    status: Literal["rejected"]
    reason: str


class UnitOut(Open):
    unit_id: str
    status: str
    node_id: str | None = None
    done_chunks: int
    total_chunks: int


class JobSummary(Open):
    job_id: str
    type: str
    access_class: str
    status: JobStatus
    progress: Annotated[float, Field(ge=0, le=1)]
    deadline: str | None = None
    eta: str | None = None
    missed_deadline: bool = False


class JobDetail(JobSummary):
    units: list[UnitOut] = []
    events: list[dict[str, Any]] = []


class JobPage(Open):
    items: list[JobSummary]
    next_cursor: str | None = None


class Receipt(Open):
    result_sha256: str | None  # None when a unit's final bytes are unreadable (the store says so; not hidden)
    chunk_ids: dict[str, list[int]]  # unit_id -> its completed chunk ids, so the client can check 0..N-1 per unit
    nodes_used: list[str]
    kwh: float
    heat_used_kwh: float
    audit_head: str | None  # None only for an empty audit chain


def _store_module():
    return importlib.import_module("coordinator.portal_store")  # P1 (#83); imported lazily


def make_router(principal: Callable[..., Any], coord: Callable[[], Any], store: Any = None) -> APIRouter:
    """``principal``: the app's auth + rate-limit dependency; ``coord``: returns the running Coordinator;
    ``store``: an object with ``portal_store``'s functions (default: the real module; tests pass a fake)."""
    r = APIRouter(prefix="/v1/client", tags=["client"])

    def ps():
        return store if store is not None else _store_module()

    def client_id(p=Depends(principal)) -> str:
        cid = getattr(p, "client_id", None)
        if getattr(p, "role", None) != "client" or not cid:
            raise HTTPException(403, "client token required")
        return cid

    def found(x):
        if x is None:  # unknown or not this client's: indistinguishable on purpose
            raise HTTPException(404, "job not found")
        return x

    @r.get("/me", response_model=ClientMe)
    def me(cid: str = Depends(client_id)):
        return ps().client_summary(coord(), cid)

    @r.get("/catalogue", response_model=list[CatalogueItem])
    def catalogue(_cid: str = Depends(client_id)):
        return ps().catalogue(coord())

    @r.post("/jobs", status_code=201, response_model=Admitted,
            responses={200: {"model": Admitted, "description": "idempotent replay: the job this key already made"},
                       422: {"model": Rejected, "description": "rejected at admission (or invalid input)"}})
    def submit(body: SubmitIn, response: Response, cid: str = Depends(client_id)):
        if body.type == "live_transcription":  # #127: unbounded live job, leased at once
            from coordinator import transcribe as ts
            res = ts.create_job(coord(), cid, body.idempotency_key, body.access_class, body.client_pub)
            if res.get("created") is False:
                response.status_code = 200
            return res
        if body.deadline_h is None:
            return JSONResponse({"status": "rejected", "reason": "deadline_h is required"}, status_code=422)
        try:
            res = ps().submit_client_job(coord(), cid, type=body.type, access_class=body.access_class,
                                         deadline_h=body.deadline_h, idempotency_key=body.idempotency_key,
                                         rounds=body.rounds, chunks=body.chunks)
        except CoordError as e:
            if e.status == 422 and isinstance(e.detail, dict) and e.detail.get("status") == "rejected":
                return JSONResponse({"status": "rejected", "reason": str(e.detail.get("reason", ""))}, status_code=422)
            raise
        if res.get("created") is False:
            response.status_code = 200
        return res

    @r.get("/jobs", response_model=JobPage)
    def list_jobs(limit: Limit = 50, cursor: Cursor = None, cid: str = Depends(client_id)):
        return ps().list_client_jobs(coord(), cid, limit=limit, cursor=cursor)

    @r.get("/jobs/{job_id}", response_model=JobDetail)
    def get_job(job_id: PathId, cid: str = Depends(client_id)):
        return found(ps().get_client_job(coord(), cid, job_id))

    @r.delete("/jobs/{job_id}", response_model=JobDetail)
    def cancel(job_id: PathId, cid: str = Depends(client_id)):
        return found(ps().cancel_client_job(coord(), cid, job_id))

    @r.get("/jobs/{job_id}/result", response_class=Response,
           responses={200: {"content": {"application/octet-stream": {}},
                            "description": "assembled output; X-Result-SHA256 header"},
                      409: {"description": "not done yet"}})
    def result(job_id: PathId, cid: str = Depends(client_id)):
        data, sha = found(ps().get_result(coord(), cid, job_id))
        return Response(content=data, media_type="application/octet-stream",
                        headers={"X-Result-SHA256": sha, "Cache-Control": "no-store"})

    # ---- #127 live transcription (contracts/src/live_transcribe.md): segments in, transcript out
    @r.post("/jobs/{job_id}/segments", status_code=201)
    async def segment(job_id: PathId, request: Request, response: Response,
                      x_seq: Annotated[int, Header(ge=0, le=10_000_000)], cid: str = Depends(client_id)):
        from coordinator import transcribe as ts
        body = await request.body()
        res = found(await asyncio.to_thread(ts.add_segment, coord(), cid, job_id, x_seq, body))
        if res.get("duplicate"):
            response.status_code = 200
        return res

    @r.post("/jobs/{job_id}/end")
    def end(job_id: PathId, cid: str = Depends(client_id)):
        from coordinator import transcribe as ts
        return found(ts.end_job(coord(), cid, job_id))

    @r.get("/jobs/{job_id}/transcript")
    def transcript(job_id: PathId, cid: str = Depends(client_id)):
        from coordinator import transcribe as ts
        return found(ts.transcript(coord(), cid, job_id))

    @r.get("/jobs/{job_id}/recipients")
    def recipients(job_id: PathId, cid: str = Depends(client_id)):  # live v2: who to wrap each segment for
        from coordinator import transcribe as ts
        return found(ts.recipients(coord(), cid, job_id))

    @r.get("/jobs/{job_id}/transcript/receipt")
    def live_receipt(job_id: PathId, cid: str = Depends(client_id)):  # live v2.1: Merkle root + proofs + audit anchor
        from coordinator import transcribe as ts  # (/receipt stays the batch-job receipt)
        return found(ts.receipt(coord(), cid, job_id))

    @r.get("/jobs/{job_id}/receipt", response_model=Receipt, responses={409: {"description": "not done yet"}})
    def receipt(job_id: PathId, cid: str = Depends(client_id)):
        return found(ps().get_receipt(coord(), cid, job_id))

    return r
