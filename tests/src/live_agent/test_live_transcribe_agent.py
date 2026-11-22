"""#127 node agent: two real Agents (--backend echo) against an in-process coordinator. Stream, STOP A, B resumes:
every seq exactly once, in order; STOP -> first segment accepted on B within 6 s."""
from __future__ import annotations

import io
import struct
import threading
import time
import wave

import httpx
from fastapi.testclient import TestClient

import trust
from coordinator.app import create_app
from live_agent import wire
from live_agent.agent import Agent, Config

TOK = {"t-admin": "admin", "t-c1": "client:c1", "t-na": "node:node-a", "t-nb": "node:node-b"}
REG = {n: {"certified": False, "max_classes": ["public"], "region": "CH-BS", "site_id": f"site-{n[-1]}"} for n in ("node-a", "node-b")}


def wav(seq):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(struct.pack("<h", seq) * 1600)
    return b.getvalue()


def relay(tc, tok):
    def h(req):
        r = tc.request(req.method, req.url.raw_path.decode(), content=req.content,
                       headers={**dict(req.headers), "authorization": f"Bearer {tok}"})
        hd = {k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding", "content-length")}
        return httpx.Response(r.status_code, headers=hd, content=r.content)
    return httpx.Client(base_url="http://coord.test", transport=httpx.MockTransport(h))


def agent(tc, node, tok, tmp):
    cfg = Config(node_id=node, site_id=f"site-{node[-1]}", backend="echo", root=tmp / "agents", renew_s=1.0)
    return Agent(cfg, relay(tc, tok))


def test_echo_agents_stop_and_resume(tmp_path):
    app = create_app(tmp_path / "c", tokens=TOK, registry=REG)
    app.state.limiter.allow = lambda k: True
    tc = TestClient(app)
    H = lambda t: {"Authorization": f"Bearer {t}"}
    for n, t in (("node-a", "t-na"), ("node-b", "t-nb")):
        ev = {"node_id": n, "region": "CH-BS", "measurement": "digitalheat-node-image-v1", "certified": False}
        assert tc.post("/v1/nodes/register", headers=H(t), json={"node_id": n, "site_id": f"site-{n[-1]}",
                       "eligible_classes": ["public"], "server_kw_el": 1.0,
                       "attestation": wire.attestation_to_json(trust.attest(n, ev))}).status_code == 200
    job = tc.post("/v1/client/jobs", headers=H("t-c1"), json={"type": "live_transcription", "access_class": "public",
                                                               "idempotency_key": "live"}).json()["job_id"]
    put = lambda s: tc.post(f"/v1/client/jobs/{job}/segments", headers={**H("t-c1"), "X-Seq": str(s)}, content=wav(s))
    A, B = agent(tc, "node-a", "t-na", tmp_path), agent(tc, "node-b", "t-nb", tmp_path)
    la = tc.post("/v1/nodes/node-a/lease", headers=H("t-na")).json()
    res = {}
    ta = threading.Thread(target=lambda: res.__setitem__("a", A.run_live(la))); ta.start()
    for s in range(12):
        put(s); time.sleep(0.02)
    deadline = time.time() + 10
    while time.time() < deadline and len(tc.get(f"/v1/client/jobs/{job}/transcript", headers=H("t-c1")).json()["segments"]) < 12:
        time.sleep(0.05)
    for s in range(12, 30):
        put(s)
    t_stop = time.time()
    tc.post("/v1/ops/nodes/node-a/drain", headers=H("t-admin")); tc.post("/v1/ops/nodes/node-a/kill", headers=H("t-admin"))
    ta.join(10)
    assert res.get("a") == "lapsed"
    lb = tc.post("/v1/nodes/node-b/lease", headers=H("t-nb")).json()
    tb = threading.Thread(target=lambda: res.__setitem__("b", B.run_live(lb))); tb.start()
    first_b = None
    while time.time() < t_stop + 10 and first_b is None:
        segs = tc.get(f"/v1/client/jobs/{job}/transcript", headers=H("t-c1")).json()["segments"]
        if any(x["node"] == "node-b" for x in segs):
            first_b = time.time()
        time.sleep(0.05)
    assert first_b is not None and first_b - t_stop <= 6.0, first_b and first_b - t_stop
    tc.post(f"/v1/client/jobs/{job}/end", headers=H("t-c1"))
    tb.join(15)
    assert res.get("b") == "done"
    t = tc.get(f"/v1/client/jobs/{job}/transcript", headers=H("t-c1")).json()
    assert [x["seq"] for x in t["segments"]] == list(range(30)) and t["pending"] == 0
    assert t["text"] == " ".join(f"seg {i}" for i in range(30))
    assert {x["backend"] for x in t["segments"]} == {"echo"}
