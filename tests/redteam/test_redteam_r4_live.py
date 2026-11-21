"""Red team round 4 (#65, design-redteam): live attack of the deployed coordinator behind Tailscale Funnel.

The attacks below were first run against the LIVE coordinator at
https://dhruvs-mac-mini.tailaf7ebe.ts.net with the real node token `node-rt-mac` and the observer token
(authorised owner red-team). Every attack was then reproduced here against an IN-PROCESS coordinator
(`coordinator.app.create_app` + `TestClient`, no network) so the suite is hermetic and deterministic.

Convention (same as test_redteam_r3.py): a CONFIRMED vulnerability becomes an `xfail(strict=True)` test so a
fix flips it to XPASS and the fixer drops the marker. An attack the code SURVIVES stays as a normal passing
regression guard. Round 4 found NO exploitable defect: every auth, lease-ownership, malformed-input,
checkpoint-integrity and attestation guard held, and the live `/healthz` + observer `audit_verifies` stayed
green throughout. So every test here is a passing regression guard. The one notable behaviour -- a MOCK
attestation can be forged from the public demo signer (source: trust._MOCK_SIGNER) -- is by design and
documented in trust.py ("NOT real trust"); it is pinned as a regression (`test_mock_attestation_is_forgeable_by_design`)
together with the guards that still bite (bad signature / wrong measurement -> 403), not as a finding.
"""
from __future__ import annotations

import base64
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import trust
from coordinator.app import BODY_MAX, create_app
from coordinator.core import CHUNKS_PER_UNIT, LEASE_S

T0 = 1_764_000_000.0  # 2025-11-24, a winter hour (same anchor as test_coordinator.py)
TOK = {"admin": "A" * 40, "observer": "O" * 40, "node-a": "a" * 40, "node-b": "b" * 40}
ROLES = {TOK["admin"]: "admin", TOK["observer"]: "observer",
         TOK["node-a"]: "node:node-a", TOK["node-b"]: "node:node-b"}
# v1.2 operator registry for the test nodes
REGISTRY = {n: {"certified": False, "max_classes": ["public", "swiss-only", "certified"], "region": "CH-BS",
                "site_id": f"site-{n[-1]}"} for n in TOK if n.startswith("node-")}


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

    def make():
        app = create_app(tmp_path, tokens=ROLES, clock=clock, registry=REGISTRY)
        app.state.limiter.clock = clock  # test seam: drive the monotonic limiter with the injected clock
        return app

    app = make()

    def client():
        return TestClient(app)

    return type("Env", (), {"clock": clock, "client": staticmethod(client), "dir": tmp_path})


# ------------------------------------------------------------------ helpers (mirror test_coordinator.py)
def attestation(node, measurement="digitalheat-node-image-v1", region="CH-BS", certified=False):
    a = trust.attest(node, {"measurement": measurement, "region": region, "certified": certified})
    return {"node_id": a.node_id, "evidence": dict(a.evidence),
            "signature_b64": base64.b64encode(a.signature).decode(), "mock": True}


def register(c, node, classes=("public", "swiss-only")):
    r = c.post("/v1/nodes/register", headers=H(node), json={
        "node_id": node, "site_id": f"site-{node[-1]}", "eligible_classes": list(classes),
        "server_kw_el": 1.0, "attestation": attestation(node)})
    assert r.status_code == 200, r.text
    hb(c, node)


def hb(c, node, demand=5.0, tank=5.0):
    r = c.post(f"/v1/nodes/{node}/heartbeat", headers=H(node),
               json={"watts": 30.0, "progress": 0.0, "demand_kw": demand, "tank_level_kwh": tank})
    assert r.status_code == 200, r.text
    return r.json()


