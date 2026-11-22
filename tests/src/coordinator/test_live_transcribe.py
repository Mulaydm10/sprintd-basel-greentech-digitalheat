"""#127 live transcription, Coordinator section (contracts/src/live_transcribe.md): in-process coordinator, two echo
nodes; stream 30 segments, kill node A at seq 12 -> node B continues; exactly once, in order, complete; auth; events."""
from __future__ import annotations

import base64
import io
import struct
import wave

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient

import trust
from coordinator import portal_store as ps
from coordinator.app import create_app
from coordinator.auth import Principal
from live_agent import wire

TOK = {"t-admin": "admin", "t-c1": "client:c1", "t-c2": "client:c2", "t-na": "node:node-a", "t-nb": "node:node-b"}
REG = {n: {"certified": False, "max_classes": ["public"], "region": "CH-BS", "site_id": f"site-{n[-1]}"} for n in ("node-a", "node-b")}


def wav(seq: int, seconds: float = 0.2) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(struct.pack("<h", seq % 30000) * int(16000 * seconds))
    return b.getvalue()


@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path, tokens=TOK, registry=REG)
    app.state.limiter.allow = lambda k: True
    c = TestClient(app)
    for n, t in (("node-a", "t-na"), ("node-b", "t-nb")):
        ev = {"node_id": n, "region": "CH-BS", "measurement": "digitalheat-node-image-v1", "certified": False}
        assert c.post("/v1/nodes/register", headers=H(t), json={"node_id": n, "site_id": f"site-{n[-1]}",
                      "eligible_classes": ["public"], "server_kw_el": 1.0,
                      "attestation": wire.attestation_to_json(trust.attest(n, ev))}).status_code == 200
        c.post(f"/v1/nodes/{n}/heartbeat", headers=H(t), json={"backend": "echo"})  # transcriber nodes only (6a1144f)
    return type("E", (), {"c": c, "app": app, "coord": app.state.coord})


def H(t):
    return {"Authorization": f"Bearer {t}"}


def start(env, key="k1"):
    r = env.c.post("/v1/client/jobs", headers=H("t-c1"), json={"type": "live_transcription", "access_class": "public",
                                                               "idempotency_key": key})
    assert r.status_code == 201, r.text
    return r.json()["job_id"]


def put(env, job, seq, tok="t-c1"):
    return env.c.post(f"/v1/client/jobs/{job}/segments", headers={**H(tok), "X-Seq": str(seq)}, content=wav(seq))


class EchoNode:
    """Like live_agent with --backend echo: lease, long-poll, decrypt, 'transcribe', post result in order."""
    def __init__(self, env, node, tok):
        self.env, self.node, self.tok, self.lease, self.key, self.done = env, node, tok, None, None, []

    def take(self):
        r = self.env.c.post(f"/v1/nodes/{self.node}/lease", headers=H(self.tok)).json()
        if "lease_id" not in r:
            return False
        self.lease, self.key = r["lease_id"], X25519PrivateKey.from_private_bytes(base64.b64decode(r["key_release"]["key_b64"]))
        return True

    def step(self, after=-1):
        r = self.env.c.get(f"/v1/leases/{self.lease}/segments", headers=H(self.tok), params={"after": after, "wait": 0})
        if r.status_code != 200:
            return r.status_code, []
        out = []
        for s in r.json()["segments"]:
            data = trust.open_(wire.envelope_from_bytes(base64.b64decode(s["envelope_b64"])), self.key)
            assert data[:4] == b"RIFF"
            rr = self.env.c.post(f"/v1/leases/{self.lease}/segments/{s['seq']}/result", headers=H(self.tok),
                                 json={"text": f"seg {s['seq']}", "backend": "echo", "ms": 1.0})
            if rr.status_code == 200:
                out.append(s["seq"])
            else:
                return rr.status_code, out
        self.done += out
        return 200, out


