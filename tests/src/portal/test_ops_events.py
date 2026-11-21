"""#85 portal P3: ops API + live events, against an in-memory backend (P1's portal_store plugs in later)."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from coordinator.auth import Principal
from portal import events as ev
from portal import ops

TOKENS = {"tok-admin": Principal("admin", token_id="0"), "tok-obs": Principal("observer", token_id="1"),
          "tok-node": Principal("node", node_id="node-a", token_id="2"),
          "tok-client": Principal("client", token_id="3"), "tok-host": Principal("host", site_id="site-a", token_id="4")}


def principal(authorization: str | None = Header(None)) -> Principal:
    if not authorization or not authorization.startswith("Bearer ") or authorization[7:] not in TOKENS:
        raise HTTPException(401, "missing or unknown bearer token")
    return TOKENS[authorization[7:]]


class FakeBackend:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.drained: set[str] = set()
        self.calls: list[tuple] = []
        self.lock = threading.Lock()

    def emit(self, type_: str, **data) -> int:
        with self.lock:
            i = len(self.events) + 1
            self.events.append({"id": i, "type": type_, "ts": "2026-11-21T19:00:00Z", "data": data})
            return i

    # role filter, as P1 does it in SQL
    def _visible(self, p, e) -> bool:
        if p.role in ("admin", "observer"):
            return True
        if p.role == "host":
            return e["data"].get("site_id") == p.site_id
        return False

    def events_after(self, p, after_id, limit=200):
        with self.lock:
            return [e for e in self.events if e["id"] > after_id and self._visible(p, e)][:limit]

    def events_head(self):
        return len(self.events)

    def ops_overview(self):
        return {"nodes": {"online": 2, "suspect": 0, "offline": 1}, "jobs": {"queued": 1, "running": 1, "done": 3,
                "failed": 0}, "leases_active": 1, "heat_used_kwh_today": 12.5, "dumped_kwh_today": 0.0,
                "missed_deadline_pct": 0.0, "degraded_sites": [], "audit": {"ok": True, "head": "ab" * 32,
                                                                           "length": 7}}

    def _page(self, name, limit, cursor):
        self.calls.append((name, limit, cursor))
        return {"items": [{"id": f"{name}-{i}"} for i in range(limit)], "next_cursor": "c2"}

    def ops_nodes(self, limit, cursor):
        return self._page("nodes", limit, cursor)

    def ops_jobs(self, limit, cursor):
        return self._page("jobs", limit, cursor)

    def ops_sites(self, limit, cursor):
        return self._page("sites", limit, cursor)

    def ops_audit(self, limit, cursor):
        return {**self._page("audit", limit, cursor), "verify": {"ok": True, "head": "ab" * 32, "length": 7}}

    def drain_node(self, node_id, drained):
        if node_id == "missing":
            raise HTTPException(404, "unknown node")
        changed = (node_id in self.drained) != drained
        (self.drained.add if drained else self.drained.discard)(node_id)
        if changed:
            self.emit("node.state", node_id=node_id, drained=drained)
        return {"node_id": node_id, "drained": drained, "changed": changed}

    def kill_node(self, node_id):
        self.calls.append(("kill", node_id))
        return {"node_id": node_id, "revoked_lease": "l-1"}

    def tamper(self, node_id):
        return {"node_id": node_id}

    def set_site_scenario(self, site_id, replay):
        self.calls.append(("scenario", site_id, replay))
        return {"site_id": site_id, "replay": replay, "changed": True}


@pytest.fixture
def be():
    return FakeBackend()


@pytest.fixture
def app(be):
    a = FastAPI()
    a.include_router(ops.make_router(principal, lambda: be))
    a.include_router(ev.make_router(principal, lambda: be, poll_s=0.01, keepalive_s=0.05))
    return a


def c(app, tok=None):
    return TestClient(app, headers={"Authorization": f"Bearer {tok}"} if tok else {})


# ------------------------------------------------------------------ ops: roles
GETS = ["/v1/ops/overview", "/v1/ops/nodes", "/v1/ops/jobs", "/v1/ops/sites", "/v1/ops/audit"]
POSTS = ["/v1/ops/nodes/node-a/drain", "/v1/ops/nodes/node-a/undrain", "/v1/ops/nodes/node-a/kill",
         "/v1/ops/nodes/node-a/tamper"]


@pytest.mark.parametrize("path", GETS)
def test_ops_reads_admin_and_observer_only(app, path):
    assert c(app).get(path).status_code == 401
    for tok in ("tok-admin", "tok-obs"):
        assert c(app, tok).get(path).status_code == 200, (tok, path)
    for tok in ("tok-node", "tok-client", "tok-host"):
        assert c(app, tok).get(path).status_code == 403, (tok, path)


@pytest.mark.parametrize("path", POSTS + ["/v1/ops/sites/site-a/scenario"])
def test_ops_actions_admin_only(app, path):
    body = {"replay": "july"} if path.endswith("scenario") else None
    assert c(app, "tok-admin").post(path, json=body).status_code == 200, path
    for tok in ("tok-obs", "tok-node", "tok-client", "tok-host"):
        assert c(app, tok).post(path, json=body).status_code == 403, (tok, path)


def test_overview_shape(app):
    o = c(app, "tok-obs").get("/v1/ops/overview").json()
    assert set(o) >= {"nodes", "jobs", "leases_active", "heat_used_kwh_today", "dumped_kwh_today",
                      "missed_deadline_pct", "degraded_sites", "audit"}
    assert o["audit"]["ok"] is True


# ------------------------------------------------------------------ ops: validation
@pytest.mark.parametrize("bad", ["..%2Fetc", "UPPER", "a_b", "x" * 65, "%00"])
def test_ops_hostile_ids_rejected(app, bad, be):
    r = c(app, "tok-admin").post(f"/v1/ops/nodes/{bad}/kill")
    assert r.status_code in (404, 422)
    assert not [x for x in be.calls if x[0] == "kill"]  # never reached the backend


def test_pagination_bounds(app, be):
    cl = c(app, "tok-admin")
    assert cl.get("/v1/ops/nodes?limit=200").status_code == 200
    for q in ("limit=0", "limit=201", "limit=-1", "cursor=../x", "cursor=" + "a" * 129):
        assert cl.get(f"/v1/ops/nodes?{q}").status_code == 422, q
    r = cl.get("/v1/ops/jobs?limit=3&cursor=c2").json()
    assert len(r["items"]) == 3 and r["next_cursor"] == "c2" and be.calls[-1] == ("jobs", 3, "c2")


def test_scenario_body_strict(app):
    cl = c(app, "tok-admin")
    assert cl.post("/v1/ops/sites/site-a/scenario", json={"replay": "year"}).status_code == 422  # only coldest|july
    assert cl.post("/v1/ops/sites/site-a/scenario", json={"replay": "july", "x": 1}).status_code == 422
    assert cl.post("/v1/ops/sites/site-a/scenario", json={}).status_code == 422


def test_drain_idempotent_and_emits_once(app, be):
    cl = c(app, "tok-admin")
    a = cl.post("/v1/ops/nodes/node-a/drain").json()
    b = cl.post("/v1/ops/nodes/node-a/drain").json()
    assert (a["changed"], b["changed"]) == (True, False) and a["drained"] and b["drained"]
    assert [e["type"] for e in be.events] == ["node.state"]
    assert cl.post("/v1/ops/nodes/node-a/undrain").json()["drained"] is False
    assert cl.post("/v1/ops/nodes/missing/drain").status_code == 404


def test_openapi_describes_every_route(app):
    spec = c(app).get("/openapi.json").json()
    paths = spec["paths"]
    for p in ["/v1/ops/overview", "/v1/ops/nodes", "/v1/ops/jobs", "/v1/ops/sites", "/v1/ops/audit",
              "/v1/ops/nodes/{node_id}/drain", "/v1/ops/nodes/{node_id}/undrain", "/v1/ops/nodes/{node_id}/kill",
              "/v1/ops/nodes/{node_id}/tamper", "/v1/ops/sites/{site_id}/scenario", "/v1/events", "/v1/events/poll"]:
        assert p in paths, p
    ov = paths["/v1/ops/overview"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ov.get("$ref", "").endswith("/Overview")  # a response model, for the frontend's codegen
    assert "text/event-stream" in paths["/v1/events"]["get"]["responses"]["200"]["content"]


# ------------------------------------------------------------------ events: poll
def test_poll_filters_by_role_and_resumes(app, be):
    be.emit("site.signal", site_id="site-a", demand_kw=3.0)
    be.emit("site.signal", site_id="site-b", demand_kw=1.0)
    be.emit("lease.granted", node_id="node-a")
    admin = c(app, "tok-admin").get("/v1/events/poll?after=0").json()
    assert [e["id"] for e in admin["events"]] == [1, 2, 3] and admin["last_id"] == 3
    host = c(app, "tok-host").get("/v1/events/poll?after=0").json()
    assert [e["data"]["site_id"] for e in host["events"]] == ["site-a"]  # only its own site
    assert c(app, "tok-client").get("/v1/events/poll?after=0").json() == {"events": [], "last_id": 0}
    assert c(app, "tok-admin").get("/v1/events/poll?after=2").json()["last_id"] == 3
    assert c(app, "tok-admin").get("/v1/events/poll?after=3").json() == {"events": [], "last_id": 3}
    for q in ("after=-1", "after=x", "limit=0", "limit=201"):
        assert c(app, "tok-admin").get(f"/v1/events/poll?{q}").status_code == 422, q


# ------------------------------------------------------------------ events: SSE
def read_sse(resp, n: int, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Parse up to n events from a streaming response."""
    out, cur, t0 = [], {}, time.time()
    for line in resp.iter_lines():
        if time.time() - t0 > timeout:
            break
        if line == "":
            if cur:
                out.append(cur)
                cur = {}
                if len(out) >= n:
                    break
            continue
        if line.startswith(":"):
            continue
        k, _, v = line.partition(": ")
        cur[k] = v
    return out


