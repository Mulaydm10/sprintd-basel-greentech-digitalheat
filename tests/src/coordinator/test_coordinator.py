"""Coordinator v1 (contracts/src/coordinator.md): TestClient + in-process fake nodes, injected clock.

Fake nodes behave like jobs.runner + live_agent: each unit has N chunks, a chunk's result is a deterministic
hash, checkpoints are encrypted bundles sealed to the job key (key from key_release), and completion sends
sha256 of the ordered chunk results. No network, no real processes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import random

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient

import trust
from coordinator.app import create_app
from coordinator.core import CHUNKS_PER_UNIT, LEASE_S, SUSPECT_S

T0 = 1_764_000_000.0  # 2025-11-24, a winter hour
TOK = {"admin": "A" * 40, "observer": "O" * 40, "node-a": "a" * 40, "node-b": "b" * 40, "node-c": "c" * 40}
ROLES = {TOK["admin"]: "admin", TOK["observer"]: "observer",
         **{TOK[n]: f"node:{n}" for n in ("node-a", "node-b", "node-c")}}


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
    box = {"app": create_app(tmp_path, tokens=ROLES, clock=clock)}

    def client():
        return TestClient(box["app"])

    def restart():
        box["app"] = create_app(tmp_path, tokens=ROLES, clock=clock)

    return type("Env", (), {"clock": clock, "client": staticmethod(client), "restart": staticmethod(restart),
                            "dir": tmp_path})


def attestation(node, measurement="digitalheat-node-image-v1", region="CH-BS"):
    a = trust.attest(node, {"measurement": measurement, "region": region, "certified": False})
    return {"node_id": a.node_id, "evidence": dict(a.evidence), "signature_b64": base64.b64encode(a.signature).decode(),
            "mock": True}


def register(c, node, classes=("public", "swiss-only")):
    r = c.post("/v1/nodes/register", headers=H(node), json={
        "node_id": node, "site_id": f"site-{node[-1]}", "eligible_classes": list(classes), "server_kw_el": 1.0,
        "attestation": attestation(node)})
    assert r.status_code == 200, r.text
    hb(c, node)


def hb(c, node, demand=5.0, tank=5.0):
    r = c.post(f"/v1/nodes/{node}/heartbeat", headers=H(node),
               json={"watts": 30.0, "watts_source": "none", "progress": 0.0, "demand_kw": demand, "tank_level_kwh": tank})
    assert r.status_code == 200, r.text
    return r.json()


def submit(c, job_type="image_tagging", force=True, **kw):
    r = c.post("/v1/jobs", headers=H("admin"), json={"job_type": job_type, "customer_id": "cust-1", "force": force, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def lease(c, node):
    r = c.post(f"/v1/nodes/{node}/lease", headers=H(node))
    assert r.status_code == 200, r.text
    return r.json()


def chunk_result(unit_id, i):
    return hashlib.sha256(f"{unit_id}:{i}".encode()).hexdigest()


def expected_sha(unit_id, n=CHUNKS_PER_UNIT):
    return hashlib.sha256("".join(chunk_result(unit_id, i) for i in range(n)).encode()).hexdigest()


def seal_bundle(key_b64, bundle: dict) -> bytes:
    priv = X25519PrivateKey.from_private_bytes(base64.b64decode(key_b64))
    env = trust.seal(json.dumps(bundle).encode(), priv.public_key(), aad=b"ckpt")
    return json.dumps({k: base64.b64encode(getattr(env, k)).decode()
                       for k in ("ephemeral_pub", "nonce", "ciphertext", "aad")}).encode()


def open_bundle(key_b64, data: bytes) -> dict:
    d = {k: base64.b64decode(v) for k, v in json.loads(data).items()}
    priv = X25519PrivateKey.from_private_bytes(base64.b64decode(key_b64))
    return json.loads(trust.open_(trust.Envelope(d["ephemeral_pub"], d["nonce"], d["ciphertext"], d["aad"]), priv))


def upload(c, node, lease_id, data: bytes, next_chunk: int):
    return c.post(f"/v1/leases/{lease_id}/checkpoint", headers={**H(node), "Content-Type": "application/octet-stream",
                  "X-Next-Chunk": str(next_chunk), "X-Out-Bytes": str(next_chunk * 64),
                  "X-Sha256": hashlib.sha256(data).hexdigest()}, content=data)


def complete(c, node, lease_id, unit_id, sha=None):
    return c.post(f"/v1/leases/{lease_id}/complete", headers=H(node),
                  json={"result_sha256": sha or expected_sha(unit_id), "chunk_ids": list(range(CHUNKS_PER_UNIT))})


# ------------------------------------------------------------------ happy path
def test_happy_path_register_lease_renew_checkpoint_complete(env):
    c = env.client()
    assert c.get("/healthz").json() == {"ok": True, "version": "coordinator-v1"}
    register(c, "node-a")
    job = submit(c)
    assert job["admitted"] and job["units"] == 1 and "job_public_key_b64" in job
    L = lease(c, "node-a")
    u = L["unit"]
    assert L["expires_in_s"] == LEASE_S and L["checkpoint_url"] is None and L["key_release"]["key_b64"]
    assert u["chunks"] == CHUNKS_PER_UNIT and u["job_type"] == "image_tagging"
    assert lease(c, "node-a")["lease_id"] == L["lease_id"]  # re-asking returns the same lease
    env.clock.t += 5
    assert c.post(f"/v1/leases/{L['lease_id']}/renew", headers=H("node-a")).json()["expires_in_s"] == LEASE_S
    data = seal_bundle(L["key_release"]["key_b64"], {"next_chunk": 7})
    assert upload(c, "node-a", L["lease_id"], data, 7).json()["seq"] == 1
    got = c.get(f"/v1/checkpoints/{u['unit_id']}/latest", headers=H("node-a"))
    assert got.content == data and got.headers["x-next-chunk"] == "7"
    assert open_bundle(L["key_release"]["key_b64"], got.content) == {"next_chunk": 7}
    r = complete(c, "node-a", L["lease_id"], u["unit_id"])
    assert r.json() == {"ok": True, "duplicate": False, "unit_id": u["unit_id"]}
    st = c.get("/v1/status", headers=H("observer")).json()
    assert st["queue"] == {"done": 1} and st["leases"] == [] and st["audit_verifies"]
    assert lease(c, "node-a")["hold"] is True


# ------------------------------------------------------------------ node death -> lapse -> reassign -> resume
def test_node_death_lapse_reassign_resume_from_checkpoint(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    submit(c)
    La = lease(c, "node-a")
    if "hold" in La:  # merit may prefer node-b; make node-a the holder deterministically
        La = lease(c, "node-b")
        a, b = "node-b", "node-a"
    else:
        a, b = "node-a", "node-b"
    unit = La["unit"]["unit_id"]
    data = seal_bundle(La["key_release"]["key_b64"], {"next_chunk": 12})
    assert upload(c, a, La["lease_id"], data, 12).status_code == 200
    env.clock.t += LEASE_S + 1  # a dies: no renew
    hb(c, b)
    st = c.get("/v1/status", headers=H("admin")).json()
    assert any(n["node_id"] == a and n["suspect"] for n in st["nodes"])
    Lb = lease(c, b)
    assert Lb["unit"]["unit_id"] == unit and Lb["checkpoint_url"] == f"/v1/checkpoints/{unit}/latest"
    resumed = open_bundle(Lb["key_release"]["key_b64"], c.get(Lb["checkpoint_url"], headers=H(b)).content)
    assert resumed == {"next_chunk": 12}
    assert c.post(f"/v1/leases/{La['lease_id']}/renew", headers=H(a)).status_code == 410
    assert c.get(f"/v1/checkpoints/{unit}/latest", headers=H(a)).status_code == 403  # no longer the holder
    assert complete(c, a, La["lease_id"], unit).status_code == 410  # lapsed lease cannot complete
    assert complete(c, b, Lb["lease_id"], unit).status_code == 200


# ------------------------------------------------------------------ coordinator restart: timers frozen
def test_restart_mid_lease_freezes_timers(env):
    c = env.client()
    register(c, "node-a")
    submit(c)
    L = lease(c, "node-a")
    env.clock.t += 5  # 10 s left
    c.post("/v1/nodes/node-a/heartbeat", headers=H("node-a"), json={})
    env.clock.t += 300  # coordinator down for 5 minutes (crash: no shutdown hook)
    env.restart()
    c = env.client()
    st = c.get("/v1/status", headers=H("observer")).json()
    lz = st["leases"][0]
    assert lz["lease_id"] == L["lease_id"] and 9.0 <= lz["expires_in_s"] <= 10.0
    assert not st["nodes"][0]["suspect"]  # node timers shifted too
    assert c.post(f"/v1/leases/{L['lease_id']}/renew", headers=H("node-a")).status_code == 200
    assert st["audit_verifies"] and any(e["type"] == "coordinator_restart" for e in st["recent_audit"])


def test_lease_lapsed_before_downtime_stays_lapsed(env):
    c = env.client()
    register(c, "node-a")
    submit(c)
    L = lease(c, "node-a")
    env.clock.t += LEASE_S + 2
    c.get("/v1/status", headers=H("observer"))  # coordinator alive past expiry -> lapses
    env.clock.t += 100
    env.restart()
    c = env.client()
    assert c.post(f"/v1/leases/{L['lease_id']}/renew", headers=H("node-a")).status_code == 410


def test_job_keys_and_audit_survive_restart(env):
    c = env.client()
    register(c, "node-a")
    submit(c)
    k1 = lease(c, "node-a")["key_release"]["key_b64"]
    env.restart()
    c = env.client()
    assert lease(c, "node-a")["key_release"]["key_b64"] == k1
    assert c.get("/v1/status", headers=H("admin")).json()["audit_verifies"]


# ------------------------------------------------------------------ auth / limits / validation
def test_auth_401_403(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    assert c.get("/v1/status").status_code == 401
    assert c.get("/v1/status", headers={"Authorization": "Bearer " + "x" * 40}).status_code == 401
    assert c.get("/v1/status", headers=H("node-a")).status_code == 403
    assert c.post("/v1/jobs", headers=H("observer"), json={"job_type": "image_tagging", "customer_id": "c"}).status_code == 403
    assert c.post("/v1/nodes/node-b/heartbeat", headers=H("node-a"), json={}).status_code == 403
    assert c.post("/v1/nodes/node-a/tamper", headers=H("node-a")).status_code == 403
    submit(c)
    L = lease(c, "node-a")
    if "hold" in L:
        L, owner, other = lease(c, "node-b"), "node-b", "node-a"
    else:
        owner, other = "node-a", "node-b"
    assert c.post(f"/v1/leases/{L['lease_id']}/renew", headers=H(other)).status_code == 403
    assert c.post(f"/v1/leases/{L['lease_id']}/renew", headers=H("admin")).status_code == 403
    reg = c.post("/v1/nodes/register", headers=H("node-a"), json={
        "node_id": "node-b", "site_id": "s", "eligible_classes": ["public"], "server_kw_el": 1.0,
        "attestation": attestation("node-b")})
    assert reg.status_code == 403  # a node token cannot register another node


def test_bad_attestation_is_403_and_audited(env):
    c = env.client()
    bad = attestation("node-a", measurement="evil-image")
    r = c.post("/v1/nodes/register", headers=H("node-a"), json={
        "node_id": "node-a", "site_id": "s", "eligible_classes": ["public"], "server_kw_el": 1.0, "attestation": bad})
    assert r.status_code == 403
    forged = attestation("node-a")
    forged["evidence"]["region"] = "CH-ZH"  # signature no longer matches
    r = c.post("/v1/nodes/register", headers=H("node-a"), json={
        "node_id": "node-a", "site_id": "s", "eligible_classes": ["public"], "server_kw_el": 1.0, "attestation": forged})
    assert r.status_code == 403
    st = c.get("/v1/status", headers=H("admin")).json()
    assert sum(e["type"] == "register_denied" for e in st["recent_audit"]) == 2


def test_rate_limit_429(env):
    c = env.client()
    codes = [c.get("/v1/status", headers=H("observer")).status_code for _ in range(45)]
    assert codes[:40] == [200] * 40 and 429 in codes[40:]
    env.clock.t += 1.0  # refill
    assert c.get("/v1/status", headers=H("observer")).status_code == 200
    assert c.get("/v1/status", headers=H("admin")).status_code == 200  # per token


def test_body_limits_413(env):
    c = env.client()
    register(c, "node-a")
    big = b'{"watts": 1, "pad": "' + b"x" * (1 << 20) + b'"}'
    r = c.post("/v1/nodes/node-a/heartbeat", headers={**H("node-a"), "Content-Type": "application/json"}, content=big)
    assert r.status_code == 413
    submit(c)
    L = lease(c, "node-a")
    huge = b"\0" * ((32 << 20) + 1)
    assert upload(c, "node-a", L["lease_id"], huge, 1).status_code == 413
    ok = b"\1" * (2 << 20)  # 2 MB checkpoint is fine
    assert upload(c, "node-a", L["lease_id"], ok, 1).status_code == 200


@pytest.mark.parametrize("body", [
    {"watts": 1, "evil": True},              # extra field
    {"watts": -5},                           # negative
    {"progress": 2},                         # out of range
    {"running_unit": "../../etc"},           # not an id
    {"watts": "NaN"},                        # non-finite
])
def test_validation_422(env, body):
    c = env.client()
    register(c, "node-a")
    assert c.post("/v1/nodes/node-a/heartbeat", headers=H("node-a"), json=body).status_code == 422


def test_checkpoint_sha_mismatch_422(env):
    c = env.client()
    register(c, "node-a")
    submit(c)
    L = lease(c, "node-a")
    r = c.post(f"/v1/leases/{L['lease_id']}/checkpoint", headers={**H("node-a"), "X-Next-Chunk": "1",
               "X-Out-Bytes": "1", "X-Sha256": "0" * 64}, content=b"data")
    assert r.status_code == 422


@pytest.mark.parametrize("path", [
    "/v1/checkpoints/..%2F..%2Fetc%2Fpasswd/latest", "/v1/checkpoints/../../etc/passwd/latest",
    "/v1/checkpoints/UNIT/latest", "/v1/checkpoints/a.b/latest", "/v1/checkpoints/" + "a" * 65 + "/latest",
])
def test_path_traversal_ids_rejected(env, path):
    c = env.client()
    register(c, "node-a")
    assert c.get(path, headers=H("node-a")).status_code in (404, 422)
    r = c.post("/v1/nodes/register", headers=H("node-a"), json={
        "node_id": "../node-a", "site_id": "s", "eligible_classes": ["public"], "server_kw_el": 1.0,
        "attestation": attestation("node-a")})
    assert r.status_code == 422


# ------------------------------------------------------------------ completion semantics
def test_duplicate_and_conflicting_completion(env):
    c = env.client()
    register(c, "node-a")
    submit(c)
    L = lease(c, "node-a")
    unit = L["unit"]["unit_id"]
    assert complete(c, "node-a", L["lease_id"], unit).json()["duplicate"] is False
    assert complete(c, "node-a", L["lease_id"], unit).json()["duplicate"] is True  # counted once
    assert complete(c, "node-a", L["lease_id"], unit, sha="f" * 64).status_code == 409
    st = c.get("/v1/status", headers=H("admin")).json()
    assert st["queue"] == {"done": 1} and any(e["type"] == "complete_conflict" for e in st["recent_audit"])


def test_complete_requires_every_chunk_exactly_once(env):
    c = env.client()
    register(c, "node-a")
    submit(c)
    L = lease(c, "node-a")
    for ids in ([0, 1, 2], list(range(CHUNKS_PER_UNIT - 1)) + [0], list(range(1, CHUNKS_PER_UNIT + 1))):
        r = c.post(f"/v1/leases/{L['lease_id']}/complete", headers=H("node-a"),
                   json={"result_sha256": "a" * 64, "chunk_ids": ids})
        assert r.status_code == 422


# ------------------------------------------------------------------ tamper
def test_tamper_denies_key_and_reassigns(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    submit(c)
    La = lease(c, "node-a")
    holder, other = ("node-a", "node-b") if "unit" in La else ("node-b", "node-a")
    if holder == "node-b":
        La = lease(c, "node-b")
    assert c.post(f"/v1/nodes/{holder}/tamper", headers=H("admin")).json()["revoked"] == 1
    assert c.post(f"/v1/leases/{La['lease_id']}/renew", headers=H(holder)).status_code == 410
    again = lease(c, holder)
    assert again["hold"] and again["reason"] == "key denied: node_tampered"
    hb(c, other)
    Lo = lease(c, other)
    assert Lo["unit"]["unit_id"] == La["unit"]["unit_id"]
    st = c.get("/v1/status", headers=H("admin")).json()
    assert any(n["node_id"] == holder and n["tampered"] for n in st["nodes"])
    env.restart()  # tamper survives restart
    assert lease(env.client(), holder)["hold"]


# ------------------------------------------------------------------ degraded mode
def test_degraded_when_heat_signal_stale_and_no_dump_only_work(env):
    c = env.client()
    register(c, "node-a")
    # summer, full tank: heat has nowhere to go; an urgent unit would run straight into dump
    hb(c, "node-a", demand=0.0, tank=35.0)
    submit(c, deadline_h=0.25)
    fresh = lease(c, "node-a")
    assert fresh.get("degraded") is False
    lease_id = fresh.get("lease_id")
    if lease_id:  # fresh signal: forced deadline work may dump; release it for the degraded check
        complete(c, "node-a", lease_id, fresh["unit"]["unit_id"])
        submit(c, deadline_h=0.25)
    env.clock.t += 10  # heat signal older than 2 ticks
    c.post("/v1/nodes/node-a/heartbeat", headers=H("node-a"), json={"watts": 1.0})  # alive, but no heat data
    st = c.get("/v1/status", headers=H("observer")).json()
    assert st["degraded"] == ["node-a"]
    stale = lease(c, "node-a")
    assert stale["hold"] and stale["degraded"] is True
    assert "degraded" in stale["reason"] or "idle" in stale["reason"] or "no capacity" in stale["reason"]
    assert hb(c, "node-a", demand=5.0, tank=5.0)["degraded"] is False  # fresh data clears it


# ------------------------------------------------------------------ admission at submit
def test_admission_rejects_without_live_nodes_and_admits_with_capacity(env):
    c = env.client()
    r = submit(c, force=False)
    assert r["admitted"] is False and r["reason"] == "no live node" and r["units"] == 0
    register(c, "node-a")
    r = submit(c, force=False)
    assert r["admitted"] is True and r["units"] == 1


# ------------------------------------------------------------------ exactly-once under random kills
class FakeNode:
    def __init__(self, name):
        self.name = name
        self.lease = None
        self.results: list[str] = []
        self.key = None

    def crash(self):
        self.lease, self.results, self.key = None, [], None


@pytest.mark.parametrize("seed", range(6))
def test_property_random_kills_exactly_once(env, seed):
    rng = random.Random(seed)
    c = env.client()
    nodes = [FakeNode(n) for n in ("node-a", "node-b", "node-c")]
    for n in nodes:
        register(c, n.name)
    units = 0
    for jt in ("image_tagging", "whisper_transcription", "image_tagging"):
        units += submit(c, job_type=jt)["units"]
    completions = pauses = 0
    for _step in range(6000):
        env.clock.t += 0.25  # real time passes: keeps every token under its rate limit, lets idle leases lapse
        st = c.get("/v1/status", headers=H("admin")).json()
        if st["queue"].get("done", 0) == units:
            break
        roll = rng.random()
        if roll < 0.03:
            env.restart()  # coordinator crash + restart
            c = env.client()
            continue
        if roll < 0.06:
            env.clock.t += rng.choice([1.0, LEASE_S + 1.0])  # time passes (sometimes past a lease)
        n = rng.choice(nodes)
        if rng.random() < 0.05:
            n.crash()  # node dies: loses everything local
            continue
        warm = rng.random() < 0.3
        hb(c, n.name, demand=0.0 if warm else 5.0, tank=35.0 if warm else 5.0)
        if n.lease is None:
            L = lease(c, n.name)
            if "unit" not in L:
                continue
            n.lease, n.key = L, L["key_release"]["key_b64"]
            n.results = []
            if L["checkpoint_url"]:
                got = c.get(L["checkpoint_url"], headers=H(n.name))
                if got.status_code == 200:
                    n.results = open_bundle(n.key, got.content)["results"]
            continue
        lid, unit = n.lease["lease_id"], n.lease["unit"]["unit_id"]
        rr = c.post(f"/v1/leases/{lid}/renew", headers=H(n.name))
        if rr.status_code == 410:
            n.lease = None  # lapsed: discard local work
            continue
        if rr.json().get("hold"):  # paused on the heat signal: one final checkpoint, then stop
            if n.results and rng.random() < 0.8:
                upload(c, n.name, lid, seal_bundle(n.key, {"results": n.results}), len(n.results))
            n.lease = None
            pauses += 1
            continue
        for _ in range(rng.randint(1, 6)):
            i = len(n.results)
            if i < CHUNKS_PER_UNIT:
                n.results.append(chunk_result(unit, i))
        if rng.random() < 0.5:
            upload(c, n.name, lid, seal_bundle(n.key, {"results": n.results}), len(n.results))
        if len(n.results) == CHUNKS_PER_UNIT:
            sha = hashlib.sha256("".join(n.results).encode()).hexdigest()
            r = c.post(f"/v1/leases/{lid}/complete", headers=H(n.name),
                       json={"result_sha256": sha, "chunk_ids": list(range(CHUNKS_PER_UNIT))})
            assert r.status_code in (200, 410), r.text
            completions += r.status_code == 200
            n.lease = None
    st = c.get("/v1/status", headers=H("admin")).json()
    assert st["queue"].get("done", 0) == units, st["queue"]
    assert st["audit_verifies"]
    import sqlite3
    db = sqlite3.connect(env.dir / "state.db")
    for unit_id, sha, chunks in db.execute("SELECT unit_id, result_sha256, done_chunks FROM units"):
        assert sha == expected_sha(unit_id)  # output equals the uninterrupted run
        assert json.loads(chunks) == list(range(CHUNKS_PER_UNIT))  # every chunk id exactly once
    assert completions >= units



# ------------------------------------------------------------------ pause on the heat signal (#57 review)
def test_running_unit_pauses_when_heat_is_no_longer_wanted_and_migrates(env):
    c = env.client()
    register(c, "node-a")
    submit(c)  # image_tagging: a week of slack, so not deadline-forced
    L = lease(c, "node-a")
    unit, lid = L["unit"]["unit_id"], L["lease_id"]
    assert c.post(f"/v1/leases/{lid}/renew", headers=H("node-a")).json()["ok"] is True  # cold: keeps running
    hb(c, "node-a", demand=0.0, tank=35.0)  # house warm, tank full: heat no longer wanted
    r = c.post(f"/v1/leases/{lid}/renew", headers=H("node-a")).json()
    assert r["hold"] is True and r["final_checkpoint_within_s"] == LEASE_S
    st = c.get("/v1/status", headers=H("admin")).json()
    assert st["queue"] == {"pending": 1} and st["leases"] == []
    data = seal_bundle(L["key_release"]["key_b64"], {"next_chunk": 9})
    assert upload(c, "node-a", lid, data, 9).status_code == 200  # the one final checkpoint
    assert upload(c, "node-a", lid, data, 9).status_code == 410  # released
    assert c.post(f"/v1/leases/{lid}/renew", headers=H("node-a")).status_code == 410
    assert complete(c, "node-a", lid, unit).status_code == 410
    register(c, "node-b")  # a cold house elsewhere picks it up from the final checkpoint
    Lb = lease(c, "node-b")
    assert Lb["unit"]["unit_id"] == unit and Lb["checkpoint_url"]
    assert open_bundle(Lb["key_release"]["key_b64"], c.get(Lb["checkpoint_url"], headers=H("node-b")).content) == {"next_chunk": 9}
    st = c.get("/v1/status", headers=H("admin")).json()
    assert {"lease_paused", "lease_released"} <= {e["type"] for e in st["recent_audit"]}


def test_deadline_forced_unit_keeps_running_when_warm(env):
    c = env.client()
    register(c, "node-a")
    submit(c, deadline_h=0.25)  # due within the hour: forced
    L = lease(c, "node-a")
    hb(c, "node-a", demand=0.0, tank=35.0)
    assert c.post(f"/v1/leases/{L['lease_id']}/renew", headers=H("node-a")).json().get("ok") is True


def test_nan_body_is_422_not_500(env):
    c = env.client()
    register(c, "node-a")
    r = c.post("/v1/nodes/node-a/heartbeat", headers={**H("node-a"), "Content-Type": "application/json"},
               content=b'{"watts": NaN}')
    assert r.status_code == 422 and "NaN" not in r.text and "nan" not in r.text.lower().replace("finite", "")


def test_last_error_reported_in_status(env):
    c = env.client()
    register(c, "node-a")
    assert c.post("/v1/nodes/node-a/heartbeat", headers=H("node-a"),
                  json={"last_error": "key denied: node_tampered"}).status_code == 200
    st = c.get("/v1/status", headers=H("observer")).json()
    assert st["nodes"][0]["last_error"] == "key denied: node_tampered"
    assert c.post("/v1/nodes/node-a/heartbeat", headers=H("node-a"), json={"last_error": "x" * 501}).status_code == 422
