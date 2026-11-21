"""Red team round 4, macmini part (#65): live attacks on the deployed coordinator, reproduced in-process.

Found against the LIVE coordinator (https://dhruvs-mac-mini.tailaf7ebe.ts.net) with the node token `node-rt-mac` and
the observer token only (never admin), then reproduced here against `coordinator.app.create_app` + TestClient (no
network). Complements test_redteam_r4_live.py (design's pass, no findings) with four findings it did not cover.
Convention: a confirmed vulnerability is `xfail(strict=True)`; the fix flips it to XPASS and drops the marker.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

import trust
from coordinator.app import create_app
from coordinator.core import CHUNKS_PER_UNIT

T0 = 1_764_000_000.0  # 2025-11-24, a winter hour
TOK = {"admin": "A" * 40, "observer": "O" * 40, "node-a": "a" * 40, "node-b": "b" * 40, "site-b": "s" * 40}
ROLES = {TOK["admin"]: "admin", TOK["observer"]: "observer", TOK["node-a"]: "node:node-a",
         TOK["node-b"]: "node:node-b", TOK["site-b"]: "site:site-b"}


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def H(who):
    return {"Authorization": f"Bearer {TOK[who]}"}


@pytest.fixture
def env(tmp_path, request):
    clock = Clock()
    app = create_app(tmp_path, tokens=ROLES, clock=clock, registry={
        "node-a": {"certified": False, "max_classes": ["public"], "region": "CH-BS", "site_id": "nowhere" if "f33" in request.node.name or "heat_bypasses" in request.node.name else "site-a"},
        "node-b": {"certified": False, "max_classes": ["public"], "region": "CH-BS", "site_id": "site-b"}})
    if hasattr(app.state, "limiter"):
        app.state.limiter.clock = clock
    return type("Env", (), {"clock": clock, "app": app, "client": staticmethod(lambda: TestClient(app))})


def attestation(node):
    ev = {"measurement": "digitalheat-node-image-v1", "region": "CH-BS", "certified": False}
    a = trust.attest(node, ev)
    return {"node_id": node, "evidence": ev, "signature_b64": base64.b64encode(a.signature).decode(), "mock": True}


def register(c, node, site):
    r = c.post("/v1/nodes/register", headers=H(node), json={
        "node_id": node, "site_id": site, "eligible_classes": ["public"], "server_kw_el": 1.0,
        "attestation": attestation(node)})
    assert r.status_code == 200, r.text


def submit(c, **kw):
    r = c.post("/v1/jobs", headers=H("admin"), json={"job_type": "image_tagging", "customer_id": "c", "force": True, **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ================================================================== F33 heartbeat heat bypasses the site signal
def test_finding_node_reported_heat_bypasses_site_signal(env):
    """v1.1 moved heat to POST /v1/sites/{id}/signal (site token only), but core._with_signal falls back to the legacy
    heartbeat fields when the node's site has no signal row, and site_id is self-chosen at register. Live: node-rt-mac
    registered site 'rt-mac' (no signal) and heartbeat demand_kw=9999 was accepted. Here the attacker picks a
    signal-less site, claims 9999 kW and takes the paid unit from the honest node whose site really wants heat."""
    c = env.client()
    register(c, "node-b", "site-b")  # honest node, heat comes from its site sensor
    assert c.post("/v1/sites/site-b/signal", headers=H("site-b"),
                  json={"demand_kw": 3.0, "tank_level_kwh": 5.0, "ts": T0}).status_code == 200
    register(c, "node-a", "nowhere")  # attacker: a site no sensor reports for
    c.post("/v1/nodes/node-a/heartbeat", headers=H("node-a"), json={"demand_kw": 9999.0, "tank_level_kwh": 0.0})
    submit(c)
    got = c.post("/v1/nodes/node-a/lease", headers=H("node-a")).json()
    st = c.get("/v1/status", headers=H("observer")).json()
    attacker = next(n for n in st["nodes"] if n["node_id"] == "node-a")
    # expected after a fix: self-reported heat is ignored (or the node is degraded and gets no heat-led work)
    assert "hold" in got or attacker["degraded"], (got, attacker)


# ================================================================== F34 slow body upload never times out
@pytest.mark.xfail(strict=True, reason="#65 r4 F34: a slow request body holds a worker forever (slow-loris)")
def test_finding_slow_body_has_no_read_timeout(env):
    """Live: one TLS connection sent headers with Content-Length 200 and then 1 byte every 5 s; after 29 s the server
    had not answered or closed it (healthz stayed 200). uvicorn runs with limit_concurrency=64, so 64 such connections
    (no valid token needed: the body is read before auth answers) would lock everyone out. Here the ASGI app is fed a
    body that never completes; a fix (body-read deadline in the BodyLimit middleware, then 408) answers in time."""
    sent: list[dict] = []

    async def receive():
        await asyncio.sleep(3600)  # the client never sends the rest of the body
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "https",
             "path": "/v1/nodes/node-a/heartbeat", "raw_path": b"/v1/nodes/node-a/heartbeat", "query_string": b"",
             "root_path": "", "server": ("test", 443), "client": ("1.2.3.4", 1234),
             "headers": [(b"host", b"test"), (b"authorization", f"Bearer {TOK['node-a']}".encode()),
                         (b"content-type", b"application/json"), (b"content-length", b"200")]}

    async def run():
        try:
            await asyncio.wait_for(env.app(scope, receive, send), timeout=5)
        except asyncio.TimeoutError:
            pass

    asyncio.run(run())
    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert starts and starts[0]["status"] in (400, 408, 413), sent


# ================================================================== F35 completing a unit without doing any work
@pytest.mark.xfail(strict=True, reason="#65 r4 F35: a unit can be completed 0 s after its lease, without any work")
def test_finding_complete_without_any_work(env):
    """complete() checks only the chunk-id set and result-hash consistency. A node can lease a ~15-minute unit and
    complete it in the same second with an invented hash, no checkpoint and no progress: the work is counted as done
    (and paid). A cheap plausibility gate: reject completion earlier than a fraction of the unit's minimum runtime
    (kwh_el / server_kw_el), or without at least one checkpoint (422 + audit)."""
    c = env.client()
    register(c, "node-a", "site-a")
    c.post("/v1/nodes/node-a/heartbeat", headers=H("node-a"), json={"demand_kw": 5.0, "tank_level_kwh": 5.0})
    submit(c)
    L = c.post("/v1/nodes/node-a/lease", headers=H("node-a")).json()
    r = c.post(f"/v1/leases/{L['lease_id']}/complete", headers=H("node-a"),
               json={"result_sha256": hashlib.sha256(b"never ran").hexdigest(), "chunk_ids": list(range(CHUNKS_PER_UNIT))})
    assert r.status_code >= 400, r.text


# ================================================================== F36 unbounded audit growth from one node token
@pytest.mark.xfail(strict=True, reason="#65 r4 F36: one node token can append audit entries without bound")
def test_finding_audit_log_growth_from_one_node_token(env):
    """Every register call appends a 'register_node' audit entry, even when nothing changed. One node token at the
    rate limit (20/s) adds ~1.7M entries a day: the hash chain, state.db and the startup verify (which replays the
    whole chain) grow without bound. Expected: an unchanged re-register is idempotent (no new entry), or audit
    events per node are rate-limited."""
    c = env.client()
    register(c, "node-a", "site-a")
    before = c.get("/v1/status", headers=H("observer")).json()["recent_audit"][0]["idx"]
    for _ in range(30):
        env.clock.t += 0.1
        register(c, "node-a", "site-a")
    after = c.get("/v1/status", headers=H("observer")).json()["recent_audit"][0]["idx"]
    assert after - before <= 1, after - before


# ================================================================== guards that held live (regression)
def test_live_guards_that_held(env):
    """Live results reproduced: NaN / huge-int / deeply nested / unicode-key / duplicate-key bodies and unicode path
    ids -> 422; node token -> jobs/tamper/other node 403; observer -> lease 403; unknown lease 404."""
    c = env.client()
    register(c, "node-a", "site-a")
    hdr = {**H("node-a"), "Content-Type": "application/json"}
    for body in (b'{"watts": NaN}', b'{"watts": 1' + b"0" * 400 + b"}", b'{"watts":' + b"[" * 3000 + b"]" * 3000 + b"}",
                 '{"wätts": 1}'.encode(), b'{"watts": 1, "watts": -5}'):
        assert c.post("/v1/nodes/node-a/heartbeat", headers=hdr, content=body).status_code == 422
    assert c.post("/v1/nodes/nöde/heartbeat", headers=H("node-a"), json={}).status_code == 422
    assert c.post("/v1/jobs", headers=H("node-a"), json={"job_type": "image_tagging", "customer_id": "x"}).status_code == 403
    assert c.post("/v1/nodes/node-b/heartbeat", headers=H("node-a"), json={}).status_code == 403
    assert c.post("/v1/nodes/node-a/lease", headers=H("observer")).status_code == 403
    assert c.post("/v1/leases/l-0000000000000000/renew", headers=H("node-a")).status_code == 404