def test_stream_kill_and_resume_exactly_once(env):
    job = start(env)
    a, b = EchoNode(env, "node-a", "t-na"), EchoNode(env, "node-b", "t-nb")
    assert a.take()
    assert not b.take()  # one live unit: only the first asker gets it
    for seq in range(12):
        assert put(env, job, seq).status_code == 201
    while a.step()[1]:
        pass
    assert a.done == list(range(12))
    for seq in range(12, 30):
        assert put(env, job, seq).status_code == 201
    head = ps.events_head(env.coord)
    # STOP node A (drain + kill), exactly like the 10 Coordinator page does
    assert env.c.post("/v1/ops/nodes/node-a/drain", headers=H("t-admin")).status_code == 200
    assert env.c.post("/v1/ops/nodes/node-a/kill", headers=H("t-admin")).status_code == 200
    code, _ = a.step()
    assert code == 410  # node A must stop
    assert b.take()  # node B gets the job at once (resume = one lease call)
    while b.step()[1]:
        pass
    assert b.done == list(range(12, 30))  # continues at the first un-accepted seq: nothing lost, nothing repeated
    assert env.c.post(f"/v1/client/jobs/{job}/end", headers=H("t-c1")).status_code == 200
    t = env.c.get(f"/v1/client/jobs/{job}/transcript", headers=H("t-c1")).json()
    assert [s["seq"] for s in t["segments"]] == list(range(30)) and t["pending"] == 0 and t["ended"]
    assert {s["node"] for s in t["segments"][:12]} == {"node-a"} and {s["node"] for s in t["segments"][12:]} == {"node-b"}
    assert t["text"] == " ".join(f"seg {i}" for i in range(30))
    assert env.c.get(f"/v1/client/jobs/{job}", headers=H("t-c1")).json()["status"] == "done"
    evs = ps.events_after(env.coord, Principal("client", None, "t", client_id="c1"), head, 1000)
    moved = [e for e in evs if e["type"] == "job.moved"]
    assert moved and moved[0]["data"]["from"] == "node-a" and moved[0]["data"]["to"] == "node-b" and moved[0]["data"]["at_seq"] == 12
    assert sum(1 for e in evs if e["type"] == "transcript.segment") == 18


def test_results_exactly_once_and_in_order(env):
    job = start(env)
    a = EchoNode(env, "node-a", "t-na"); assert a.take()
    for seq in range(3):
        put(env, job, seq)
    url = lambda s: f"/v1/leases/{a.lease}/segments/{s}/result"
    assert env.c.post(url(1), headers=H("t-na"), json={"text": "x", "backend": "echo"}).status_code == 409  # out of order
    assert env.c.post(url(0), headers=H("t-na"), json={"text": "seg 0", "backend": "echo"}).status_code == 200
    assert env.c.post(url(0), headers=H("t-na"), json={"text": "seg 0", "backend": "echo"}).json()["duplicate"]
    assert env.c.post(url(0), headers=H("t-na"), json={"text": "other", "backend": "echo"}).status_code == 409
    assert env.c.post(url(9), headers=H("t-na"), json={"text": "x", "backend": "echo"}).status_code == 404


def test_auth_and_input_bounds(env):
    job = start(env)
    assert put(env, job, 0, tok="t-c2").status_code == 404  # another client: not found, not forbidden
    assert env.c.get(f"/v1/client/jobs/{job}/transcript", headers=H("t-c2")).status_code == 404
    assert env.c.post(f"/v1/client/jobs/{job}/segments", headers={**H("t-c1"), "X-Seq": "0"}, content=b"not a wav").status_code == 422
    assert env.c.post(f"/v1/client/jobs/{job}/segments", headers={**H("t-c1"), "X-Seq": "0"}, content=b"RIFF" + b"\0" * 300_000).status_code in (413, 422)
    assert put(env, job, 0).status_code == 201 and put(env, job, 0).status_code == 200  # idempotent
    assert put(env, job, 200).status_code == 422  # gap > 50
    a = EchoNode(env, "node-a", "t-na"); assert a.take()
    assert env.c.get(f"/v1/leases/{a.lease}/segments", headers=H("t-nb"), params={"wait": 0}).status_code == 403
    assert env.c.post("/v1/client/jobs", headers=H("t-c1"), json={"type": "live_transcription", "access_class": "public",
                                                                  "idempotency_key": "k1"}).status_code == 200
    assert env.c.post(f"/v1/client/jobs/{job}/end", headers=H("t-c1")).status_code == 200
    assert put(env, job, 1).status_code == 409  # ended


def test_live_lease_is_not_paused_by_heat(env):
    start(env)
    a = EchoNode(env, "node-a", "t-na"); assert a.take()
    r = env.c.post(f"/v1/leases/{a.lease}/renew", headers=H("t-na")).json()
    assert r.get("ok") and not r.get("hold")  # no site signal at all (no heat data) and still running


def test_local_node_preferred_cloud_only_as_fallback(env):  # #132
    job = start(env)
    hb = lambda node, tok, be: env.c.post(f"/v1/nodes/{node}/heartbeat", headers=H(tok), json={"backend": be})
    hb("node-a", "t-na", "whisper-local"); hb("node-b", "t-nb", "elevenlabs")
    r = env.c.post("/v1/nodes/node-b/lease", headers=H("t-nb")).json()  # the cloud node asks first
    assert r.get("hold") and "local node node-a" in r["reason"]
    la = env.c.post("/v1/nodes/node-a/lease", headers=H("t-na")).json()
    assert la["unit"]["job_type"] == "live_transcription"
    audit = env.c.get("/v1/ops/audit", headers=H("t-admin"), params={"limit": 20}).json()["items"]
    assert any(e.get("type") == "lease" and e.get("reason") == "local node preferred; cloud only as fallback" for e in audit)
    # STOP the local node -> the cloud node takes over immediately (fallback)
    env.c.post("/v1/ops/nodes/node-a/drain", headers=H("t-admin")); env.c.post("/v1/ops/nodes/node-a/kill", headers=H("t-admin"))
    lb = env.c.post("/v1/nodes/node-b/lease", headers=H("t-nb")).json()
    assert lb["unit"]["job_type"] == "live_transcription"
    audit = env.c.get("/v1/ops/audit", headers=H("t-admin"), params={"limit": 20}).json()["items"]
    assert any(e.get("type") == "lease" and e.get("reason") == "cloud fallback: no idle local node" for e in audit)
    assert job


