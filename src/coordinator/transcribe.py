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

from . import portal_store as ps

LIVE = "live_transcription"
SEG_MAX = 256 * 1024
MAX_GAP = 50
FETCH_LIMIT = 8
CONTEXT_CHARS = 200


def _core():
    from . import core
    return core


def _err(status: int, detail):
    return _core().CoordError(status, detail)


def live_unit(db, job_id: str):
    return db.execute("SELECT * FROM units WHERE job_id=? AND job_class=?", (job_id, LIVE)).fetchone()


def create_job(coord, client_id: str, idempotency_key: str, access_class: str = "public") -> dict:
    """POST /v1/client/jobs {type: live_transcription}: idempotent per (client, key)."""
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
                   (f"{job_id}-live", job_id, 0, LIVE, access_class, 0.0, 1.0, 10 ** 6, 0.0, 1, 1, "pending"))
        coord._audit(db, {"type": "submit", "job": job_id, "admitted": True, "reason": "live transcription", "units": 1})
    return {"job_id": job_id, "status": "admitted", "eta": None, "created": True}


def _owned_live(db, client_id: str, job_id: str):
    j = db.execute("SELECT * FROM jobs WHERE job_id=? AND client_id=?", (job_id, client_id)).fetchone()
    if j is None or j["job_type"] != LIVE:
        return None
    return j


def add_segment(coord, client_id: str, job_id: str, seq: int, body: bytes) -> dict | None:
    """Client upload. None = unknown/foreign job (404). Idempotent per (job, seq)."""
    if not isinstance(seq, int) or seq < 0:
        raise _err(422, "X-Seq must be an integer >= 0")
    if len(body) > SEG_MAX:
        raise _err(413, f"segment larger than {SEG_MAX} bytes")
    if len(body) < 44 or body[:4] != b"RIFF" or body[8:12] != b"WAVE":
        raise _err(422, "segment must be a WAV file")
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
        pub = coord.broker._jobs[job_id].priv.public_key()
        env = wire.envelope_to_bytes(trust.seal(body, pub))
        d = coord.dir / "segments" / job_id
        d.mkdir(parents=True, exist_ok=True)
        f, tmp = d / f"{seq}.env", d / f".{seq}.tmp"
        tmp.write_bytes(env)
        os.replace(tmp, f)
        db.execute("""INSERT INTO segments(job_id, seq, path, sha256, size, received_at, state)
                      VALUES(?,?,?,?,?,?,'pending')""", (job_id, seq, str(f.relative_to(coord.dir)), sha, len(body), now))
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
        rows = db.execute("""SELECT seq, text, node, backend, state FROM segments WHERE job_id=? ORDER BY seq""",
                          (job_id,)).fetchall()
    segs = [{"seq": r["seq"], "text": r["text"], "node": r["node"], "backend": r["backend"]} for r in rows
            if r["state"] == "accepted"]
    return {"job_id": job_id, "segments": segs, "pending": sum(1 for r in rows if r["state"] != "accepted"),
            "ended": j["ended_at"] is not None, "text": " ".join(s["text"].strip() for s in segs if s["text"].strip())}


# ------------------------------------------------------------------ node side (called from core.lease / app)


def lease_live(db, coord, me, now: float) -> dict | None:
    """In core.lease: a pending live unit goes to the first eligible node that asks (latency-bound)."""
    classes = set(json.loads(me["eligible_classes"]))
    u = db.execute("""SELECT * FROM units WHERE job_class=? AND state='pending' ORDER BY rowid LIMIT 1""", (LIVE,)).fetchone()
    if u is None or u["access_class"] not in classes:
        return None
    core = _core()
    node_id = me["node_id"]
    rel = coord._release(u["job_id"], node_id, coord._attestation(me), me["region"])
    coord._persist_audit(db)
    if isinstance(rel, trust.Denied):
        return None
    prev = db.execute("SELECT node_id FROM leases WHERE unit_id=? ORDER BY issued_at DESC LIMIT 1", (u["unit_id"],)).fetchone()
    lease_id = "l-" + secrets.token_hex(8)
    db.execute("INSERT INTO leases VALUES(?,?,?,?,?,?)", (lease_id, u["unit_id"], node_id, "active", now, now + core.LEASE_S))
    db.execute("UPDATE units SET state='leased' WHERE unit_id=?", (u["unit_id"],))
    coord._audit(db, {"type": "lease", "lease": lease_id, "unit": u["unit_id"], "node": node_id, "degraded": False})
    if prev is not None and prev["node_id"] != node_id:
        nxt = _next_seq(db, u["job_id"])
        ps.emit(db, coord, "job.moved", {"job": u["job_id"], "from": prev["node_id"], "to": node_id, "at_seq": nxt},
                **ps.scope(db, u["unit_id"], node_id))
    cur = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
    return coord._lease_payload(db, cur, now, False, key=rel)


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
        lz, u = _held(db, node_id, lease_id)
        job = u["job_id"]
        rows = db.execute("""SELECT seq, path, sha256 FROM segments WHERE job_id=? AND state='pending' AND seq>?
                             ORDER BY seq LIMIT ?""", (job, int(after), FETCH_LIMIT)).fetchall()
        acc = db.execute("""SELECT text FROM segments WHERE job_id=? AND state='accepted' ORDER BY seq DESC LIMIT 12""",
                         (job,)).fetchall()
        ended = db.execute("SELECT ended_at FROM jobs WHERE job_id=?", (job,)).fetchone()["ended_at"] is not None
        nxt = _next_seq(db, job)
    ctx = " ".join(r["text"].strip() for r in reversed(acc) if r["text"])[-CONTEXT_CHARS:]
    segs = [{"seq": r["seq"], "sha256": r["sha256"],
             "envelope_b64": base64.b64encode((coord.dir / r["path"]).read_bytes()).decode()} for r in rows]
    return {"job_id": job, "segments": segs, "next_seq": nxt, "ended": ended, "context": ctx}


def accept(coord, node_id: str, lease_id: str, seq: int, text: str, words, backend: str, ms: float) -> dict:
    """Exactly once per seq, in order: dup = 200 no-op, conflicting text = 409, out of order = 409."""
    now = coord.clock()
    with coord._tx() as db:
        coord._expire(db, now)
        row = None
        lz = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
        if lz is not None:
            u0 = db.execute("SELECT job_id FROM units WHERE unit_id=?", (lz["unit_id"],)).fetchone()
            row = db.execute("SELECT * FROM segments WHERE job_id=? AND seq=?", (u0["job_id"], seq)).fetchone() if u0 else None
        if row is not None and row["state"] == "accepted":  # idempotent even after the lease moved on
            if (row["text"] or "") == (text or ""):
                return {"ok": True, "duplicate": True, "seq": seq}
            raise _err(409, "conflicting text for an already accepted segment")
        lz, u = _held(db, node_id, lease_id)
        job = u["job_id"]
        if row is None:
            raise _err(404, "no such segment")
        nxt = _next_seq(db, job)
        if seq != nxt:
            raise _err(409, f"out of order: the next segment to accept is {nxt}")
        db.execute("""UPDATE segments SET state='accepted', text=?, words=?, node=?, backend=?, ms=?, accepted_at=?
                      WHERE job_id=? AND seq=?""", (text, json.dumps(words) if words is not None else None, node_id,
                                                    backend, ms, now, job, seq))
        db.execute("UPDATE leases SET expires_at=? WHERE lease_id=?", (now + _core().LEASE_S, lease_id))  # progress = alive
        ps.emit(db, coord, "transcript.segment", {"job": job, "seq": seq, "text": text, "node": node_id, "backend": backend},
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
