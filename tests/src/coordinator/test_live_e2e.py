"""#135 live transcription v2 (E2E, coordinator-blind) + v2.1 (signed, hash-linked segments, Merkle receipt).
Real Agents (--backend echo) against an in-process coordinator; the phone's side in Python (live_agent.e2e, interop
with phone-e2e.js verified by design)."""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

import trust
from coordinator import e2e_chain as ec
from coordinator.app import create_app
from live_agent import e2e, wire
from live_agent.agent import Agent, Config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live_agent"))
from test_live_transcribe_agent import relay, wav  # noqa: E402

NODES = ("node-a", "node-b", "node-c")
TOK = {"t-admin": "admin", "t-c1": "client:c1", **{f"t-n{n[-1]}": f"node:{n}" for n in NODES}}
REG = {n: {"certified": False, "max_classes": ["public"], "region": "CH-BS", "site_id": f"site-{n[-1]}"} for n in NODES}
H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731


def setup(tmp_path, nodes=NODES):
    app = create_app(tmp_path / "c", tokens=TOK, registry=REG)
    app.state.limiter.allow = lambda k: True
    tc = TestClient(app)
    agents = {}
    for n in nodes:
        ev = {"node_id": n, "region": "CH-BS", "measurement": "digitalheat-node-image-v1", "certified": False}
        assert tc.post("/v1/nodes/register", headers=H(f"t-n{n[-1]}"), json={
            "node_id": n, "site_id": f"site-{n[-1]}", "eligible_classes": ["public"], "server_kw_el": 1.0,
            "attestation": wire.attestation_to_json(trust.attest(n, ev))}).status_code == 200
        cfg = Config(node_id=n, site_id=f"site-{n[-1]}", backend="echo", root=tmp_path / "agents", renew_s=1.0)
        agents[n] = Agent(cfg, relay(tc, f"t-n{n[-1]}"))
        assert agents[n].heartbeat_once()  # backend + e2e_pub + sig_pub
    return app, tc, agents


class Phone:
    """The phone's side of v2 in Python: per-job key, seal every segment for the current recipients, open results."""

    def __init__(self, tc, key="p"):
        self.tc, self.priv = tc, e2e.new_pair()
        r = tc.post("/v1/client/jobs", headers=H("t-c1"), json={"type": "live_transcription", "access_class": "public",
                                                               "idempotency_key": key, "client_pub": e2e.pub_b64(self.priv)})
        assert r.status_code == 201 and r.json()["e2e"] is True, r.text
        self.job = r.json()["job_id"]

    def recipients(self):
        return {x["node_id"]: x["e2e_pub"] for x in
                self.tc.get(f"/v1/client/jobs/{self.job}/recipients", headers=H("t-c1")).json()["recipients"]}

    def put(self, seq, recips=None):
        blob = e2e.seal_segment(wav(seq), recips or self.recipients())
        r = self.tc.post(f"/v1/client/jobs/{self.job}/segments", headers={**H("t-c1"), "X-Seq": str(seq),
                         "Content-Type": "application/json"}, content=blob.encode())
        assert r.status_code == 201, r.text
        return blob

    def transcript(self):
        return self.tc.get(f"/v1/client/jobs/{self.job}/transcript", headers=H("t-c1")).json()

    def read(self, seg):  # what phone-e2e.js openText does
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        enc = seg["enc"]
        k = e2e._key(self.priv, enc["eph"])
        return AESGCM(k).decrypt(base64.b64decode(enc["iv"]), base64.b64decode(enc["ct"]), None).decode()


def verify_chain(job, segs):  # what phone-e2e.js verifyChain does
    prev = hashlib.sha256(job.encode()).digest()
    for s in segs:
        lk = hashlib.sha256(prev + bytes.fromhex(s["blob_sha256"]) + bytes.fromhex(s["enc_sha256"]) + s["node"].encode()).hexdigest()
        if lk != s["link"]:
            return False
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(base64.b64decode(s["sig_pub"])).verify(
            base64.b64decode(s["sig"]), f"dh-seg-v1|{job}|{s['seq']}|{s['blob_sha256']}|{s['enc_sha256']}".encode())
        prev = bytes.fromhex(lk)
    return True


