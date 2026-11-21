"""In-process fake of the coordinator v1 node protocol, for live_agent tests (the real one is #52, macmini).

Only what the agent talks to: register / heartbeat / lease / renew / checkpoint (raw body + X-* headers) /
checkpoint latest / complete, with bearer auth. Test knobs inject 5xx, holds, lapses and key denials.
Uses the real trust.KeyBroker and live_agent.wire codecs.
"""
from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response

from live_agent import wire
from trust import Denied, KeyBroker

REGION = "CH-BS"


@dataclass
class FakeUnit:
    unit_id: str
    job_id: str
    job_type: str = "image_tagging"
    access_class: str = "public"
    chunks: int = 40
    rounds: int | None = None
    done: bool = False
    result_sha256: str | None = None
    chunk_ids: list[int] | None = None
    completions: int = 0


@dataclass
class Lease:
    lease_id: str
    unit_id: str
    node_id: str
    lapsed: bool = False
    paused: bool = False  # renew said hold; the node may still upload its final checkpoint


@dataclass
class Knobs:
    fail_next: int = 0  # next N node calls answer 503
    fail_renew: bool = False  # every renew answers 503 (coordinator "unreachable" mid-lease)
    hold_renew: bool = False  # renew answers {hold}: the node must pause
    lapse_on_renew: bool = False  # renew answers 410
    expires_in_s: float = 15.0
    renew_every_s: float = 5.0


