"""P2 (#84): client + host routers against an in-memory fake of P1's portal_store (P1 not merged yet).

The fake keeps the same function names and ownership semantics as coordinator.portal_store: scoped getters return
None for unknown OR foreign ids. The app mirrors the coordinator's create_app: Bearer principal dependency, the
CoordError handler and the input-validation handler. Once P1 lands, an in-process coordinator test replaces it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from coordinator.core import CoordError
from portal import client as pclient
from portal import host as phost

NOW = datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class P:  # same fields P1 agreed on #83
    role: str
    client_id: str | None = None
    site_id: str | None = None
    node_id: str | None = None
    token_id: str = "t"


TOKENS = {"tok-c1": P("client", client_id="c1"), "tok-c2": P("client", client_id="c2"),
          "tok-h1": P("host", site_id="house-a"), "tok-h2": P("host", site_id="house-b"),
          "tok-admin": P("admin"), "tok-site": P("site", site_id="house-a"), "tok-node": P("node", node_id="n1")}


class FakeStore:
    def __init__(self):
        self.calls = []
        self.jobs = {}  # job_id -> dict(client_id, ...)
        self.keys = {}  # (client_id, key) -> job_id
        self.override = {}

    # ---- client
    def client_summary(self, coord, cid):
        mine = [j for j in self.jobs.values() if j["client_id"] == cid]
        return {"client_id": cid, "jobs_total": len(mine), "jobs_running": sum(j["status"] == "running" for j in mine),
                "server_h_used": 1.5, "chf_spent": 2.55}

    def catalogue(self, coord):
        return [{"type": "whisper_transcription", "label": "Transcription", "access_classes": ["swiss-only"],
                 "est_unit_min": 15.0, "price_chf_server_h": 1.7}]

    def submit_client_job(self, coord, cid, *, type, access_class, deadline_h, idempotency_key, rounds=None,
                          chunks=None):
        self.calls.append(("submit", cid, type, access_class, deadline_h, idempotency_key, rounds, chunks))
        if access_class == "certified":
            raise CoordError(422, {"status": "rejected", "reason": "no eligible site"})
        if (cid, idempotency_key) in self.keys:
            return {"job_id": self.keys[(cid, idempotency_key)], "status": "admitted", "eta": None, "created": False}
        jid = f"job-{len(self.jobs) + 1}"
        self.keys[(cid, idempotency_key)] = jid
        self.jobs[jid] = {"client_id": cid, "job_id": jid, "type": type, "access_class": access_class,
                          "status": "queued", "progress": 0.0, "deadline": "2026-11-22T20:00:00Z", "eta": None,
                          "missed_deadline": False, "units": [], "events": []}
        return {"job_id": jid, "status": "admitted", "eta": "2026-11-21T21:00:00Z", "created": True}

    def _own(self, cid, jid):
        j = self.jobs.get(jid)
        return j if j and j["client_id"] == cid else None

    def list_client_jobs(self, coord, cid, *, limit=50, cursor=None):
        self.calls.append(("list", cid, limit, cursor))
        items = [{k: v for k, v in j.items() if k not in ("client_id", "units", "events")}
                 for j in self.jobs.values() if j["client_id"] == cid]
        return {"items": items[::-1][:limit], "next_cursor": None}

    def get_client_job(self, coord, cid, jid):
        j = self._own(cid, jid)
        return None if j is None else {k: v for k, v in j.items() if k != "client_id"}

    def cancel_client_job(self, coord, cid, jid):
        j = self._own(cid, jid)
        if j is None:
            return None
        j["status"] = "cancelled"
        return {k: v for k, v in j.items() if k != "client_id"}

    def get_result(self, coord, cid, jid):
        j = self._own(cid, jid)
        if j is None:
            return None
        if j["status"] != "done":
            raise CoordError(409, "job not done")
        data = b"chunk0\nchunk1\n"
        return data, hashlib.sha256(data).hexdigest()

    def get_receipt(self, coord, cid, jid):
        j = self._own(cid, jid)
        if j is None:
            return None
        if j["status"] != "done":
            raise CoordError(409, "job not done")
        if j.get("receipt_degraded"):  # the real store's None cases: unreadable final bytes, empty audit chain
            return {"result_sha256": None, "chunk_ids": {f"{jid}-u000": [0, 1]}, "nodes_used": [], "kwh": 0.0,
                    "heat_used_kwh": 0.0, "audit_head": None}
        return {"result_sha256": "ab" * 32, "chunk_ids": {f"{jid}-u000": [0, 1], f"{jid}-u001": [0, 1]},
                "nodes_used": ["node-mac"], "kwh": 0.5, "heat_used_kwh": 0.4, "audit_head": "cd" * 32,
                "audit_length": 7}  # same shape as coordinator.portal_store.get_receipt (unit -> chunk ids)

    # ---- host
    def host_site(self, coord, sid):
        if sid not in ("house-a", "house-b"):
            return None
        o = self.override.get(sid, {})
        return {"site_id": sid, "demand_kw": 3.2, "tank_level_kwh": 12.0, "degraded": False,
                "paused": o.get("paused", False), "paused_until": o.get("until"),
                "nodes": [{"node_id": "node-mac" if sid == "house-a" else "node-omen"}],
                "heat_today_kwh": 10.0, "heat_month_kwh": 120.0, "dumped_today_kwh": 0.0, "chf_heat_value_today": 1.33}

    def host_node(self, coord, sid, nid):
        at = {"house-a": "node-mac", "house-b": "node-omen"}.get(sid)
        if nid != at:
            return None
        return {"node_id": nid, "watts": 950.0, "running_unit": "u-1", "progress": 0.4, "last_heartbeat_s": 2.0,
                "state": "online"}

    def set_site_override(self, coord, sid, *, paused, until_ts=None):
        self.calls.append(("override", sid, paused, until_ts))
        self.override[sid] = {"paused": paused,
                              "until": None if until_ts is None else datetime.fromtimestamp(until_ts, timezone.utc).isoformat()}
        return self.host_site(coord, sid)

    def host_history(self, coord, sid, *, hours=24):
        self.calls.append(("history", sid, hours))
        return [{"ts": "2026-11-21T19:00:00Z", "heat_kwh": 3.0, "dumped_kwh": 0.0, "demand_kwh": 3.5}]


def make_app(store, openapi=False):
    app = FastAPI(openapi_url="/openapi.json" if openapi else None)

    def principal(authorization: str | None = Header(None)):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "missing or unknown bearer token")
        p = TOKENS.get(authorization[7:])
        if p is None:
            raise HTTPException(401, "missing or unknown bearer token")
        return p

    @app.exception_handler(CoordError)
    async def _coord_err(_req, e: CoordError):
        return JSONResponse({"detail": e.detail}, status_code=e.status)

    coord = SimpleNamespace(name="fake-coord")
    app.include_router(pclient.make_router(principal, lambda: coord, store=store))
    app.include_router(phost.make_router(principal, lambda: coord, store=store, now=lambda: NOW))
    return app


@pytest.fixture()
def env():
    store = FakeStore()
    return store, TestClient(make_app(store))


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


JOB = {"type": "whisper_transcription", "access_class": "swiss-only", "deadline_h": 24, "idempotency_key": "k-1"}


# ================================================================== client
def test_client_me_and_catalogue(env):
    _, c = env
    me = c.get("/v1/client/me", headers=h("tok-c1"))
    assert me.status_code == 200 and me.json()["client_id"] == "c1"
    cat = c.get("/v1/client/catalogue", headers=h("tok-c1")).json()
    assert cat[0]["type"] == "whisper_transcription" and cat[0]["price_chf_server_h"] == 1.7


@pytest.mark.parametrize("tok,code", [(None, 401), ("nope", 401), ("tok-h1", 403), ("tok-admin", 403),
                                      ("tok-node", 403), ("tok-site", 403)])
def test_client_routes_need_a_client_token(env, tok, code):
    _, c = env
    assert c.get("/v1/client/me", headers=h(tok) if tok else {}).status_code == code


def test_submit_created_then_idempotent_replay(env):
    store, c = env
    r1 = c.post("/v1/client/jobs", json=JOB, headers=h("tok-c1"))
    assert r1.status_code == 201 and r1.json()["status"] == "admitted"
    r2 = c.post("/v1/client/jobs", json=JOB, headers=h("tok-c1"))
    assert r2.status_code == 200 and r2.json()["job_id"] == r1.json()["job_id"]
    assert store.calls[0] == ("submit", "c1", "whisper_transcription", "swiss-only", 24.0, "k-1", None, None)
    assert len(store.jobs) == 1


def test_submit_rejected_is_unwrapped_422(env):
    _, c = env
    r = c.post("/v1/client/jobs", json={**JOB, "access_class": "certified"}, headers=h("tok-c1"))
    assert r.status_code == 422 and r.json() == {"status": "rejected", "reason": "no eligible site"}


@pytest.mark.parametrize("patch", [{"deadline_h": 0.1}, {"deadline_h": 721}, {"deadline_h": "NaN"},
                                   {"access_class": "secret"}, {"idempotency_key": "Bad Key"},
                                   {"type": "../etc"}, {"chunks": 0}, {"rounds": -1}, {"extra": 1}])
def test_submit_validates_input(env, patch):
    store, c = env
    assert c.post("/v1/client/jobs", json={**JOB, **patch}, headers=h("tok-c1")).status_code == 422
    assert not store.calls


def test_foreign_and_unknown_jobs_are_404_never_403(env):
    _, c = env
    jid = c.post("/v1/client/jobs", json=JOB, headers=h("tok-c1")).json()["job_id"]
    assert c.get(f"/v1/client/jobs/{jid}", headers=h("tok-c1")).status_code == 200
    for path in (f"/v1/client/jobs/{jid}", f"/v1/client/jobs/{jid}/result", f"/v1/client/jobs/{jid}/receipt"):
        assert c.get(path, headers=h("tok-c2")).status_code == 404
    assert c.delete(f"/v1/client/jobs/{jid}", headers=h("tok-c2")).status_code == 404
    assert c.get("/v1/client/jobs/job-999", headers=h("tok-c1")).status_code == 404
    assert c.get("/v1/client/jobs/BAD_ID", headers=h("tok-c1")).status_code == 422


def test_list_is_scoped_and_paginated(env):
    store, c = env
    c.post("/v1/client/jobs", json=JOB, headers=h("tok-c1"))
    c.post("/v1/client/jobs", json={**JOB, "idempotency_key": "k-2"}, headers=h("tok-c2"))
    page = c.get("/v1/client/jobs?limit=10", headers=h("tok-c1")).json()
    assert [j["job_id"] for j in page["items"]] == ["job-1"] and page["next_cursor"] is None
    assert c.get("/v1/client/jobs?limit=0", headers=h("tok-c1")).status_code == 422
    assert c.get("/v1/client/jobs?limit=201", headers=h("tok-c1")).status_code == 422
    assert c.get("/v1/client/jobs?cursor=%27;drop", headers=h("tok-c1")).status_code == 422


def test_cancel_is_idempotent(env):
    _, c = env
    jid = c.post("/v1/client/jobs", json=JOB, headers=h("tok-c1")).json()["job_id"]
    for _ in range(2):
        r = c.delete(f"/v1/client/jobs/{jid}", headers=h("tok-c1"))
        assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_result_409_until_done_then_bytes_with_sha(env):
    store, c = env
    jid = c.post("/v1/client/jobs", json=JOB, headers=h("tok-c1")).json()["job_id"]
    assert c.get(f"/v1/client/jobs/{jid}/result", headers=h("tok-c1")).status_code == 409
    assert c.get(f"/v1/client/jobs/{jid}/receipt", headers=h("tok-c1")).status_code == 409
    store.jobs[jid]["status"] = "done"
    r = c.get(f"/v1/client/jobs/{jid}/result", headers=h("tok-c1"))
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-result-sha256"] == hashlib.sha256(r.content).hexdigest()
    rc = c.get(f"/v1/client/jobs/{jid}/receipt", headers=h("tok-c1")).json()
    assert rc["nodes_used"] == ["node-mac"] and len(rc["audit_head"]) == 64 and rc["audit_length"] == 7
    assert rc["chunk_ids"] == {f"{jid}-u000": [0, 1], f"{jid}-u001": [0, 1]}


def test_receipt_passes_through_the_stores_none_fields(env):
    store, c = env
    jid = c.post("/v1/client/jobs", json=JOB, headers=h("tok-c1")).json()["job_id"]
    store.jobs[jid] |= {"status": "done", "receipt_degraded": True}
    r = c.get(f"/v1/client/jobs/{jid}/receipt", headers=h("tok-c1"))
    assert r.status_code == 200, r.text
    assert r.json()["result_sha256"] is None and r.json()["audit_head"] is None


# ================================================================== host
def test_host_site_and_own_node(env):
    _, c = env
    s = c.get("/v1/host/site", headers=h("tok-h1")).json()
    assert s["site_id"] == "house-a" and s["nodes"][0]["node_id"] == "node-mac"
    n = c.get("/v1/host/nodes/node-mac", headers=h("tok-h1"))
    assert n.status_code == 200 and n.json()["state"] == "online"


def test_host_cannot_see_other_sites_node(env):
    _, c = env
    assert c.get("/v1/host/nodes/node-omen", headers=h("tok-h1")).status_code == 404
    assert c.get("/v1/host/nodes/node-mac", headers=h("tok-h2")).status_code == 404


@pytest.mark.parametrize("tok,code", [(None, 401), ("tok-c1", 403), ("tok-site", 403), ("tok-admin", 403)])
def test_host_routes_need_a_host_token(env, tok, code):
    _, c = env
    assert c.get("/v1/host/site", headers=h(tok) if tok else {}).status_code == code


def test_pause_resume_override(env):
    store, c = env
    r = c.post("/v1/host/site/pause", headers=h("tok-h1"))
    assert r.status_code == 200 and r.json()["paused"] is True
    until = (NOW + timedelta(hours=8)).isoformat()
    r = c.post("/v1/host/site/pause", json={"until": until}, headers=h("tok-h1"))
    assert r.status_code == 200 and store.calls[-1] == ("override", "house-a", True, (NOW + timedelta(hours=8)).timestamp())
    r = c.post("/v1/host/site/resume", headers=h("tok-h1"))
    assert r.status_code == 200 and r.json()["paused"] is False
    assert store.calls[-1] == ("override", "house-a", False, None)


@pytest.mark.parametrize("body", [{"until": (NOW - timedelta(minutes=1)).isoformat()},
                                  {"until": (NOW + timedelta(days=31)).isoformat()},
                                  {"until": "not a date"}, {"until": None, "x": 1}])
def test_pause_validates_until(env, body):
    store, c = env
    assert c.post("/v1/host/site/pause", json=body, headers=h("tok-h1")).status_code == 422
    assert not [x for x in store.calls if x[0] == "override"]


def test_history_hours_bounds(env):
    store, c = env
    assert c.get("/v1/host/history", headers=h("tok-h1")).json()[0]["heat_kwh"] == 3.0
    assert store.calls[-1] == ("history", "house-a", 24)
    assert c.get("/v1/host/history?hours=0", headers=h("tok-h1")).status_code == 422
    assert c.get("/v1/host/history?hours=721", headers=h("tok-h1")).status_code == 422


# ================================================================== openapi
def test_openapi_describes_every_route_with_a_response_model():
    spec = TestClient(make_app(FakeStore(), openapi=True)).get("/openapi.json").json()
    want = {("/v1/client/me", "get"), ("/v1/client/catalogue", "get"), ("/v1/client/jobs", "post"),
            ("/v1/client/jobs", "get"), ("/v1/client/jobs/{job_id}", "get"), ("/v1/client/jobs/{job_id}", "delete"),
            ("/v1/client/jobs/{job_id}/result", "get"), ("/v1/client/jobs/{job_id}/receipt", "get"),
            ("/v1/host/site", "get"), ("/v1/host/nodes/{node_id}", "get"), ("/v1/host/site/pause", "post"),
            ("/v1/host/site/resume", "post"), ("/v1/host/history", "get")}
    have = {(p, m) for p, ops in spec["paths"].items() for m in ops}
    assert want <= have
    for p, m in want - {("/v1/client/jobs/{job_id}/result", "get")}:
        assert "$ref" in str(spec["paths"][p][m]["responses"]["200" if not (p, m) == ("/v1/client/jobs", "post")
                                                              else "201"]), (p, m)