def _wait(fn, t=10.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_e2e_handover_across_three_nodes_exactly_once_and_coordinator_blind(tmp_path):
    app, tc, ag = setup(tmp_path)
    ph = Phone(tc)
    assert set(ph.recipients()) == set(NODES)
    res, seq = {}, 0
    for n, tok in (("node-a", "t-na"), ("node-b", "t-nb"), ("node-c", "t-nc")):
        lz = tc.post(f"/v1/nodes/{n}/lease", headers=H(tok)).json()
        assert lz.get("unit", {}).get("job_type") == "live_transcription", (n, lz)
        th = threading.Thread(target=lambda n=n, lz=lz: res.__setitem__(n, ag[n].run_live(lz)))
        th.start()
        for _ in range(3):
            ph.put(seq); seq += 1
        assert _wait(lambda: len(ph.transcript()["segments"]) == seq), (n, ph.transcript())
        if n != "node-c":  # STOP this node: the next one is already a recipient
            tc.post(f"/v1/ops/nodes/{n}/drain", headers=H("t-admin")); tc.post(f"/v1/ops/nodes/{n}/kill", headers=H("t-admin"))
            th.join(10)
            assert res[n] == "lapsed"
    tc.post(f"/v1/client/jobs/{ph.job}/end", headers=H("t-c1"))
    th.join(10)
    assert res["node-c"] == "done"
    t = ph.transcript()
    segs = t["segments"]
    assert [s["seq"] for s in segs] == list(range(9))  # exactly once, in order, across 3 nodes
    assert [s["node"] for s in segs] == ["node-a"] * 3 + ["node-b"] * 3 + ["node-c"] * 3
    assert all(s["text"] == "" for s in segs) and t["text"] == ""  # the coordinator serves ciphertext only
    assert [ph.read(s) for s in segs] == [f"seg {i}" for i in range(9)]  # ... which only the phone opens
    assert verify_chain(ph.job, segs) and t["root"]
    # coordinator-blind: no clear transcript and no WAV anywhere in its DB or segment files
    cdir = tmp_path / "c"
    db = sqlite3.connect(cdir / "state.db")
    dump = "\n".join(db.iterdump())
    assert "seg 3" not in dump and "seg 0" not in dump
    for f in (cdir / "segments" / ph.job).iterdir():
        raw = f.read_bytes()
        assert b"RIFF" not in raw and b"WAVE" not in raw and f.suffix == ".e2e"
    # v2.1 receipt: root anchored in the audit chain, every segment provably included
    rc = tc.get(f"/v1/client/jobs/{ph.job}/transcript/receipt", headers=H("t-c1")).json()
    assert rc["root"] == t["root"] and rc["n_segments"] == 9 and rc["nodes"] == list(NODES)
    assert all(ec.verify_proof(p["link"], p["path"], rc["root"]) for p in rc["proofs"])
    audit = tc.get("/v1/ops/audit", headers=H("t-admin"), params={"limit": 50}).json()["items"]
    assert any(e.get("type") == "receipt" and e.get("root") == rc["root"] for e in audit)


def test_a_node_that_is_not_a_recipient_never_gets_or_opens_the_segment(tmp_path):
    app, tc, ag = setup(tmp_path)
    ph = Phone(tc)
    rc = ph.recipients()
    blob = ph.put(0, {"node-b": rc["node-b"]})  # sealed for node-b only
    with __import__("pytest").raises(KeyError):
        e2e.open_segment(ag["node-a"]._e2e_priv, "node-a", blob)
    la = tc.post("/v1/nodes/node-a/lease", headers=H("t-na")).json()
    assert "unit" not in la  # lease_live hands the job only to a recipient of the next segment
    lb = tc.post("/v1/nodes/node-b/lease", headers=H("t-nb")).json()
    assert lb["unit"]["job_type"] == "live_transcription"
    # node-b holds it; a later segment wrapped for node-c only -> node-b reports, the job is released to node-c
    ph.put(1, {"node-c": rc["node-c"]})
    tc.post(f"/v1/client/jobs/{ph.job}/end", headers=H("t-c1"))
    assert ag["node-b"].run_live(lb) == "lapsed"
    assert [s["seq"] for s in ph.transcript()["segments"]] == [0]
    lc = tc.post("/v1/nodes/node-c/lease", headers=H("t-nc")).json()
    assert ag["node-c"].run_live(lc) == "done"
    segs = ph.transcript()["segments"]
    assert [(s["seq"], s["node"]) for s in segs] == [(0, "node-b"), (1, "node-c")] and verify_chain(ph.job, segs)
    audit = tc.get("/v1/ops/audit", headers=H("t-admin"), params={"limit": 50}).json()["items"]
    assert any(e.get("type") == "lease_released" and "not a recipient" in e.get("reason", "") for e in audit)


def test_bad_signature_wrong_enc_and_tampering_are_caught(tmp_path):
    app, tc, ag = setup(tmp_path, ("node-a",))
    ph = Phone(tc)
    ph.put(0)
    lz = tc.post("/v1/nodes/node-a/lease", headers=H("t-na")).json()
    sha = tc.get(f"/v1/leases/{lz['lease_id']}/segments", headers=H("t-na"), params={"wait": 0}).json()["segments"][0]["sha256"]
    enc = e2e.seal_text(e2e.pub_b64(ph.priv), "hello")
    url = f"/v1/leases/{lz['lease_id']}/segments/0/result"
    a = ag["node-a"]
    base = {"text": "", "backend": "echo", "enc": enc}
    assert tc.post(url, headers=H("t-na"), json={**base, "sig": base64.b64encode(b"x" * 64).decode()}).status_code == 422
    assert tc.post(url, headers=H("t-na"), json={**base}).status_code == 422  # unsigned from a node with a sig_pub
    assert tc.post(url, headers=H("t-na"), json={"text": "hello", "backend": "echo",
                   "sig": a._sign_segment(ph.job, 0, sha, None, "hello")}).status_code == 422  # clear text on an E2E job
    good = {**base, "sig": a._sign_segment(ph.job, 0, sha, enc, "")}
    assert tc.post(url, headers=H("t-na"), json=good).status_code == 200
    assert tc.post(url, headers=H("t-na"), json=good).json()["duplicate"] is True
    segs = ph.transcript()["segments"]
    assert ph.read(segs[0]) == "hello" and verify_chain(ph.job, segs)
    forged = [{**segs[0], "enc_sha256": ec.enc_sha256(e2e.seal_text(e2e.pub_b64(ph.priv), "evil"))}]
    assert not verify_chain(ph.job, forged)  # an edited segment breaks its link


def test_input_bounds(tmp_path):
    app, tc, ag = setup(tmp_path, ("node-a",))
    r = tc.post("/v1/client/jobs", headers=H("t-c1"), json={"type": "live_transcription", "access_class": "public",
                                                           "idempotency_key": "bad", "client_pub": "bm90IGEga2V5"})
    assert r.status_code == 422  # the phone falls back to WAV on 422
    ph = Phone(tc)
    put = lambda body: tc.post(f"/v1/client/jobs/{ph.job}/segments", headers={**H("t-c1"), "X-Seq": "0"}, content=body)
    assert put(b"{not json").status_code == 422
    assert put(json.dumps({"v": 2, "iv": "", "ct": "", "wraps": {}}).encode()).status_code == 422
    assert put(json.dumps({"v": 1, "iv": base64.b64encode(b"x" * 12).decode(), "ct": "AA==", "wraps": {}}).encode()).status_code == 422
    assert put(b"{" + b" " * (ec.E2E_MAX + 1)).status_code == 413
    bad_hb = tc.post("/v1/nodes/node-a/heartbeat", headers=H("t-na"), json={"e2e_pub": "AAAA"})
    assert bad_hb.status_code == 422
    assert tc.get("/v1/client/jobs/job-000000000000/recipients", headers=H("t-c1")).status_code == 404


def test_merkle_proofs_for_every_size():
    for n in range(1, 12):
        links = [hashlib.sha256(bytes([i])).hexdigest() for i in range(n)]
        root, proofs = ec.merkle(links)
        assert all(ec.verify_proof(lk, p, root) for lk, p in zip(links, proofs))
        assert not ec.verify_proof(links[0][::-1], proofs[0], root)


def test_final_tail_flush_stays_encrypted_signed_and_linked(tmp_path):
    app, tc, ag = setup(tmp_path, ("node-a",))
    ph = Phone(tc)
    a = ag["node-a"]

    class Tail:  # holds back the last words of every segment (#134), so the flush must carry them
        name = "echo"
        def transcribe(self, wav, context="", seq=0, final=False):
            return {"text": f"seg {seq}", "words": None, "tail": "keep going."}
    a._transcriber = Tail()
    for s in range(2):
        ph.put(s)
    tc.post(f"/v1/client/jobs/{ph.job}/end", headers=H("t-c1"))
    assert a.run_live(tc.post("/v1/nodes/node-a/lease", headers=H("t-na")).json()) == "done"
    t = ph.transcript()
    segs = t["segments"]
    assert [ph.read(s) for s in segs] == ["seg 0", "seg 1 keep going."] and all(s["text"] == "" for s in segs)
    assert verify_chain(ph.job, segs)  # the flushed segment is re-signed and relinked
    rc = tc.get(f"/v1/client/jobs/{ph.job}/transcript/receipt", headers=H("t-c1")).json()
    assert rc["root"] == t["root"] and all(ec.verify_proof(p["link"], p["path"], rc["root"]) for p in rc["proofs"])
    assert "keep going" not in "\n".join(sqlite3.connect(tmp_path / "c" / "state.db").iterdump())


def test_139_a_drained_node_never_gets_a_new_live_lease_and_undrained_gets_it(tmp_path):
    app, tc, ag = setup(tmp_path, ("node-a", "node-b"))
    for n in ("node-a", "node-b"):
        tc.post(f"/v1/ops/nodes/{n}/drain", headers=H("t-admin"))
    ph = Phone(tc)
    assert set(ph.recipients()) == {"node-a", "node-b"}  # standby nodes stay recipients (e8ec2cd)
    ph.put(0)
    for _ in range(3):
        for n, tok in (("node-a", "t-na"), ("node-b", "t-nb")):
            assert "unit" not in tc.post(f"/v1/nodes/{n}/lease", headers=H(tok)).json()
    tc.post("/v1/ops/nodes/node-b/undrain", headers=H("t-admin"))
    assert "unit" not in tc.post("/v1/nodes/node-a/lease", headers=H("t-na")).json()
    assert tc.post("/v1/nodes/node-b/lease", headers=H("t-nb")).json()["unit"]["job_type"] == "live_transcription"


def test_139_the_flushed_last_segment_changes_its_hash_so_the_phone_re_reads_it(tmp_path):
    app, tc, ag = setup(tmp_path, ("node-a",))
    ph = Phone(tc)
    a = ag["node-a"]

    class Tail:
        name = "echo"
        def transcribe(self, wav, context="", seq=0, final=False):
            return {"text": "we keep", "words": None, "tail": "going."}
    a._transcriber = Tail()
    ph.put(0)
    lz = tc.post("/v1/nodes/node-a/lease", headers=H("t-na")).json()
    th = threading.Thread(target=lambda: a.run_live(lz)); th.start()
    assert _wait(lambda: len(ph.transcript()["segments"]) == 1)
    before = ph.transcript()["segments"][0]
    tc.post(f"/v1/client/jobs/{ph.job}/end", headers=H("t-c1"))
    th.join(10)
    after = ph.transcript()["segments"][0]
    assert ph.read(before) == "we keep" and ph.read(after) == "we keep going."
    assert after["seq"] == before["seq"] and after["enc_sha256"] != before["enc_sha256"]  # phone-client.html keys on it
    page = (Path(__file__).resolve().parents[3] / "src/dashboard/static/site/phone-client.html").read_text()
    assert "last.key !== key" in page and "s.enc_sha256 || s.text" in page
