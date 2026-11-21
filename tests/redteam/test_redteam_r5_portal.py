"""Red team round 5 (#86, parth-cloud): the portal API (contract portal v1: P1 #83/#88, P2 #84, P3 #85/#87).

In-process against the real coordinator + portal routers (TestClient). Same convention as earlier rounds:
``test_finding_*`` are findings (xfail strict, listed on #86); everything else is an attack the code survives, kept
as a regression guard. Skipped until the client/host routers (P2) and portal_store (P1) are importable.
"""
from __future__ import annotations

import base64
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("portal.client", reason="needs P2 (#84)")
pytest.importorskip("portal.host", reason="needs P2 (#84)")
portal_store = pytest.importorskip("coordinator.portal_store", reason="needs P1 (#83)")

from coordinator.app import create_app  # noqa: E402
from live_agent import wire  # noqa: E402
from trust import attest  # noqa: E402

TOK = {"t-admin": "admin", "t-obs": "observer", "t-c1": "client:c1", "t-c2": "client:c2", "t-ha": "host:site-a",
       "t-hb": "host:site-b", "t-na": "node:node-a", "t-nb": "node:node-b", "t-sa": "site:site-a",
       "t-sb": "site:site-b"}
REG = {n: {"certified": False, "max_classes": ["public", "swiss-only"], "region": "CH-BS", "site_id": f"site-{n[-1]}"}
       for n in ("node-a", "node-b")}
JOB = {"type": "image_tagging", "access_class": "public", "deadline_h": 24}


class World:
    def __init__(self, tmp: Path, cors: str = "") -> None:
        self.dir = tmp
        self.app = create_app(tmp, tokens=TOK, registry=REG)
        for n, t, s, ts in (("node-a", "t-na", "site-a", "t-sa"), ("node-b", "t-nb", "site-b", "t-sb")):
            ev = {"node_id": n, "region": "CH-BS", "measurement": "digitalheat-node-image-v1", "certified": False}
            assert self.c(t).post("/v1/nodes/register", json={
                "node_id": n, "site_id": s, "eligible_classes": ["public"], "server_kw_el": 1.0,
                "attestation": wire.attestation_to_json(attest(n, ev))}).status_code == 200
            self.c(t).post(f"/v1/nodes/{n}/heartbeat", json={})
            self.c(ts).post(f"/v1/sites/{s}/signal", json={"demand_kw": 6.0, "tank_level_kwh": 5.0, "ts": time.time()})

    def c(self, tok: str | None = None, **headers) -> TestClient:
        h = {**({"Authorization": f"Bearer {tok}"} if tok else {}), **headers}
        return TestClient(self.app, headers=h, raise_server_exceptions=False)

    def submit(self, tok: str, key: str, **kw) -> dict:
        r = self.c(tok).post("/v1/client/jobs", json={**JOB, "idempotency_key": key, **kw})
        assert r.status_code in (200, 201), r.text
        return r.json()


@pytest.fixture
def w(tmp_path, monkeypatch):
    monkeypatch.setenv("DH_CORS_ORIGINS", "https://app.example.ch")
    return World(tmp_path)


# ============================================================ IDOR + cross-role (guards)
def test_client_cannot_see_or_cancel_another_clients_job(w):
    j1 = w.submit("t-c1", "k1")["job_id"]
    c2 = w.c("t-c2")
    for p in ("", "/result", "/receipt"):
        assert c2.get(f"/v1/client/jobs/{j1}{p}").status_code == 404, p  # 404, not 403: ids cannot be probed
    assert c2.delete(f"/v1/client/jobs/{j1}").status_code == 404
    assert w.c("t-c1").get(f"/v1/client/jobs/{j1}").json()["status"] != "cancelled"
    assert all(j["job_id"] != j1 for j in c2.get("/v1/client/jobs").json()["items"])


def test_idempotency_key_is_scoped_per_client(w):
    j1 = w.submit("t-c1", "same-key")["job_id"]
    assert w.submit("t-c2", "same-key")["job_id"] != j1  # never hands out another client's job


def test_host_sees_only_its_site(w):
    hb = w.c("t-hb")
    assert hb.get("/v1/host/nodes/node-a").status_code == 404
    site = hb.get("/v1/host/site").json()
    assert site["site_id"] == "site-b" and all(n.get("node_id") != "node-a" for n in site.get("nodes", []))


@pytest.mark.parametrize("cursor", ["' OR 1=1 --", base64.urlsafe_b64encode(b"' OR 1=1 --").decode(),
                                    base64.urlsafe_b64encode(b"zzzz").decode(), "%00", "a" * 300])
def test_cursor_tampering_never_leaks(w, cursor):
    j1 = w.submit("t-c1", "k1")["job_id"]
    r = w.c("t-c2").get("/v1/client/jobs", params={"cursor": cursor})
    assert r.status_code < 500
    assert r.status_code != 200 or all(j["job_id"] != j1 for j in r.json()["items"])