@dataclass
class FakeCoordinator:
    tokens: dict[str, str] = field(default_factory=lambda: {"tok-a": "node-a", "tok-b": "node-b"})
    broker: KeyBroker = field(default_factory=KeyBroker)
    units: dict[str, FakeUnit] = field(default_factory=dict)
    leases: dict[str, Lease] = field(default_factory=dict)
    checkpoints: dict[str, list[tuple[bytes, dict[str, str]]]] = field(default_factory=dict)
    heartbeats: list[dict[str, Any]] = field(default_factory=list)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    knobs: Knobs = field(default_factory=Knobs)
    calls: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    _ids: Any = field(default_factory=lambda: itertools.count())

    # ---------------------------------------------------------------- test helpers (not HTTP)
    def submit(self, unit_id: str, **kw) -> FakeUnit:
        u = FakeUnit(unit_id, kw.pop("job_id", f"job-{unit_id}"), **kw)
        self.units[unit_id] = u
        self.broker.register_job(u.job_id, "cust", u.access_class)
        return u

    def lapse_all(self) -> None:
        for lease in self.leases.values():
            lease.lapsed = True

    # ---------------------------------------------------------------- app
    def app(self) -> FastAPI:
        app = FastAPI()
        c = self

        def node_of(auth: str | None, node_id: str | None = None) -> str:
            if not auth or not auth.startswith("Bearer ") or auth[7:] not in c.tokens:
                raise HTTPException(401, "unknown token")
            nid = c.tokens[auth[7:]]
            if node_id is not None and node_id != nid:
                raise HTTPException(403, "wrong node")
            return nid

        def maybe_fail(name: str) -> None:
            c.calls.append(name)
            if c.knobs.fail_next > 0:
                c.knobs.fail_next -= 1
                raise HTTPException(503, "injected")

        def live_lease(lease_id: str, nid: str) -> Lease:
            lease = c.leases.get(lease_id)
            if lease is None or lease.node_id != nid:
                raise HTTPException(404, "no such lease")
            if lease.lapsed:
                raise HTTPException(410, "lease lapsed")
            return lease

        @app.post("/v1/nodes/register")
        async def register(req: Request, authorization: str | None = Header(None)):
            body = await req.json()
            nid = node_of(authorization, body.get("node_id"))
            maybe_fail("register")
            att = wire.attestation_from_json(body["attestation"])
            if not att.is_valid() or att.node_id != nid:
                raise HTTPException(403, "bad attestation")
            c.nodes[nid] = {**body, "att": att}
            return {"ok": True}

        @app.post("/v1/nodes/{node_id}/heartbeat")
        async def heartbeat(node_id: str, req: Request, authorization: str | None = Header(None)):
            node_of(authorization, node_id)
            c.heartbeats.append({"node_id": node_id, **(await req.json())})
            return {"ok": True}

        @app.post("/v1/nodes/{node_id}/lease")
        def lease(node_id: str, authorization: str | None = Header(None)):
            nid = node_of(authorization, node_id)
            maybe_fail("lease")
            with c.lock:
                busy = {lz.unit_id for lz in c.leases.values() if not lz.lapsed and not lz.paused}
                pending = [u for u in c.units.values() if not u.done and u.unit_id not in busy]
                if not pending:
                    return {"hold": True, "reason": "queue empty", "retry_after_s": 0.01}
                u = pending[0]
                res = c.broker.release(u.job_id, nid, c.nodes[nid]["att"], REGION)
                if isinstance(res, Denied):
                    return {"hold": True, "reason": f"key denied: {res.reason}", "retry_after_s": 0.01}
                lid = f"lease-{next(c._ids)}"
                c.leases[lid] = Lease(lid, u.unit_id, nid)
                unit = {"unit_id": u.unit_id, "job_id": u.job_id, "job_type": u.job_type,
                        "access_class": u.access_class, "chunks": u.chunks}
                if u.rounds:
                    unit["rounds"] = u.rounds
                return {"unit": unit, "lease_id": lid, "expires_in_s": c.knobs.expires_in_s,
                        "renew_every_s": c.knobs.renew_every_s,
                        "checkpoint_url": f"/v1/checkpoints/{u.unit_id}/latest" if c.checkpoints.get(u.unit_id)
                        else None,
                        "key_release": {**wire.key_to_json(res.key), "job_id": u.job_id}}

        @app.post("/v1/leases/{lease_id}/renew")
        def renew(lease_id: str, authorization: str | None = Header(None)):
            nid = node_of(authorization)
            c.calls.append("renew")
            if c.knobs.fail_renew:
                raise HTTPException(503, "injected")
            lz = live_lease(lease_id, nid)
            if c.knobs.lapse_on_renew:
                lz.lapsed = True
                raise HTTPException(410, "lease lapsed")
            if c.knobs.hold_renew:
                lz.paused = True  # the coordinator takes the unit back; the node pauses and uploads
                return {"hold": True, "reason": "heat not wanted"}
            return {"ok": True, "expires_in_s": c.knobs.expires_in_s}

        @app.post("/v1/leases/{lease_id}/checkpoint")
        async def upload(lease_id: str, req: Request, authorization: str | None = Header(None)):
            nid = node_of(authorization)
            maybe_fail("checkpoint")
            lz = live_lease(lease_id, nid)
            body = await req.body()
            if req.headers.get("X-Sha256") != wire.sha256_hex(body):
                raise HTTPException(422, "sha256 mismatch")
            hdr = {k: req.headers[k] for k in ("X-Next-Chunk", "X-Out-Bytes", "X-Sha256")}
            c.checkpoints.setdefault(lz.unit_id, []).append((body, hdr))
            if lz.paused:  # final upload after a pause: release the unit
                lz.lapsed = True
            return {"ok": True, "seq": len(c.checkpoints[lz.unit_id])}

        @app.get("/v1/checkpoints/{unit_id}/latest")
        def latest(unit_id: str, authorization: str | None = Header(None)):
            nid = node_of(authorization)
            if not any(lz.unit_id == unit_id and lz.node_id == nid and not lz.lapsed for lz in c.leases.values()):
                raise HTTPException(403, "not the lease holder")
            if not c.checkpoints.get(unit_id):
                raise HTTPException(404, "no checkpoint")
            body, hdr = c.checkpoints[unit_id][-1]
            return Response(body, media_type="application/octet-stream",
                            headers={**hdr, "X-Seq": str(len(c.checkpoints[unit_id]))})

        @app.post("/v1/leases/{lease_id}/complete")
        async def complete(lease_id: str, req: Request, authorization: str | None = Header(None)):
            nid = node_of(authorization)
            maybe_fail("complete")
            lz = live_lease(lease_id, nid)
            body = await req.json()
            u = c.units[lz.unit_id]
            if u.done:
                if u.result_sha256 != body["result_sha256"]:
                    raise HTTPException(409, "conflicting result")
                return {"ok": True, "duplicate": True}
            u.done, u.result_sha256, u.chunk_ids = True, body["result_sha256"], body["chunk_ids"]
            u.completions += 1
            lz.lapsed = True
            return {"ok": True}

        return app