def released(slots, key="0", timeout=5.0) -> bool:
    """The stream's finally runs on the server task just after the client side closes: wait for it."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if slots.count(key) == 0:
            return True
        time.sleep(0.01)
    return False


def stream_app(be, **kw):
    a = FastAPI()
    r = ev.make_router(principal, lambda: be, poll_s=0.01, keepalive_s=0.05, **kw)
    a.include_router(r)
    return a, r


def test_sse_streams_new_events_with_ids_and_resumes_from_last_event_id(be):
    a, r = stream_app(be, max_events=2)
    for i in range(3):
        be.emit("unit.progress", unit_id=f"u-{i}", site_id="site-a")
    with c(a, "tok-admin").stream("GET", "/v1/events", headers={"Last-Event-ID": "1"}) as resp:
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
        got = read_sse(resp, 2)
    assert [int(e["id"]) for e in got] == [2, 3] and got[0]["event"] == "unit.progress"
    assert json.loads(got[1]["data"])["data"]["unit_id"] == "u-2"
    assert released(r.slots)  # slot released when the stream ended


def test_sse_without_last_event_id_starts_at_head(be):
    a, _ = stream_app(be, max_events=1)
    be.emit("old.event")
    be.emit("old.event")

    def later():
        time.sleep(0.2)
        be.emit("lease.granted", node_id="n")
    threading.Thread(target=later, daemon=True).start()
    with c(a, "tok-admin").stream("GET", "/v1/events") as resp:
        got = read_sse(resp, 1)
    assert [e["event"] for e in got] == ["lease.granted"] and got[0]["id"] == "3"


def test_sse_query_resume_and_bad_ids(be):
    a, _ = stream_app(be, max_events=1)
    be.emit("x")
    be.emit("y")
    with c(a, "tok-admin").stream("GET", "/v1/events?last_event_id=1") as resp:
        assert read_sse(resp, 1)[0]["event"] == "y"
    for h in ("abc", "-1", "1e9", "9" * 30):
        assert c(a, "tok-admin").get("/v1/events", headers={"Last-Event-ID": h}).status_code == 422, h


def test_sse_role_filtered(be):
    a, _ = stream_app(be, max_events=1)
    be.emit("site.signal", site_id="site-b")
    be.emit("site.signal", site_id="site-a")
    with c(a, "tok-host").stream("GET", "/v1/events", headers={"Last-Event-ID": "0"}) as resp:
        got = read_sse(resp, 1)
    assert [json.loads(e["data"])["data"]["site_id"] for e in got] == ["site-a"]


def test_sse_requires_auth(be):
    a, _ = stream_app(be)
    assert c(a).get("/v1/events").status_code == 401


def test_sse_max_four_streams_per_token(be):
    a, r = stream_app(be, max_events=1)
    for _ in range(4):
        assert r.slots.acquire("0")
    assert c(a, "tok-admin").get("/v1/events").status_code == 429
    assert r.slots.count("0") == 4  # a refused stream does not leak a slot
    for _ in range(4):
        r.slots.release("0")
    be.emit("x")
    with c(a, "tok-admin").stream("GET", "/v1/events", headers={"Last-Event-ID": "0"}) as resp:
        assert read_sse(resp, 1)
    assert released(r.slots)
    assert c(a, "tok-obs").get("/v1/events/poll").status_code == 200  # poll is not a stream


# ------------------------------------------------------------------ events: the ASGI stream itself
def run_stream(stream, receive, send):
    asyncio.run(stream({"type": "http"}, receive, send))


def test_slow_consumer_is_dropped_not_buffered():
    closed = []
    events = [{"id": i, "type": "t", "ts": "z", "data": {}} for i in range(1, 1000)]
    s = ev.EventStream(lambda after: [e for e in events if e["id"] > after][:200], 0, lambda: closed.append(1),
                       poll_s=0.01, keepalive_s=60, send_timeout_s=0.05)
    sent = []

    async def receive():
        await asyncio.sleep(3600)

    async def send(msg):
        if msg["type"] == "http.response.body" and msg.get("body", b"").startswith(b"id: 3\n"):
            await asyncio.sleep(1)  # the consumer stalls on event 3
        sent.append(msg)
    t0 = time.time()
    run_stream(s, receive, send)
    assert s.dropped and closed == [1]
    assert time.time() - t0 < 2  # dropped at the send deadline, not after draining 999 events
    assert sum(1 for m in sent if m.get("body", b"").startswith(b"id: ")) <= 3


def test_disconnect_ends_stream_and_releases():
    closed = []
    s = ev.EventStream(lambda after: [], 0, lambda: closed.append(1), poll_s=0.01, keepalive_s=0.02)
    calls = {"n": 0}

    async def receive():
        calls["n"] += 1
        await asyncio.sleep(0.1)
        return {"type": "http.disconnect"}
    sent = []

    async def send(msg):
        sent.append(msg)
    t0 = time.time()
    run_stream(s, receive, send)
    assert closed == [1] and time.time() - t0 < 2
    assert any(m.get("body") == b": keep-alive\n\n" for m in sent)  # keep-alive comments while idle


def test_backend_error_releases_slot():
    closed = []

    def boom(after):
        raise RuntimeError("db down")
    s = ev.EventStream(boom, 0, lambda: closed.append(1), poll_s=0.01)

    async def receive():
        await asyncio.sleep(3600)

    async def send(msg):
        pass
    with pytest.raises(RuntimeError):
        run_stream(s, receive, send)
    assert closed == [1]


def test_event_format_is_one_data_line():
    raw = ev.format_event({"id": 7, "type": "job.state", "ts": "t", "data": {"note": "a\nb"}}).decode()
    lines = raw.split("\n")
    assert lines[0] == "id: 7" and lines[1] == "event: job.state" and lines[2].startswith("data: ")
    assert raw.endswith("\n\n") and raw.count("\n") == 4  # the newline inside data is escaped