def _nodes(env, a_backend="whisper-local"):
    env.c.post("/v1/nodes/node-a/heartbeat", headers=H("t-na"), json={"backend": a_backend})


def test_132_two_live_jobs_back_to_back_on_the_same_node(env):
    _nodes(env)
    env.c.post("/v1/ops/nodes/node-b/drain", headers=H("t-admin"))
    for key in ("k1", "k2"):
        job = start(env, key)
        a = EchoNode(env, "node-a", "t-na")
        assert a.take(), key
        for s in range(3):
            put(env, job, s)
        while a.step()[1]:
            pass
        assert env.c.post(f"/v1/client/jobs/{job}/end", headers=H("t-c1")).status_code == 200
        assert env.c.get(f"/v1/client/jobs/{job}", headers=H("t-c1")).json()["status"] == "done"
        assert [x["seq"] for x in env.c.get(f"/v1/client/jobs/{job}/transcript", headers=H("t-c1")).json()["segments"]] == [0, 1, 2]


def test_132_drained_node_undrained_mid_job_gets_it_back(env):
    _nodes(env)
    job = start(env)
    a = EchoNode(env, "node-a", "t-na"); assert a.take()
    put(env, job, 0)
    a.step()
    env.c.post("/v1/ops/nodes/node-a/drain", headers=H("t-admin"))
    env.c.post("/v1/ops/nodes/node-b/drain", headers=H("t-admin"))
    assert env.c.post(f"/v1/leases/{a.lease}/renew", headers=H("t-na")).json().get("hold")  # drained: lets go
    env.c.post("/v1/ops/nodes/node-a/undrain", headers=H("t-admin"))
    put(env, job, 1)
    a2 = EchoNode(env, "node-a", "t-na")
    for _ in range(20):  # the paused lease's upload window may still hold the unit for a moment
        if a2.take():
            break
        env.coord.clock = (lambda c=env.coord.clock(): (lambda: c + 20))()
    assert a2.lease and a2.lease != a.lease
    a2.step()
    assert [x["seq"] for x in env.c.get(f"/v1/client/jobs/{job}/transcript", headers=H("t-c1")).json()["segments"]] == [0, 1]


def test_132_orphan_leased_unit_is_repaired_on_the_next_tick(env):
    _nodes(env)
    job = start(env)
    with env.coord._tx() as db:  # the inconsistent state seen live: unit leased, no lease row
        db.execute("UPDATE units SET state='leased' WHERE job_id=?", (job,))
    env.coord.tick()
    assert env.coord.store.one("SELECT state FROM units WHERE job_id=?", job)["state"] == "pending"
    assert EchoNode(env, "node-a", "t-na").take()  # and the job is leasable again
    audit = env.c.get("/v1/ops/audit", headers=H("t-admin"), params={"limit": 20}).json()["items"]
    assert any(e.get("type") == "repair_orphan_unit" for e in audit)


def test_134_final_tail_flush_once_after_end(env):
    job = start(env)
    a = EchoNode(env, "node-a", "t-na"); assert a.take()
    for s in range(2):
        put(env, job, s)
    while a.step()[1]:
        pass
    url = f"/v1/leases/{a.lease}/segments/1/flush"
    assert env.c.post(url, headers=H("t-na"), json={"text": "keep going."}).status_code == 409  # not ended yet
    env.c.post(f"/v1/client/jobs/{job}/end", headers=H("t-c1"))
    assert env.c.post(f"/v1/leases/{a.lease}/segments/0/flush", headers=H("t-na"), json={"text": "x"}).status_code == 409
    assert env.c.post(url, headers=H("t-nb"), json={"text": "x"}).status_code == 403
    assert env.c.post(url, headers=H("t-na"), json={"text": "keep going."}).json()["duplicate"] is False
    assert env.c.post(url, headers=H("t-na"), json={"text": "keep going."}).json()["duplicate"] is True
    assert env.c.post(url, headers=H("t-na"), json={"text": "other"}).status_code == 409
    segs = env.c.get(f"/v1/client/jobs/{job}/transcript", headers=H("t-c1")).json()["segments"]
    assert segs[-1]["text"].endswith("keep going.") and segs[-1]["seq"] == 1