def submit(c, job_type="image_tagging", force=True, **kw):
    r = c.post("/v1/jobs", headers=H("admin"),
               json={"job_type": job_type, "customer_id": "cust-1", "force": force, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def lease_held(c, nodes=("node-a", "node-b")):
    """Submit a job and return (holder, other, lease_json). decide() may route to either node."""
    for n in nodes:
        L = c.post(f"/v1/nodes/{n}/lease", headers=H(n)).json()
        if "hold" not in L:
            other = next(x for x in nodes if x != n)
            return n, other, L
    raise AssertionError("no node could lease the submitted unit")


def expected_sha(unit_id, n=CHUNKS_PER_UNIT):
    return hashlib.sha256("".join(hashlib.sha256(f"{unit_id}:{i}".encode()).hexdigest()
                                  for i in range(n)).encode()).hexdigest()


# ================================================================== auth / role escalation
def test_unauthenticated_and_bad_token_rejected(env):
    c = env.client()
    assert c.get("/v1/status").status_code == 401
    assert c.get("/v1/status", headers={"Authorization": "Bearer " + "z" * 40}).status_code == 401
    assert c.get("/v1/status", headers={"Authorization": "Basic x"}).status_code == 401
    assert c.get("/healthz").status_code == 200  # only healthz is open


def test_node_token_cannot_reach_observer_or_admin_endpoints(env):
    c = env.client()
    register(c, "node-a")
    assert c.get("/v1/status", headers=H("node-a")).status_code == 403            # observer-only
    assert c.post("/v1/jobs", headers=H("node-a"),
                  json={"job_type": "image_tagging", "customer_id": "x"}).status_code == 403  # admin-only
    assert c.post("/v1/nodes/node-a/tamper", headers=H("node-a")).status_code == 403          # admin-only


def test_observer_token_cannot_perform_admin_or_node_actions(env):
    c = env.client()
    assert c.post("/v1/jobs", headers=H("observer"),
                  json={"job_type": "image_tagging", "customer_id": "x"}).status_code == 403
    assert c.post("/v1/nodes/node-a/tamper", headers=H("observer")).status_code == 403
    assert c.post("/v1/nodes/node-a/lease", headers=H("observer")).status_code == 403  # not that node


def test_node_cannot_act_for_another_node(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    assert c.post("/v1/nodes/node-b/heartbeat", headers=H("node-a"), json={}).status_code == 403
    assert c.post("/v1/nodes/node-b/lease", headers=H("node-a")).status_code == 403
    r = c.post("/v1/nodes/register", headers=H("node-a"), json={
        "node_id": "node-b", "site_id": "s", "eligible_classes": ["public"], "server_kw_el": 1.0,
        "attestation": attestation("node-b")})
    assert r.status_code == 403  # token may only register its own node id


def test_node_token_cannot_push_site_signal(env):
    """The site-signal endpoint takes an admin or that-site's token, never a node token."""
    c = env.client()
    register(c, "node-a")
    r = c.post("/v1/sites/site-a/signal", headers=H("node-a"),
               json={"demand_kw": 1.0, "tank_level_kwh": 1.0, "ts": T0})
    assert r.status_code == 403


# ================================================================== lease theft / replay / forged completion
def test_cannot_touch_a_lease_owned_by_another_node(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    submit(c)
    holder, other, L = lease_held(c)
    lid, unit = L["lease_id"], L["unit"]["unit_id"]
    # the non-holder tries to steal: renew / complete / checkpoint / read -> 403, never success
    assert c.post(f"/v1/leases/{lid}/renew", headers=H(other)).status_code == 403
    assert c.post(f"/v1/leases/{lid}/complete", headers=H(other),
                  json={"result_sha256": "0" * 64, "chunk_ids": list(range(CHUNKS_PER_UNIT))}).status_code == 403
    up = c.post(f"/v1/leases/{lid}/checkpoint", headers={**H(other), "X-Next-Chunk": "1",
                "X-Out-Bytes": "1", "X-Sha256": hashlib.sha256(b"x").hexdigest()}, content=b"x")
    assert up.status_code == 403
    assert c.get(f"/v1/checkpoints/{unit}/latest", headers=H(other)).status_code == 403
    # the rightful holder still works
    assert c.post(f"/v1/leases/{lid}/renew", headers=H(holder)).status_code == 200


def test_fabricated_or_unknown_lease_is_404(env):
    c = env.client()
    register(c, "node-a")
    assert c.post("/v1/leases/l-deadbeef/renew", headers=H("node-a")).status_code == 404
    assert c.post("/v1/leases/l-deadbeef/complete", headers=H("node-a"),
                  json={"result_sha256": "0" * 64, "chunk_ids": [0]}).status_code in (404, 422)


def test_replay_lease_after_lapse_is_410(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    submit(c)
    holder, _, L = lease_held(c)
    lid = L["lease_id"]
    env.clock.t += LEASE_S + 1  # let the lease lapse (no renew)
    c.get("/v1/status", headers=H("observer"))  # alive past expiry -> lapses the lease
    assert c.post(f"/v1/leases/{lid}/renew", headers=H(holder)).status_code == 410
    assert c.post(f"/v1/leases/{lid}/complete", headers=H(holder),
                  json={"result_sha256": "0" * 64,
                        "chunk_ids": list(range(CHUNKS_PER_UNIT))}).status_code == 410


# ================================================================== conflicting results / completion integrity
def test_completion_must_cover_exactly_all_chunks(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    submit(c)
    holder, _, L = lease_held(c)
    lid, unit = L["lease_id"], L["unit"]["unit_id"]
    # wrong chunk set -> 422
    assert c.post(f"/v1/leases/{lid}/complete", headers=H(holder),
                  json={"result_sha256": "0" * 64, "chunk_ids": [0, 1, 2]}).status_code == 422
    # duplicate chunk ids -> 422
    assert c.post(f"/v1/leases/{lid}/complete", headers=H(holder),
                  json={"result_sha256": "0" * 64,
                        "chunk_ids": [0] * CHUNKS_PER_UNIT}).status_code == 422


def test_conflicting_result_on_completed_unit_is_409(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    submit(c)
    holder, _, L = lease_held(c)
    lid, unit = L["lease_id"], L["unit"]["unit_id"]
    good = expected_sha(unit)
    ok = c.post(f"/v1/leases/{lid}/complete", headers=H(holder),
                json={"result_sha256": good, "chunk_ids": list(range(CHUNKS_PER_UNIT))})
    assert ok.status_code == 200 and ok.json()["duplicate"] is False
    # same result again -> idempotent duplicate
    dup = c.post(f"/v1/leases/{lid}/complete", headers=H(holder),
                 json={"result_sha256": good, "chunk_ids": list(range(CHUNKS_PER_UNIT))})
    assert dup.status_code == 200 and dup.json()["duplicate"] is True
    # a conflicting result for the same (done) unit -> 409, and audited
    conflict = c.post(f"/v1/leases/{lid}/complete", headers=H(holder),
                      json={"result_sha256": "1" * 64, "chunk_ids": list(range(CHUNKS_PER_UNIT))})
    assert conflict.status_code == 409
    assert c.get("/v1/status", headers=H("observer")).json()["audit_verifies"]


# ================================================================== checkpoint poisoning
def test_checkpoint_sha_mismatch_rejected(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    submit(c)
    holder, _, L = lease_held(c)
    lid = L["lease_id"]
    r = c.post(f"/v1/leases/{lid}/checkpoint", headers={**H(holder), "X-Next-Chunk": "1",
               "X-Out-Bytes": "64", "X-Sha256": "0" * 64}, content=b"not-matching-bytes")
    assert r.status_code == 422  # sha256 does not match the uploaded bytes


def test_checkpoint_next_chunk_out_of_range_rejected(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    submit(c)
    holder, _, L = lease_held(c)
    lid = L["lease_id"]
    body = b"payload"
    r = c.post(f"/v1/leases/{lid}/checkpoint", headers={**H(holder), "X-Next-Chunk": str(CHUNKS_PER_UNIT + 5),
               "X-Out-Bytes": "64", "X-Sha256": hashlib.sha256(body).hexdigest()}, content=body)
    assert r.status_code == 422  # next_chunk must be in [0, chunks]


def test_empty_checkpoint_body_rejected(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    submit(c)
    holder, _, L = lease_held(c)
    lid = L["lease_id"]
    r = c.post(f"/v1/leases/{lid}/checkpoint", headers={**H(holder), "X-Next-Chunk": "0",
               "X-Out-Bytes": "0", "X-Sha256": hashlib.sha256(b"").hexdigest()}, content=b"")
    assert r.status_code == 422


# ================================================================== malformed JSON / NaN / huge ints / ids
def test_nan_and_inf_rejected(env):
    c = env.client()
    for bad in (b"NaN", b"Infinity", b"-Infinity"):
        body = (b'{"node_id":"node-a","site_id":"s","eligible_classes":["public"],"server_kw_el":'
                + bad + b',"attestation":{"node_id":"node-a","evidence":{"measurement":"x"},'
                b'"signature_b64":"QUFBQQ=="}}')
        r = c.post("/v1/nodes/register", headers={**H("node-a"), "content-type": "application/json"}, content=body)
        assert r.status_code == 422, (bad, r.status_code)


def test_extra_fields_forbidden(env):
    c = env.client()
    r = c.post("/v1/nodes/register", headers=H("node-a"), json={
        "node_id": "node-a", "site_id": "s", "eligible_classes": ["public"], "server_kw_el": 1.0,
        "attestation": attestation("node-a"), "evil": "x"})
    assert r.status_code == 422


def test_bad_path_ids_rejected(env):
    c = env.client()
    for bad in ("UPPER", "n%C3%A9", "a" * 65, "..%2Fetc"):
        r = c.post(f"/v1/nodes/{bad}/heartbeat", headers=H("node-a"), json={})
        assert r.status_code in (403, 404, 422), (bad, r.status_code)
        assert r.status_code != 500


def test_huge_int_chunk_id_rejected(env):
    c = env.client()
    register(c, "node-a")
    r = c.post("/v1/leases/l-x/complete", headers=H("node-a"),
               json={"result_sha256": "0" * 64, "chunk_ids": [10 ** 30]})
    assert r.status_code == 422


def test_oversize_body_rejected_before_parsing(env):
    c = env.client()
    register(c, "node-a")
    big = b'{"last_error":"' + b"A" * (BODY_MAX + 1000) + b'"}'
    r = c.post("/v1/nodes/node-a/heartbeat",
               headers={**H("node-a"), "content-type": "application/json"}, content=big)
    assert r.status_code == 413


# ================================================================== attestation / certified
def test_mock_attestation_is_forgeable_by_design(env):
    """A08 (fixed in coordinator v1.2): the MOCK attestation can still be forged (its demo signer is derivable
    from a public string), but the forged evidence certified=True no longer makes a node certified. The operator
    registry nodes.json decides: here node-a is registered uncertified, so the claim is audited
    certified_claim_rejected and the certified class is dropped."""
    c = env.client()
    att = trust.attest("node-a", {"measurement": "digitalheat-node-image-v1",
                                  "region": "CH-BL", "certified": True})
    r = c.post("/v1/nodes/register", headers=H("node-a"), json={
        "node_id": "node-a", "site_id": "site-a", "eligible_classes": ["public", "swiss-only", "certified"],
        "server_kw_el": 1.0, "attestation": {
            "node_id": "node-a", "evidence": {"measurement": "digitalheat-node-image-v1",
                                              "region": "CH-BL", "certified": True},
            "signature_b64": base64.b64encode(att.signature).decode(), "mock": True}})
    assert r.status_code == 200
    assert r.json()["certified"] is False and "certified" not in r.json()["eligible_classes"]
    types = [e.event["type"] for e in c.app.state.coord.broker.audit.entries]
    assert "certified_claim_rejected" in types


def test_bad_signature_and_wrong_measurement_still_rejected(env):
    """The guards that DO bite: a wrong/garbage signature and an unexpected measurement -> 403, audited."""
    c = env.client()
    # garbage signature
    bad = {"node_id": "node-a", "site_id": "s", "eligible_classes": ["public"], "server_kw_el": 1.0,
           "attestation": {"node_id": "node-a", "evidence": {"measurement": "digitalheat-node-image-v1",
                           "region": "CH-BL"}, "signature_b64": "QUFBQQ==", "mock": True}}
    assert c.post("/v1/nodes/register", headers=H("node-a"), json=bad).status_code == 403
    # valid signature but measurement not in expected set
    att = trust.attest("node-a", {"measurement": "evil-image", "region": "CH-BL"})
    wrong = {"node_id": "node-a", "site_id": "s", "eligible_classes": ["public"], "server_kw_el": 1.0,
             "attestation": {"node_id": "node-a", "evidence": {"measurement": "evil-image", "region": "CH-BL"},
                             "signature_b64": base64.b64encode(att.signature).decode(), "mock": True}}
    assert c.post("/v1/nodes/register", headers=H("node-a"), json=wrong).status_code == 403
    assert c.get("/v1/status", headers=H("observer")).json()["audit_verifies"]


def test_region_mismatch_denies_key_release(env):
    """A node attested in a non-Swiss region cannot lease a swiss-only unit: release is denied (hold), no key."""
    c = env.client()
    r = c.post("/v1/nodes/register", headers=H("node-a"), json={
        "node_id": "node-a", "site_id": "site-a", "eligible_classes": ["public", "swiss-only"],
        "server_kw_el": 1.0, "attestation": attestation("node-a", region="DE-BW")})
    assert r.status_code == 200
    hb(c, "node-a")
    submit(c, job_type="image_tagging", access_class="swiss-only")
    L = c.post("/v1/nodes/node-a/lease", headers=H("node-a")).json()
    assert L.get("hold") is True and "key_release" not in L


# ================================================================== rate limiting
def test_rate_limit_fires_past_burst(env):
    """Per-token bucket: rate 20/s, burst 40 on a frozen clock -> the 41st+ request is 429, not a crash."""
    c = env.client()
    codes = [c.get("/v1/status", headers=H("observer")).status_code for _ in range(60)]
    assert 429 in codes
    assert codes.count(200) <= 41  # burst bound
    # a different token has its own bucket (no cross-token starvation)
    register(c, "node-a")
    assert c.post("/v1/nodes/node-a/heartbeat", headers=H("node-a"), json={}).status_code in (200, 429)


# ================================================================== no 5xx / audit integrity end to end
def test_audit_chain_verifies_after_attack_sequence(env):
    c = env.client()
    register(c, "node-a")
    register(c, "node-b")
    submit(c)
    holder, other, L = lease_held(c)
    lid = L["lease_id"]
    # a burst of rejected/odd requests must not corrupt the hash-chained audit log
    c.post(f"/v1/leases/{lid}/renew", headers=H(other))                       # 403
    c.post("/v1/leases/l-nope/complete", headers=H(holder),
           json={"result_sha256": "0" * 64, "chunk_ids": [0]})               # 404
    c.post("/v1/nodes/node-a/register", headers=H("node-b"), json={})        # 404/405
    c.post("/v1/jobs", headers=H("node-a"), json={"job_type": "x", "customer_id": "y"})  # 403
    st = c.get("/v1/status", headers=H("admin")).json()
    assert st["audit_verifies"] is True
    assert st["version"] == "coordinator-v1"