@pytest.mark.parametrize("tok,method,path", [
    ("t-c1", "get", "/v1/ops/overview"), ("t-c1", "get", "/v1/host/site"), ("t-ha", "get", "/v1/client/me"),
    ("t-na", "get", "/v1/client/jobs"), ("t-c1", "post", "/v1/nodes/node-a/lease"),
    ("t-sa", "post", "/v1/host/site/pause"), ("t-c1", "post", "/v1/ops/nodes/node-a/kill"),
    ("t-ha", "post", "/v1/ops/nodes/node-a/drain"), ("t-obs", "post", "/v1/ops/nodes/node-a/drain"),
    ("t-admin", "get", "/v1/client/me"), ("t-admin", "get", "/v1/host/site"), ("t-obs", "get", "/v1/client/jobs"),
])
def test_cross_role_is_refused(w, tok, method, path):
    assert getattr(w.c(tok), method)(path).status_code in (401, 403, 404)


def test_events_are_scoped(w):
    j1 = w.submit("t-c1", "k1")["job_id"]
    w.submit("t-c2", "k2")
    w.c("t-na").post("/v1/nodes/node-a/lease")
    for tok, banned in (("t-c2", [j1]), ("t-hb", ["site-a", "node-a"])):
        blob = json.dumps(w.c(tok).get("/v1/events/poll").json()["events"])
        assert not any(b in blob for b in banned), tok


# ============================================================ cancel / renew race, idempotency (guards)
def test_cancel_revokes_the_running_lease(w):
    w.submit("t-c1", "k1")
    na = w.c("t-na")
    lz = na.post("/v1/nodes/node-a/lease").json()
    jid, lid = lz["unit"]["job_id"], lz["lease_id"]
    c1 = w.c("t-c1")
    assert c1.delete(f"/v1/client/jobs/{jid}").json()["status"] == "cancelled"
    assert na.post(f"/v1/leases/{lid}/renew").status_code == 410
    done = {"result_sha256": "a" * 64, "chunk_ids": list(range(lz["unit"]["chunks"]))}
    assert na.post(f"/v1/leases/{lid}/complete", json=done).status_code == 410
    again = c1.delete(f"/v1/client/jobs/{jid}")
    assert again.status_code == 200 and again.json()["status"] == "cancelled"  # idempotent
    assert c1.get(f"/v1/client/jobs/{jid}/result").status_code != 200


