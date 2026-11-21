"""P2 (#84) over HTTP against the real coordinator: ``create_app`` mounts ``portal.client``/``portal.host`` on the
real ``coordinator.portal_store`` (P1, #88), with real tokens, a real node and real leases.

``test_client_host.py`` covers the full input/role matrix against a fake; this file proves the response models
accept what the real store returns (review on #93: the receipt's ``chunk_ids`` is ``{unit_id: [chunk ids]}``).
Helpers mirror ``tests/src/coordinator/test_portal_store.py`` (kept local so the portal lane stays self-contained).
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient

import trust
from coordinator.app import create_app
from live_agent import wire

T0 = 1_764_000_000.0  # 2025-11-24, a winter hour
TOK = {"admin": "A" * 40, "node-a": "a" * 40, "node-b": "b" * 40,
       "client-x": "x" * 40, "client-y": "y" * 40, "host-a": "h" * 40}
ROLES = {TOK["admin"]: "admin", TOK["node-a"]: "node:node-a", TOK["node-b"]: "node:node-b",
         TOK["client-x"]: "client:cx", TOK["client-y"]: "client:cy", TOK["host-a"]: "host:site-a"}
REGISTRY = {n: {"certified": False, "max_classes": ["public", "swiss-only"], "region": "CH-BS",
                "site_id": f"site-{n[-1]}"} for n in ("node-a", "node-b")}
JOB = {"type": "image_tagging", "access_class": "public", "deadline_h": 48, "idempotency_key": "k1",
       "rounds": 1, "chunks": 4}


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def H(who):
    return {"Authorization": f"Bearer {TOK[who]}"}


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    app = create_app(tmp_path, tokens=ROLES, clock=clock, registry=REGISTRY)
    app.state.limiter.clock = clock
    assert {"client", "host"} <= set(app.state.portal_routers)
    return type("Env", (), {"clock": clock, "app": app, "c": TestClient(app)})()


def att(node):
    a = trust.attest(node, {"measurement": "digitalheat-node-image-v1", "region": "CH-BS", "certified": False})
    return {"node_id": node, "evidence": dict(a.evidence), "signature_b64": base64.b64encode(a.signature).decode(),
            "mock": True}


def up(env, node="node-a"):
    c = env.c
    assert c.post("/v1/nodes/register", headers=H(node), json={
        "node_id": node, "site_id": f"site-{node[-1]}", "eligible_classes": ["public"], "server_kw_el": 1.0,
        "attestation": att(node)}).status_code == 200
    r = c.post(f"/v1/sites/site-{node[-1]}/signal", headers=H("admin"),
               json={"demand_kw": 5.0, "tank_level_kwh": 5.0, "ts": env.clock.t})
    assert r.status_code == 200, r.text
    assert c.post(f"/v1/nodes/{node}/heartbeat", headers=H(node), json={"watts": 30.0}).status_code == 200


def run_unit(env, node="node-a"):
    """Lease, upload the sealed final checkpoint, complete with sha256(output): what live_agent does."""
    r = env.c.post(f"/v1/nodes/{node}/lease", headers=H(node))
    assert r.status_code == 200, r.text
    L = r.json()
    u = L["unit"]
    out = b"".join(f"{i} {hashlib.sha256(f'{u['unit_id']}:{i}'.encode()).hexdigest()}\n".encode()
                   for i in range(u["chunks"]))
    priv = X25519PrivateKey.from_private_bytes(base64.b64decode(L["key_release"]["key_b64"]))
    state = {"next_chunk": u["chunks"], "out_bytes": len(out), "chunks": u["chunks"], "done": True}
    env_b = wire.envelope_to_bytes(trust.seal(wire.bundle_to_bytes(state, out), priv.public_key()))
    env.clock.t += 1
    r = env.c.post(f"/v1/leases/{L['lease_id']}/checkpoint", headers={**H(node), "X-Next-Chunk": str(u["chunks"]),
                   "X-Out-Bytes": str(len(out)), "X-Sha256": hashlib.sha256(env_b).hexdigest()}, content=env_b)
    assert r.status_code == 200, r.text
    r = env.c.post(f"/v1/leases/{L['lease_id']}/complete", headers=H(node),
                   json={"result_sha256": hashlib.sha256(out).hexdigest(), "chunk_ids": list(range(u["chunks"]))})
    assert r.status_code == 200, r.text
    return out


def test_client_full_run_result_and_receipt_over_http(env):
    c = env.c
    up(env)
    r = c.post("/v1/client/jobs", headers=H("client-x"), json=JOB)
    assert r.status_code == 201, r.text
    jid = r.json()["job_id"]
    replay = c.post("/v1/client/jobs", headers=H("client-x"), json=JOB)
    assert replay.status_code == 200 and replay.json()["job_id"] == jid
    for path in ("result", "receipt"):
        assert c.get(f"/v1/client/jobs/{jid}/{path}", headers=H("client-x")).status_code == 409

    units = c.get(f"/v1/client/jobs/{jid}", headers=H("client-x")).json()["units"]
    outs = [run_unit(env) for _ in units]

    d = c.get(f"/v1/client/jobs/{jid}", headers=H("client-x"))
    assert d.status_code == 200 and d.json()["status"] == "done" and d.json()["progress"] == 1.0
    res = c.get(f"/v1/client/jobs/{jid}/result", headers=H("client-x"))
    assert res.status_code == 200 and res.content == b"".join(outs)
    sha = res.headers["x-result-sha256"]
    assert sha == hashlib.sha256(res.content).hexdigest() and res.headers["cache-control"] == "no-store"

    rc = c.get(f"/v1/client/jobs/{jid}/receipt", headers=H("client-x"))
    assert rc.status_code == 200, rc.text  # was a 500 (ResponseValidationError) before the model fix
    rc = rc.json()
    assert rc["result_sha256"] == sha and rc["nodes_used"] == ["node-a"] and rc["audit_head"]
    assert set(rc["chunk_ids"]) == {u["unit_id"] for u in units}
    assert all(v == list(range(JOB["chunks"])) for v in rc["chunk_ids"].values())
    assert rc["kwh"] > 0 and rc["heat_used_kwh"] == pytest.approx(rc["kwh"] * 0.8)

    me = c.get("/v1/client/me", headers=H("client-x")).json()
    assert me["client_id"] == "cx" and me["jobs_total"] == 1
    page = c.get("/v1/client/jobs", headers=H("client-x")).json()
    assert [j["job_id"] for j in page["items"]] == [jid]
    assert c.get("/v1/client/catalogue", headers=H("client-x")).status_code == 200

    for path in ("", "/result", "/receipt"):  # another client: indistinguishable from unknown
        assert c.get(f"/v1/client/jobs/{jid}{path}", headers=H("client-y")).status_code == 404
    assert c.get("/v1/client/jobs", headers=H("client-y")).json()["items"] == []


def test_roles_are_enforced_by_the_real_auth(env):
    c = env.c
    assert c.get("/v1/client/me").status_code == 401
    assert c.get("/v1/host/site").status_code == 401
    assert c.get("/v1/client/me", headers=H("host-a")).status_code == 403
    assert c.get("/v1/host/site", headers=H("client-x")).status_code == 403
    for who in ("admin", "node-a"):
        assert c.get("/v1/client/me", headers=H(who)).status_code == 403
        assert c.get("/v1/host/site", headers=H(who)).status_code == 403


def test_host_site_node_pause_resume_history_over_http(env):
    c = env.c
    up(env)
    up(env, "node-b")  # at site-b: not this host's
    s = c.get("/v1/host/site", headers=H("host-a"))
    assert s.status_code == 200, s.text
    assert s.json()["site_id"] == "site-a" and [n["node_id"] for n in s.json()["nodes"]] == ["node-a"]
    assert c.get("/v1/host/nodes/node-a", headers=H("host-a")).json()["node_id"] == "node-a"
    assert c.get("/v1/host/nodes/node-b", headers=H("host-a")).status_code == 404

    assert c.post("/v1/host/site/pause", headers=H("host-a")).json()["paused"] is True
    assert c.post("/v1/host/site/resume", headers=H("host-a")).json()["paused"] is False
    assert c.post("/v1/host/site/pause", headers=H("host-a"), json={}).json()["paused"] is True

    # `until` is checked against the coordinator's clock (simulated here: 2025-11-24), the same one the store uses
    sim_now = datetime.fromtimestamp(env.clock.t, timezone.utc)
    ok = c.post("/v1/host/site/pause", headers=H("host-a"), json={"until": (sim_now + timedelta(hours=2)).isoformat()})
    assert ok.status_code == 200, ok.text
    assert ok.json()["paused"] is True and ok.json()["paused_until"]
    past = c.post("/v1/host/site/pause", headers=H("host-a"), json={"until": (sim_now - timedelta(hours=1)).isoformat()})
    assert past.status_code == 422
    assert c.post("/v1/host/site/pause", headers=H("host-a"),
                  json={"until": (sim_now + timedelta(days=31)).isoformat()}).status_code == 422

    h = c.get("/v1/host/history?hours=48", headers=H("host-a"))
    assert h.status_code == 200 and isinstance(h.json(), list)
