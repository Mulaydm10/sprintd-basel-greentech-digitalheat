"""Live transcription (#127, contracts/src/live_transcribe.md, Coordinator section).

A live job is ONE latency-bound unit (job_class LIVE) whose work is an ordered stream of segments. Rules that differ
from batch jobs, on purpose:
- it is leased IMMEDIATELY to any eligible node that asks (no heat-merit ordering: a live transcript cannot wait for
  a cold house), and its renewals are never paused by the heat signal;
- the client uploads 4.5 s WAV segments (`X-Seq`), stored sealed to the job key (trust envelope) under the job;
- the lease holder long-polls pending segments and posts one result per seq, exactly once and IN ORDER;
- lease lapse / kill / drain: the unit goes back to pending (existing paths) and the next node resumes at the first
  un-accepted seq: nothing is lost (segments stay pending until accepted) and nothing repeats (accept is per seq);
- `end` + every segment accepted -> the unit is done and the job finishes.
Events: transcript.segment {job, seq, text, node, backend}, job.moved {from, to, at_seq}.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from typing import Any

import trust
from live_agent import wire

from . import e2e_chain as ec
from . import portal_store as ps

LIVE = "live_transcription"
SEG_MAX = 256 * 1024
MAX_GAP = 50
FETCH_LIMIT = 8
TRANSCRIBERS = {"whisper-local", "elevenlabs", "echo"}  # only nodes running one of these may hold a live job
CLOUD_BACKENDS = {"elevenlabs"}  # cloud transcription: eligible, but only as the fallback (#132)
CONTEXT_CHARS = 200


def _core():
    from . import core
    return core


def _err(status: int, detail):
    return _core().CoordError(status, detail)


def live_unit(db, job_id: str):
    return db.execute("SELECT * FROM units WHERE job_id=? AND job_class=?", (job_id, LIVE)).fetchone()


def create_job(coord, client_id: str, idempotency_key: str, access_class: str = "public",
               client_pub: str | None = None) -> dict:
    """POST /v1/client/jobs {type: live_transcription}: idempotent per (client, key). `client_pub` (v2): the phone's
    per-job P-256 key (SPKI b64); nodes then return every transcript segment encrypted to it."""
    if client_pub is not None and not ec.valid_p256(client_pub):
        raise _err(422, "client_pub must be a P-256 public key (SPKI DER, base64)")
    now = coord.clock()
    old = coord.store.one("SELECT * FROM jobs WHERE client_id=? AND idempotency_key=?", client_id, idempotency_key)
    if old is not None:
        if old["job_type"] != LIVE:
            raise _err(409, {"status": "conflict", "reason": "idempotency_key was used for another job type"})
        return {"job_id": old["job_id"], "status": "admitted", "eta": None, "created": False}
    job_id = "job-" + secrets.token_hex(6)
    core = _core()
    with coord._tx() as db:
        coord.broker.register_job(job_id, client_id, access_class)
        priv = core._priv_bytes(coord.broker._jobs[job_id].priv)
        db.execute("""INSERT INTO jobs(job_id, job_type, access_class, customer_id, deadline_hour, priv_key, created_at,
                      admitted, reason, client_id, idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                   (job_id, LIVE, access_class, client_id, 10 ** 6, priv, now, 1, "live: leased immediately", client_id,
                    idempotency_key))
        db.execute("""INSERT INTO units(unit_id, job_id, seq, job_class, access_class, kwh_el, bid, deadline_hour, slack_h,
                      checkpointable, chunks, state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (f"{job_id}-live", job_id, 0, LIVE, access_class, 0.25, 1.0, 10 ** 6, 0.0, 1, 1, "pending"))
        if client_pub:
            db.execute("UPDATE jobs SET client_pub=? WHERE job_id=?", (client_pub, job_id))
        coord._audit(db, {"type": "submit", "job": job_id, "admitted": True, "reason": "live transcription", "units": 1,
                          "e2e": bool(client_pub)})
    return {"job_id": job_id, "status": "admitted", "eta": None, "created": True, "e2e": bool(client_pub)}


def _owned_live(db, client_id: str, job_id: str):
    j = db.execute("SELECT * FROM jobs WHERE job_id=? AND client_id=?", (job_id, client_id)).fetchone()
    if j is None or j["job_type"] != LIVE:
        return None
    return j


def add_segment(coord, client_id: str, job_id: str, seq: int, body: bytes) -> dict | None:
    """Client upload. None = unknown/foreign job (404). Idempotent per (job, seq)."""
    if not isinstance(seq, int) or seq < 0:
        raise _err(422, "X-Seq must be an integer >= 0")
    e2e, recips = ec.is_e2e(body), None
    if e2e:  # v2: {v, iv, ct, wraps}; stored as is, the coordinator holds no key that opens it
        if len(body) > ec.E2E_MAX:
            raise _err(413, f"segment larger than {ec.E2E_MAX} bytes")
        try:
            recips = ec.check_blob(body)
        except ValueError as e:
            raise _err(422, str(e)) from e
    elif len(body) > SEG_MAX:
        raise _err(413, f"segment larger than {SEG_MAX} bytes")
    elif len(body) < 44 or body[:4] != b"RIFF" or body[8:12] != b"WAVE":
        raise _err(422, "segment must be a WAV file or an E2E JSON blob")
    sha = hashlib.sha256(body).hexdigest()
    now = coord.clock()
    with coord._tx() as db:
        j = _owned_live(db, client_id, job_id)
        if j is None:
            return None
        if j["ended_at"] is not None:
            raise _err(409, "job ended: no more segments")
        old = db.execute("SELECT sha256 FROM segments WHERE job_id=? AND seq=?", (job_id, seq)).fetchone()
        if old is not None:
            if old["sha256"] != sha:
                raise _err(409, "a different segment was already uploaded for this seq")
            return {"ok": True, "seq": seq, "duplicate": True}
        top = db.execute("SELECT MAX(seq) FROM segments WHERE job_id=?", (job_id,)).fetchone()[0]
        if seq > (-1 if top is None else top) + 1 + MAX_GAP:
            raise _err(422, f"seq gap larger than {MAX_GAP}")
        if e2e:
            env, ext = body, "e2e"
        else:  # legacy v1: sealed to the job key (released to the lease holder)
            env, ext = wire.envelope_to_bytes(trust.seal(body, coord.broker._jobs[job_id].priv.public_key())), "env"
        d = coord.dir / "segments" / job_id
        d.mkdir(parents=True, exist_ok=True)
        f, tmp = d / f"{seq}.{ext}", d / f".{seq}.tmp"
        tmp.write_bytes(env)
        os.replace(tmp, f)
        db.execute("""INSERT INTO segments(job_id, seq, path, sha256, size, received_at, state, recipients)
                      VALUES(?,?,?,?,?,?,'pending',?)""", (job_id, seq, str(f.relative_to(coord.dir)), sha, len(body), now,
                                                          json.dumps(recips) if recips is not None else None))
    return {"ok": True, "seq": seq, "duplicate": False}


def end_job(coord, client_id: str, job_id: str) -> dict | None:
    now = coord.clock()
    with coord._tx() as db:
        j = _owned_live(db, client_id, job_id)
        if j is None:
            return None
        if j["ended_at"] is None:
            db.execute("UPDATE jobs SET ended_at=? WHERE job_id=?", (now, job_id))
            _maybe_finish(db, coord, job_id)
    return {"ok": True, "job_id": job_id}


def transcript(coord, client_id: str, job_id: str) -> dict | None:
    with coord.store.lock:
        db = coord.store.db
        j = _owned_live(db, client_id, job_id)
        if j is None:
            return None
        rows = db.execute("""SELECT * FROM segments WHERE job_id=? ORDER BY seq""", (job_id,)).fetchall()
    segs = [_seg_out(r) for r in rows if r["state"] == "accepted"]
    return {"job_id": job_id, "segments": segs, "pending": sum(1 for r in rows if r["state"] != "accepted"),
            "ended": j["ended_at"] is not None, "e2e": bool(j["client_pub"]), "root": j["root"],
            "text": " ".join((s["text"] or "").strip() for s in segs if (s["text"] or "").strip())}


def _seg_out(r) -> dict:
    """One transcript segment: clear `text` (legacy) or `enc` (v2, only the phone can open it) + the v2.1 proof."""
    return {"seq": r["seq"], "text": r["text"] or "", "node": r["node"], "backend": r["backend"],
            "enc": json.loads(r["enc"]) if r["enc"] else None, "blob_sha256": r["sha256"],
            "enc_sha256": r["enc_sha256"], "link": r["link"], "sig": r["sig"], "sig_pub": r["sig_pub"]}


def recipients(coord, client_id: str, job_id: str) -> dict | None:
    """GET /v1/client/jobs/{id}/recipients (v2): the nodes a segment must be wrapped for = online, undrained,
    untampered transcriber nodes eligible for the job's class that published an `e2e_pub`."""
    now = coord.clock()
    with coord.store.lock:
        db = coord.store.db
        j = _owned_live(db, client_id, job_id)
        if j is None:
            return None
        rows = db.execute("""SELECT node_id, e2e_pub, backend, eligible_classes FROM nodes WHERE tampered=0 AND drained=0
                             AND last_hb >= ? AND e2e_pub IS NOT NULL ORDER BY node_id""",
                          (now - _core().SUSPECT_S,)).fetchall()
    return {"recipients": [{"node_id": r["node_id"], "e2e_pub": r["e2e_pub"], "backend": r["backend"]} for r in rows
                           if (r["backend"] or "") in TRANSCRIBERS and j["access_class"] in json.loads(r["eligible_classes"])]}


def receipt(coord, client_id: str, job_id: str) -> dict | None:
    """GET /v1/client/jobs/{id}/receipt (v2.1): Merkle root over the segment links + inclusion proofs + where the
    root sits in the hash-chained audit log."""
    with coord.store.lock:
        db = coord.store.db
        j = _owned_live(db, client_id, job_id)
        if j is None:
            return None
        rows = db.execute("SELECT seq, link, node FROM segments WHERE job_id=? AND state='accepted' ORDER BY seq",
                          (job_id,)).fetchall()
        a = db.execute("""SELECT idx, hash FROM audit WHERE event LIKE ? ORDER BY idx DESC LIMIT 1""",
                       (f'%"job": "{job_id}"%"type": "receipt"%',)).fetchone()
        head = db.execute("SELECT idx, hash FROM audit ORDER BY idx DESC LIMIT 1").fetchone()
    if j["root"] is None:
        raise _err(409, "no receipt yet: the stream has not finished")
    root, proofs = ec.merkle([r["link"] for r in rows])
    return {"job_id": job_id, "root": root, "n_segments": len(rows), "nodes": sorted({r["node"] for r in rows}),
            "audit_entry": {"idx": a["idx"], "hash": a["hash"]} if a else None,
            "audit_head": {"idx": head["idx"], "hash": head["hash"]} if head else None,
            "proofs": [{"seq": r["seq"], "link": r["link"], "path": p} for r, p in zip(rows, proofs)]}


# ------------------------------------------------------------------ node side (called from core.lease / app)


def lease_live(db, coord, me, now: float) -> dict | None:
    """In core.lease: a pending live unit goes to the first eligible node that asks (latency-bound)."""
    classes = set(json.loads(me["eligible_classes"]))
    u = db.execute("""SELECT * FROM units WHERE job_class=? AND state='pending' ORDER BY rowid LIMIT 1""", (LIVE,)).fetchone()
    if u is None or u["access_class"] not in classes or (me["backend"] or "") not in TRANSCRIBERS:
        return None  # batch nodes (cpu-hash, ...) never take a live job: it would only lapse there (found live)
    if not _can_open(db, u["job_id"], me["node_id"]):
        return None  # v2: the next segment is not wrapped for this node; a recipient takes the job
    core = _core()
    node_id = me["node_id"]
    if (me["backend"] or "") in CLOUD_BACKENDS:
        # local, heat-producing compute first: hold the cloud node while an eligible LOCAL node is idle and healthy
        for n in db.execute("""SELECT * FROM nodes WHERE node_id<>? AND tampered=0 AND drained=0 AND last_hb >= ?""",
                            (node_id, now - core.SUSPECT_S)).fetchall():
            if (n["backend"] or "") not in TRANSCRIBERS or (n["backend"] or "") in CLOUD_BACKENDS or u["access_class"] not in set(json.loads(n["eligible_classes"])):
                continue
            if n["backend"] and _can_open(db, u["job_id"], n["node_id"]) and \
                    db.execute("SELECT 1 FROM leases WHERE node_id=? AND state='active'", (n["node_id"],)).fetchone() is None:
                return {"hold": True, "reason": f"live job reserved for local node {n['node_id']}; cloud only as fallback",
                        "retry_after_s": 2.0}
    reason = "cloud fallback: no idle local node" if (me["backend"] or "") in CLOUD_BACKENDS else \
        "local node preferred; cloud only as fallback"
    rel = coord._release(u["job_id"], node_id, coord._attestation(me), me["region"])
    coord._persist_audit(db)
    if isinstance(rel, trust.Denied):
        return None
    prev = db.execute("SELECT node_id FROM leases WHERE unit_id=? ORDER BY issued_at DESC LIMIT 1", (u["unit_id"],)).fetchone()
    lease_id = "l-" + secrets.token_hex(8)
    db.execute("INSERT INTO leases VALUES(?,?,?,?,?,?)", (lease_id, u["unit_id"], node_id, "active", now, now + core.LEASE_S))
    db.execute("UPDATE units SET state='leased' WHERE unit_id=?", (u["unit_id"],))
    coord._audit(db, {"type": "lease", "lease": lease_id, "unit": u["unit_id"], "node": node_id, "degraded": False,
                      "reason": reason, "backend": me["backend"]})
    if prev is not None and prev["node_id"] != node_id:
        nxt = _next_seq(db, u["job_id"])
        ps.emit(db, coord, "job.moved", {"job": u["job_id"], "from": prev["node_id"], "to": node_id, "at_seq": nxt},
                **ps.scope(db, u["unit_id"], node_id))
    cur = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
    return coord._lease_payload(db, cur, now, False, key=rel)


def _can_open(db, job_id: str, node_id: str) -> bool:
    """v2: can this node read the next segment to transcribe? (legacy WAV segments: any lease holder can)."""
    r = db.execute("""SELECT recipients FROM segments WHERE job_id=? AND state!='accepted' ORDER BY seq LIMIT 1""",
                   (job_id,)).fetchone()
    return r is None or r["recipients"] is None or node_id in json.loads(r["recipients"])


def _next_seq(db, job_id: str) -> int:
    r = db.execute("SELECT MIN(seq) FROM segments WHERE job_id=? AND state!='accepted'", (job_id,)).fetchone()[0]
    if r is not None:
        return int(r)
    top = db.execute("SELECT MAX(seq) FROM segments WHERE job_id=?", (job_id,)).fetchone()[0]
    return 0 if top is None else int(top) + 1


def _held(db, node_id: str, lease_id: str):
    lz = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
    if lz is None:
        raise _err(404, "unknown lease")
    if lz["node_id"] != node_id:
        raise _err(403, "lease belongs to another node")
    if lz["state"] != "active":
        raise _err(410, f"lease {lz['state']}: stop, another node continues")
    u = db.execute("SELECT * FROM units WHERE unit_id=?", (lz["unit_id"],)).fetchone()
    if u is None or u["job_class"] != LIVE:
        raise _err(422, "not a live transcription lease")
    return lz, u


def fetch(coord, node_id: str, lease_id: str, after: int) -> dict:
    """Pending segments with seq > after (sealed to the job key), the next seq to accept, and the context."""
    with coord._tx() as db:
        coord._expire(db, coord.clock())
        lz0 = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
        if lz0 is not None and lz0["node_id"] == node_id and lz0["state"] == "completed":  # the job finished on this node
            j0 = db.execute("SELECT job_id FROM units WHERE unit_id=?", (lz0["unit_id"],)).fetchone()["job_id"]
            return {"job_id": j0, "segments": [], "next_seq": _next_seq(db, j0), "ended": True, "done": True, "context": ""}
        lz, u = _held(db, node_id, lease_id)
        job = u["job_id"]
        rows = db.execute("""SELECT seq, path, sha256 FROM segments WHERE job_id=? AND state='pending' AND seq>?
                             ORDER BY seq LIMIT ?""", (job, int(after), FETCH_LIMIT)).fetchall()
        acc = db.execute("""SELECT text FROM segments WHERE job_id=? AND state='accepted' ORDER BY seq DESC LIMIT 12""",
                         (job,)).fetchall()
        jr = db.execute("SELECT ended_at, client_pub FROM jobs WHERE job_id=?", (job,)).fetchone()
        ended = jr["ended_at"] is not None
        nxt = _next_seq(db, job)
    # E2E jobs: the coordinator has no clear text, so no context (the node stitches with its own accepted text)
    ctx = " ".join(r["text"].strip() for r in reversed(acc) if r["text"])[-CONTEXT_CHARS:]
    segs = []
    for r in rows:
        raw = (coord.dir / r["path"]).read_bytes()
        if r["path"].endswith(".e2e"):
            segs.append({"seq": r["seq"], "sha256": r["sha256"], "blob_b64": base64.b64encode(raw).decode()})
        else:
            segs.append({"seq": r["seq"], "sha256": r["sha256"], "envelope_b64": base64.b64encode(raw).decode()})
    return {"job_id": job, "segments": segs, "next_seq": nxt, "ended": ended, "done": False, "context": ctx,
            "client_pub": jr["client_pub"]}


def not_recipient(coord, node_id: str, lease_id: str, seq: int) -> dict:
    """v2: the lease holder cannot open segment `seq` (no wrap for it): verified, then the lease is released at once
    and the job goes to a node that is a recipient (lease_live only hands it to one)."""
    with coord._tx() as db:
        lz, u = _held(db, node_id, lease_id)
        r = db.execute("SELECT recipients FROM segments WHERE job_id=? AND seq=?", (u["job_id"], seq)).fetchone()
        if r is None:
            raise _err(404, "no such segment")
        if r["recipients"] is None or node_id in json.loads(r["recipients"]):
            raise _err(409, "this node is a recipient of that segment")
        db.execute("UPDATE leases SET state='lapsed' WHERE lease_id=?", (lease_id,))
        db.execute("UPDATE units SET state='pending' WHERE unit_id=? AND state='leased'", (u["unit_id"],))
        coord._audit(db, {"type": "lease_released", "lease": lease_id, "unit": u["unit_id"], "node": node_id,
                          "reason": f"not a recipient of segment {seq}"})
    return {"ok": True, "released": True}


def accept(coord, node_id: str, lease_id: str, seq: int, text: str, words, backend: str, ms: float,
           enc: dict | None = None, sig: str | None = None) -> dict:
    """Exactly once per seq, in order: dup = 200 no-op, conflicting text = 409, out of order = 409.
    v2: an E2E job (client_pub) takes `enc` (sealed to the phone) and an empty `text`. v2.1: a node that published a
    `sig_pub` must sign m(job, seq, blob_sha256, enc_sha256); bad signature = 422. Every accepted segment is linked."""
    if enc is not None:
        try:
            ec.check_enc(enc)
        except ValueError as e:
            raise _err(422, str(e)) from e
    canon = ec.canon_enc(enc) if enc is not None else None
    now = coord.clock()
    with coord._tx() as db:
        coord._expire(db, now)
        row = None
        lz = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
        if lz is not None:
            u0 = db.execute("SELECT job_id FROM units WHERE unit_id=?", (lz["unit_id"],)).fetchone()
            row = db.execute("SELECT * FROM segments WHERE job_id=? AND seq=?", (u0["job_id"], seq)).fetchone() if u0 else None
        if row is not None and row["state"] == "accepted":  # idempotent even after the lease moved on
            if (row["text"] or "") == (text or "") and row["enc"] == canon:
                return {"ok": True, "duplicate": True, "seq": seq}
            raise _err(409, "conflicting text for an already accepted segment")
        lz, u = _held(db, node_id, lease_id)
        job = u["job_id"]
        if row is None:
            raise _err(404, "no such segment")
        nxt = _next_seq(db, job)
        if seq != nxt:
            raise _err(409, f"out of order: the next segment to accept is {nxt}")
        jr = db.execute("SELECT client_pub FROM jobs WHERE job_id=?", (job,)).fetchone()
        if jr["client_pub"]:
            if enc is None or (text or "").strip() or words:
                raise _err(422, "E2E job: send the transcript only as `enc` (text empty, no words)")
        elif enc is not None:
            raise _err(422, "enc is only for E2E jobs (created with client_pub)")
        es = ec.enc_sha256(enc, text or "")
        me = db.execute("SELECT sig_pub FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        sig_pub = me["sig_pub"] if me else None
        if sig_pub:
            if not sig or not ec.verify_sig(sig_pub, sig, ec.seg_message(job, seq, row["sha256"], es)):
                raise _err(422, "bad or missing segment signature")
        prev = db.execute("""SELECT link FROM segments WHERE job_id=? AND state='accepted' AND seq<? ORDER BY seq DESC
                             LIMIT 1""", (job, seq)).fetchone()
        lk = ec.link(prev["link"] if prev else None, job, row["sha256"], es, node_id)
        db.execute("""UPDATE segments SET state='accepted', text=?, words=?, node=?, backend=?, ms=?, accepted_at=?,
                      enc=?, enc_sha256=?, sig=?, sig_pub=?, link=? WHERE job_id=? AND seq=?""",
                   (text, json.dumps(words) if words is not None else None, node_id, backend, ms, now, canon, es,
                    sig if sig_pub else None, sig_pub, lk, job, seq))
        db.execute("UPDATE leases SET expires_at=? WHERE lease_id=?", (now + _core().LEASE_S, lease_id))  # progress = alive
        ps.emit(db, coord, "transcript.segment", {"job": job, "seq": seq, "text": text, "node": node_id, "backend": backend,
                                                  "enc": enc, "link": lk},
                **ps.scope(db, u["unit_id"], node_id))
        _maybe_finish(db, coord, job)
    return {"ok": True, "duplicate": False, "seq": seq}


def _maybe_finish(db, coord, job_id: str) -> None:
    j = db.execute("SELECT ended_at FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    pend = db.execute("SELECT COUNT(*) FROM segments WHERE job_id=? AND state!='accepted'", (job_id,)).fetchone()[0]
    if j is None or j["ended_at"] is None or pend:
        return
    u = live_unit(db, job_id)
    if u is None or u["state"] == "done":
        return
    now = coord.clock()
    lz = db.execute("SELECT * FROM leases WHERE unit_id=? AND state='active'", (u["unit_id"],)).fetchone()
    db.execute("""UPDATE units SET state='done', result_sha256=?, done_chunks='[0]', completed_at=?, completed_by=?
                  WHERE unit_id=?""", (hashlib.sha256(job_id.encode()).hexdigest(), now, lz["node_id"] if lz else None,
                                       u["unit_id"]))
    if lz is not None:
        db.execute("UPDATE leases SET state='completed' WHERE lease_id=?", (lz["lease_id"],))
    coord._audit(db, {"type": "complete", "unit": u["unit_id"], "node": lz["node_id"] if lz else None, "result": "live"})
    _receipt(db, coord, job_id)


def _receipt(db, coord, job_id: str, flush: bool = False) -> None:
    """v2.1: Merkle root over the segment links, anchored in the hash-chained audit log (again after a flush)."""
    rows = db.execute("SELECT link, node FROM segments WHERE job_id=? AND state='accepted' ORDER BY seq",
                      (job_id,)).fetchall()
    root, _ = ec.merkle([r["link"] for r in rows if r["link"]])
    if root is not None:
        db.execute("UPDATE jobs SET root=? WHERE job_id=?", (root, job_id))
        coord._audit(db, {"type": "receipt", "job": job_id, "root": root, "n_segments": len(rows),
                          "nodes": sorted({r["node"] for r in rows}), **({"flush": True} if flush else {})})


def flush(coord, node_id: str, lease_id: str, seq: int, text: str, enc: dict | None = None,
          sig: str | None = None) -> dict:
    """#134: after /end, the node that accepted the LAST segment appends that segment's held-back tail once (the
    words a next segment would have confirmed). Lease must be this node's (active or just completed); idempotent.
    v2: an E2E job sends the WHOLE last segment re-sealed to the phone as `enc` (text empty). v2.1: the node re-signs
    the new segment; its link and the job's Merkle root are recomputed (it is the last segment: no later link)."""
    text = (text or "").strip()[:500]
    if enc is not None:
        try:
            ec.check_enc(enc)
        except ValueError as e:
            raise _err(422, str(e)) from e
    with coord._tx() as db:
        lz = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
        if lz is None:
            raise _err(404, "unknown lease")
        if lz["node_id"] != node_id:
            raise _err(403, "lease belongs to another node")
        if lz["state"] not in ("active", "completed"):
            raise _err(410, f"lease {lz['state']}")
        job = db.execute("SELECT job_id FROM units WHERE unit_id=?", (lz["unit_id"],)).fetchone()["job_id"]
        jr = db.execute("SELECT ended_at, client_pub FROM jobs WHERE job_id=?", (job,)).fetchone()
        if jr["ended_at"] is None:
            raise _err(409, "the stream has not ended")
        last = db.execute("SELECT * FROM segments WHERE job_id=? ORDER BY seq DESC LIMIT 1", (job,)).fetchone()
        if last is None or last["seq"] != seq or last["state"] != "accepted" or last["node"] != node_id:
            raise _err(409, "only the last segment, accepted by this node, can be flushed")
        if jr["client_pub"]:
            if enc is None or text:
                raise _err(422, "E2E job: flush the whole segment re-sealed as `enc` (text empty)")
            marker, new_text, canon = ec.enc_sha256(enc), "", ec.canon_enc(enc)
        elif enc is not None:
            raise _err(422, "enc is only for E2E jobs (created with client_pub)")
        else:
            marker, new_text, canon = text, f"{(last['text'] or '').strip()} {text}".strip(), None
        if last["flushed"] is not None:
            if last["flushed"] == marker:
                return {"ok": True, "duplicate": True, "seq": seq}
            raise _err(409, "already flushed")
        es = ec.enc_sha256(enc, new_text)
        me = db.execute("SELECT sig_pub FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        sig_pub = me["sig_pub"] if me else None
        if sig_pub and (not sig or not ec.verify_sig(sig_pub, sig, ec.seg_message(job, seq, last["sha256"], es))):
            raise _err(422, "bad or missing segment signature")
        prev = db.execute("""SELECT link FROM segments WHERE job_id=? AND state='accepted' AND seq<? ORDER BY seq DESC
                             LIMIT 1""", (job, seq)).fetchone()
        lk = ec.link(prev["link"] if prev else None, job, last["sha256"], es, node_id)
        db.execute("""UPDATE segments SET flushed=?, text=?, enc=?, enc_sha256=?, sig=?, sig_pub=?, link=?
                      WHERE job_id=? AND seq=?""", (marker, new_text, canon, es, sig if sig_pub else None, sig_pub, lk,
                                                    job, seq))
        ps.emit(db, coord, "transcript.segment", {"job": job, "seq": seq, "text": new_text, "node": node_id,
                                                  "backend": last["backend"], "enc": enc, "link": lk,
                                                  "flush": True},  # the full segment: replaces by seq
                **ps.scope(db, lz["unit_id"], node_id))
        _receipt(db, coord, job, flush=True)
    return {"ok": True, "duplicate": False, "seq": seq}