def test_concurrent_same_key_submits_create_one_job(w):
    out: list = []
    c1 = w.c("t-c1")

    def go():
        out.append(c1.post("/v1/client/jobs", json={**JOB, "idempotency_key": "race"}))
    ts = [threading.Thread(target=go) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len({r.json()["job_id"] for r in out}) == 1
    assert sorted(r.status_code for r in out) == [200] * 11 + [201]


def test_finding_idempotency_key_reused_with_different_body():
    """Stripe-style idempotency: a replay with the SAME key but different parameters is a client bug and must be
    refused (409/422), not answered with the first job as if it matched. Today: 200 {created: false} with the old
    job (public, 24 h) for a request that asked for swiss-only, 48 h; the client believes its new job is running."""
    import tempfile
    w = World(Path(tempfile.mkdtemp()))
    w.submit("t-c1", "k")
    r = w.c("t-c1").post("/v1/client/jobs", json={**JOB, "access_class": "swiss-only", "deadline_h": 48,
                                                  "idempotency_key": "k"})
    assert r.status_code in (409, 422), (r.status_code, r.text)


# ============================================================ node trust boundary
def test_finding_node_can_spoof_progress_of_a_unit_it_does_not_hold(w):
    """node-b heartbeats {running_unit: <node-a's unit of c1's job>, progress: 0.99}. Accepted: c1's event stream gets
    a unit.progress from node-b, /v1/ops/nodes shows node-b running c1's unit, and the event carries node-b's site_id,
    so host-b also learns c1's job id. Expected: running_unit must be a unit this node holds an active lease on
    (else 409/422, or ignored and not emitted)."""
    w.submit("t-c1", "k1")
    lz = w.c("t-na").post("/v1/nodes/node-a/lease").json()
    unit = lz["unit"]["unit_id"]
    w.c("t-nb").post("/v1/nodes/node-b/heartbeat", json={"running_unit": unit, "progress": 0.99})
    spoofed = [e for e in w.c("t-c1").get("/v1/events/poll").json()["events"]
               if e["type"] == "unit.progress" and "node-b" in json.dumps(e)]
    nodes = w.c("t-admin").get("/v1/ops/nodes").json()["items"]
    assert not spoofed, spoofed
    assert all(n.get("running_unit") != unit for n in nodes if n.get("node_id") == "node-b")
    assert lz["unit"]["job_id"] not in json.dumps(w.c("t-hb").get("/v1/events/poll").json()["events"])


# ============================================================ event ring
def test_finding_event_ring_gap_is_silent(w, monkeypatch):
    """unit.progress is emitted on every heartbeat whose progress changes. At the per-token rate limit one node writes
    ~12 events/s (measured in-process), so the 10 000-event ring turns over in ~14 min: a client that resumes with
    Last-Event-ID after that silently loses its own job.state events. (Shrunk here: RING=50.) Expected: either
    progress events are coalesced/throttled per unit (like site.signal), or a resume older than the ring returns
    an explicit gap marker (e.g. a `stream.gap` event / `gap: true`) so the frontend refetches state."""
    monkeypatch.setattr(portal_store, "RING", 50)
    j1 = w.submit("t-c1", "k1")["job_id"]
    c1 = w.c("t-c1")
    mine = c1.get("/v1/events/poll").json()["events"]
    resume_from = mine[0]["id"] - 1 if mine else 0
    na = w.c("t-na")
    lz = na.post("/v1/nodes/node-a/lease").json()
    for i in range(300):  # a chatty (or hostile) node
        r = na.post("/v1/nodes/node-a/heartbeat", json={"running_unit": lz["unit"]["unit_id"], "progress": (i % 97) / 97})
        if r.status_code == 429:
            time.sleep(0.05)
    got = c1.get("/v1/events/poll", params={"after": resume_from}).json()["events"]
    first = got[0]["id"] if got else None
    lost = first is not None and first > resume_from + 1
    signalled = any(e.get("type") == "stream.gap" or e.get("gap") for e in got)
    assert not lost or signalled, f"resumed after {resume_from}, first event {first}, no gap marker ({j1})"


# ============================================================ inputs, CORS, OpenAPI (guards)
@pytest.mark.parametrize("body", [{"deadline_h": 0.24}, {"deadline_h": 720.5}, {"rounds": 10 ** 9}, {"chunks": 10 ** 7},
                                  {"chunks": 0}, {"type": "../x"}, {"access_class": "god"},
                                  {"idempotency_key": "x" * 500}, {"idempotency_key": ""}, {"extra": 1}])
def test_client_job_inputs_are_bounded(w, body):
    r = w.c("t-c1").post("/v1/client/jobs", json={**JOB, "idempotency_key": "in", **body})
    assert r.status_code == 422, r.text


def test_nan_deadline_is_422(w):
    r = w.c("t-c1").post("/v1/client/jobs", content=b'{"type":"image_tagging","access_class":"public",'
                         b'"deadline_h":NaN,"idempotency_key":"n"}', headers={"Content-Type": "application/json"})
    assert r.status_code == 422


@pytest.mark.parametrize("body", [{"until": "garbage"}, {"until": "1970-01-01T00:00:00Z"},
                                  {"until": "9999-12-31T00:00:00Z"}, {"x": 1}])
def test_host_pause_inputs(w, body):
    assert w.c("t-ha").post("/v1/host/site/pause", json=body).status_code == 422


@pytest.mark.parametrize("hours", ["100000", "-1", "0", "abc"])
def test_host_history_bounded(w, hours):
    assert w.c("t-ha").get(f"/v1/host/history?hours={hours}").status_code == 422


def test_ops_unknown_targets_are_404(w):
    a = w.c("t-admin")
    assert a.post("/v1/ops/sites/no-such-site/scenario", json={"replay": "july"}).status_code == 404
    assert a.post("/v1/ops/nodes/no-such-node/kill").status_code == 404
    assert a.post("/v1/ops/nodes/no-such-node/drain").status_code == 404


def test_cors_exact_origin_only(w):
    pre = {"Access-Control-Request-Method": "DELETE", "Access-Control-Request-Headers": "authorization"}
    ok = w.c(None, Origin="https://app.example.ch", **pre).options("/v1/client/jobs/x")
    assert ok.headers.get("access-control-allow-origin") == "https://app.example.ch"
    assert ok.headers.get("access-control-allow-credentials") in (None, "false")
    for origin in ("https://evil.example", "https://app.example.ch.evil.com", "null", "http://app.example.ch"):
        r = w.c(None, Origin=origin, **pre).options("/v1/client/me")
        assert r.headers.get("access-control-allow-origin") is None, origin


def test_openapi_lists_routes_and_leaks_nothing(w):
    spec = w.c().get("/openapi.json")
    assert spec.status_code == 200
    for secret in ("t-admin", str(w.dir), "tokens.json"):
        assert secret not in spec.text
    for p in ("/v1/client/jobs/{job_id}/result", "/v1/host/history", "/v1/ops/overview", "/v1/events/poll"):
        assert p in spec.json()["paths"]


def test_drain_blocks_new_leases_and_kill_revokes(w):
    w.submit("t-c1", "k1")
    a, na = w.c("t-admin"), w.c("t-na")
    assert a.post("/v1/ops/nodes/node-a/drain").json()["drained"] is True
    assert "lease_id" not in na.post("/v1/nodes/node-a/lease").json()  # drained: hold
    a.post("/v1/ops/nodes/node-a/undrain")
    lz = na.post("/v1/nodes/node-a/lease").json()
    assert "lease_id" in lz
    assert a.post("/v1/ops/nodes/node-a/kill").status_code == 200
    assert na.post(f"/v1/leases/{lz['lease_id']}/renew").status_code == 410
    db = sqlite3.connect(w.dir / "state.db")
    assert db.execute("SELECT state FROM units WHERE unit_id=?", (lz["unit"]["unit_id"],)).fetchone()[0] == "pending"
