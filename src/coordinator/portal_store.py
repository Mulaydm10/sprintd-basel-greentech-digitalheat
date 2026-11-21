"""Portal data layer (contracts/src/portal.md §P1). The ONLY place P2 (`portal/client.py`, `portal/host.py`) and
P3 (`portal/ops.py`, `portal/events.py`) touch coordinator state. Routers call these functions; they never run SQL.

Conventions (all functions):
- First argument `coord` is the running `coordinator.core.Coordinator` (routers get it as `request.app.state.coord`).
- Ownership is enforced INSIDE the query: a function scoped to `client_id` / `site_id` returns `None` for an unknown
  OR foreign id, and the router answers 404 (never 403, so ids cannot be probed).
- Pagination: `limit` 1..200, `cursor` = opaque string from the previous page's `next_cursor` (None = first page);
  lists are newest-first and return `{"items": [...], "next_cursor": str | None}`.
- Times are ISO-8601 UTC strings, energies kWh, money CHF.
- Business errors raise `coordinator.core.CoordError(status, detail)`; `detail` may be a dict (e.g. 422 rejected).
- Every state change runs in ONE `coord._tx()` and writes its events in the same transaction (restart-safe).

Event types (stored in the `events` table, ring of 10 000; `id` strictly increasing):
  node.state, lease.granted, lease.renewed, lease.lapsed, lease.released, unit.progress,
  unit.migrated {from, to, next_chunk}, job.state, site.signal, site.paused, audit.appended
Each event row: {id, ts, type, client_id|None, site_id|None, node_id|None, job_id|None, data:{...}}.
Visibility: client sees rows with its client_id; host sees rows with its site_id; admin/observer see all.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .auth import ID_RE, Principal

RING = 10_000  # events kept
OFFLINE_S = 60.0  # no heartbeat for this long -> offline (SUSPECT_S .. OFFLINE_S -> suspect)
SIGNAL_EVENT_EVERY_S = 10.0  # site.signal events are throttled per site (signals arrive every ~2 s)
ACCOUNT_MAX_DT_S = 10.0  # hourly accounting never credits a gap between two signals longer than this
SCENARIOS = ("coldest", "july")
ACCESS = ("public", "swiss-only", "certified")
IDEM_MAX = 64
PAGE_MAX = 200
JOB_AUDIT = {"lease", "lease_paused", "lease_released", "lease_lapsed", "complete", "submit", "job_cancelled"}


def _core():
    from . import core
    return core


def _err(status: int, detail):
    return _core().CoordError(status, detail)


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat().replace("+00:00", "Z")


def _limit(limit) -> int:
    return max(1, min(int(limit), PAGE_MAX))


def _enc(key: str) -> str:
    return base64.urlsafe_b64encode(key.encode()).decode()


def _dec(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor.encode()).decode()
    except Exception:  # noqa: BLE001
        raise _err(422, "bad cursor") from None


def _page(items: list, key, limit, cursor: str | None) -> dict[str, Any]:
    """Page a small, already newest-first list (nodes, sites). The cursor is the last item's key."""
    n, start = _limit(limit), 0
    if cursor:
        k = _dec(cursor)
        idx = next((i for i, x in enumerate(items) if key(x) == k), None)
        if idx is None:
            raise _err(422, "unknown cursor")
        start = idx + 1
    page = items[start:start + n]
    return {"items": page, "next_cursor": _enc(key(page[-1])) if page and start + n < len(items) else None}


def _local_starts(coord, now: float) -> tuple[float, float]:
    """(local midnight today, local first of the month) as epoch seconds."""
    tz = ZoneInfo(coord.a["location"]["tz"])
    t = datetime.fromtimestamp(now, tz)
    day = t.replace(hour=0, minute=0, second=0, microsecond=0)
    return day.timestamp(), day.replace(day=1).timestamp()


# ------------------------------------------------------------------ events (written by P1 at every transition)


def scope(db, unit_id: str | None = None, node_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
    """Who may see an event about this unit/node/job: {client_id, site_id, node_id, job_id}."""
    client = site = None
    if unit_id and not job_id:
        r = db.execute("SELECT job_id FROM units WHERE unit_id=?", (unit_id,)).fetchone()
        job_id = r["job_id"] if r else None
    if job_id:
        r = db.execute("SELECT client_id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        client = r["client_id"] if r else None
    if node_id:
        r = db.execute("SELECT site_id FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        site = r["site_id"] if r else None
    return {"client_id": client, "site_id": site, "node_id": node_id, "job_id": job_id}


def emit(db, coord, type: str, data: dict[str, Any], *, client_id: str | None = None, site_id: str | None = None,
         node_id: str | None = None, job_id: str | None = None) -> int:
    """Append one event INSIDE the caller's transaction `db`; trims the ring to 10 000; returns its id."""
    cur = db.execute("INSERT INTO events(ts, type, client_id, site_id, node_id, job_id, data) VALUES(?,?,?,?,?,?,?)",
                     (coord.clock(), type, client_id, site_id, node_id, job_id,
                      json.dumps(data, sort_keys=True, default=str)))
    eid = int(cur.lastrowid)
    if eid % 100 == 0:
        db.execute("DELETE FROM events WHERE id <= ?", (eid - RING,))
    return eid


def on_audit(db, coord, idx: int, ev: dict[str, Any]) -> None:
    """Called by Coordinator._persist_audit for every audit row it writes (same transaction): audit.appended plus
    the typed event for the transition it records."""
    t, unit, node = ev.get("type"), ev.get("unit"), ev.get("node")
    sc = scope(db, unit, node, ev.get("job"))
    if t == "site_override":
        sc["site_id"] = ev.get("site")
    emit(db, coord, "audit.appended", {"idx": idx, **ev}, **sc)
    if t == "lease":
        emit(db, coord, "lease.granted", {"lease": ev["lease"], "unit": unit, "node": node}, **sc)
        prev = db.execute("""SELECT node_id FROM leases WHERE unit_id=? AND lease_id<>?
                             ORDER BY issued_at DESC LIMIT 1""", (unit, ev["lease"])).fetchone()
        if prev is not None and prev["node_id"] != node:
            ck = db.execute("SELECT next_chunk FROM checkpoints WHERE unit_id=? ORDER BY seq DESC LIMIT 1",
                            (unit,)).fetchone()
            emit(db, coord, "unit.migrated", {"unit": unit, "from": prev["node_id"], "to": node,
                                              "next_chunk": ck["next_chunk"] if ck else 0}, **sc)
    elif t == "lease_paused":
        emit(db, coord, "lease.released", {"lease": ev["lease"], "unit": unit, "node": node, "paused": True,
                                           "reason": ev.get("reason")}, **sc)
    elif t == "lease_released":
        emit(db, coord, "lease.released", {"lease": ev["lease"], "unit": unit, "node": node,
                                           "final_checkpoint": True, "next_chunk": ev.get("next_chunk")}, **sc)
    elif t == "lease_lapsed":
        emit(db, coord, "lease.lapsed", {"lease": ev["lease"], "unit": unit, "node": node}, **sc)
    elif t == "register_node":
        emit(db, coord, "node.state", {"node": node, "state": "online", "site": ev.get("site")}, **sc)
    elif t == "tamper":
        emit(db, coord, "node.state", {"node": node, "state": "tampered"}, **sc)
    elif t in ("node_drained", "node_undrained"):
        emit(db, coord, "node.state", {"node": node, "state": "paused" if t == "node_drained" else "online",
                                       "drained": t == "node_drained"}, **sc)
    elif t == "site_override":
        emit(db, coord, "site.paused", {"site": ev.get("site"), "paused": ev.get("paused"),
                                        "until": ev.get("until")}, **sc)
    if t in JOB_AUDIT and sc["job_id"]:
        job_state_event(db, coord, sc["job_id"])


def job_state_event(db, coord, job_id: str) -> None:
    j = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if j is None:
        return
    st = _job_status(db, j)
    if st != j["status"]:
        db.execute("UPDATE jobs SET status=? WHERE job_id=?", (st, job_id))
        emit(db, coord, "job.state", {"job": job_id, "status": st}, client_id=j["client_id"], job_id=job_id)


def heartbeat_events(db, coord, before, after, now: float) -> None:
    core = _core()
    if now - float(before["last_hb"]) > core.SUSPECT_S:
        emit(db, coord, "node.state", {"node": after["node_id"], "state": "online", "recovered": True},
             **scope(db, None, after["node_id"]))
    unit = after["running_unit"]
    if unit and (unit != before["running_unit"] or after["progress"] != before["progress"]):
        emit(db, coord, "unit.progress", {"unit": unit, "node": after["node_id"], "progress": after["progress"]},
             **scope(db, unit, after["node_id"]))


def site_signal_event(db, coord, site_id: str, now: float, demand_kw: float, tank_kwh: float, heat_kw: float) -> None:
    last = coord.__dict__.setdefault("_portal_sig_ev", {})
    if now - last.get(site_id, -1e18) >= SIGNAL_EVENT_EVERY_S:
        last[site_id] = now
        emit(db, coord, "site.signal", {"site": site_id, "demand_kw": demand_kw, "tank_level_kwh": tank_kwh,
                                        "heat_used_kw": heat_kw}, site_id=site_id)


def account_site(db, coord, site_id: str, now: float) -> None:
    """Credit the interval since the site's previous signal to its hour bucket (the coordinator's own tick log):
    heat from the nodes holding active leases there; dumped = what the house could not take with a full tank."""
    prev = db.execute("SELECT * FROM sites WHERE site_id=?", (site_id,)).fetchone()
    if prev is None:
        return
    dt = min(now - float(prev["received_at"]), ACCOUNT_MAX_DT_S)
    if dt <= 0:
        return
    heat = coord._site_heat(db).get(site_id, 0.0)
    demand, tank = float(prev["demand_kw"]), float(prev["tank_level_kwh"])
    cap = float(coord.a["house"]["tank_kwh"])
    dumped = max(0.0, heat - demand) if tank >= cap - 1e-6 else 0.0
    h = dt / 3600.0
    db.execute("""INSERT INTO site_hourly(site_id, hour_ts, heat_kwh, dumped_kwh, demand_kwh) VALUES(?,?,?,?,?)
                  ON CONFLICT(site_id, hour_ts) DO UPDATE SET heat_kwh=heat_kwh+excluded.heat_kwh,
                  dumped_kwh=dumped_kwh+excluded.dumped_kwh, demand_kwh=demand_kwh+excluded.demand_kwh""",
               (site_id, int(now // 3600 * 3600), (heat - dumped) * h, dumped * h, demand * h))


def site_paused(db, site_id: str, now: float) -> bool:
    r = db.execute("SELECT paused, until_ts FROM site_override WHERE site_id=?", (site_id,)).fetchone()
    return bool(r and r["paused"] and (r["until_ts"] is None or now < float(r["until_ts"])))


def revoke_leases(db, coord, where: str, args: tuple, reason: str) -> list[str]:
    """Revoke matching active/paused leases NOW (their next renew/upload/complete -> 410); held units go back to
    pending. Emits lease.released per lease and the affected jobs' job.state. Returns the revoked lease ids."""
    rows = db.execute(f"SELECT lease_id, unit_id, node_id, state FROM leases WHERE {where}", args).fetchall()
    jobs = set()
    for lz in rows:
        db.execute("UPDATE leases SET state='revoked' WHERE lease_id=?", (lz["lease_id"],))
        db.execute("UPDATE units SET state='pending' WHERE unit_id=? AND state='leased'", (lz["unit_id"],))
        sc = scope(db, lz["unit_id"], lz["node_id"])
        emit(db, coord, "lease.released", {"lease": lz["lease_id"], "unit": lz["unit_id"], "node": lz["node_id"],
                                           "revoked": True, "reason": reason}, **sc)
        jobs.add(sc["job_id"])
    for j in jobs - {None}:
        job_state_event(db, coord, j)
    return [r["lease_id"] for r in rows]


def events_after(coord, principal: Principal, after_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    """Events with id > after_id visible to `principal` (client: its jobs; host: its site; admin/observer: all),
    oldest-first, at most `limit`. A gap (after_id older than the ring) simply starts at the oldest kept."""
    if principal.role in ("admin", "observer"):
        where, args = "", ()
    elif principal.role == "client" and principal.client_id:
        where, args = "AND client_id=?", (principal.client_id,)
    elif principal.role == "host" and principal.site_id:
        where, args = "AND site_id=?", (principal.site_id,)
    else:
        return []
    rows = coord.store.q(f"SELECT * FROM events WHERE id > ? {where} ORDER BY id LIMIT ?",
                         int(after_id), *args, max(1, min(int(limit), 1000)))
    return [{"id": r["id"], "ts": _iso(r["ts"]), "type": r["type"], "data": json.loads(r["data"]),
             "job_id": r["job_id"], "node_id": r["node_id"], "site_id": r["site_id"]} for r in rows]


def last_event_id(coord) -> int:
    r = coord.store.one("SELECT MAX(id) m FROM events")
    return int(r["m"] or 0)


events_head = last_event_id  # P3's name (#85)


# ------------------------------------------------------------------ jobs: status, units, views


def _job_status(db, j) -> str:
    if not j["admitted"]:
        return "failed"
    if j["cancelled_at"] is not None:
        return "cancelled"
    states = [r[0] for r in db.execute("SELECT state FROM units WHERE job_id=?", (j["job_id"],))]
    if states and all(s == "done" for s in states):
        return "done"
    if "leased" in states:
        return "running"
    if db.execute("""SELECT 1 FROM units u JOIN checkpoints c ON c.unit_id = u.unit_id
                     WHERE u.job_id=? AND u.state='pending' LIMIT 1""", (j["job_id"],)).fetchone():
        return "paused"
    return "queued"


def _deadline_ts(coord, j) -> float:
    return coord._year_start(float(j["created_at"])).timestamp() + int(j["deadline_hour"]) * 3600.0


def _live_nodes(db, now: float) -> int:
    core = _core()
    return db.execute("SELECT COUNT(*) FROM nodes WHERE tampered=0 AND drained=0 AND last_hb >= ?",
                      (now - core.SUSPECT_S,)).fetchone()[0]


def _units(db, job_id: str) -> list[dict[str, Any]]:
    out = []
    for u in db.execute("SELECT * FROM units WHERE job_id=? ORDER BY seq", (job_id,)).fetchall():
        ck = db.execute("SELECT next_chunk FROM checkpoints WHERE unit_id=? ORDER BY seq DESC LIMIT 1",
                        (u["unit_id"],)).fetchone()
        done = ck["next_chunk"] if ck else 0
        node, st = None, u["state"]
        if st == "done":
            status, done, node = "done", u["chunks"], u["completed_by"]
        elif st == "cancelled":
            status = "cancelled"
        elif st == "leased":
            status = "running"
            lz = db.execute("SELECT node_id FROM leases WHERE unit_id=? AND state='active'", (u["unit_id"],)).fetchone()
            node = lz["node_id"] if lz else None
            if node:
                n = db.execute("SELECT running_unit, progress FROM nodes WHERE node_id=?", (node,)).fetchone()
                if n and n["running_unit"] == u["unit_id"] and n["progress"] is not None:
                    done = max(done, int(float(n["progress"]) * u["chunks"]))
        else:
            status = "paused" if ck else "queued"
        out.append({"unit_id": u["unit_id"], "status": status, "node_id": node, "done_chunks": min(done, u["chunks"]),
                    "total_chunks": u["chunks"]})
    return out


def _job_view(coord, db, j, now: float, full: bool) -> dict[str, Any]:
    st = _job_status(db, j)
    units = _units(db, j["job_id"]) if j["admitted"] else []
    total = sum(u["total_chunks"] for u in units)
    progress = round(sum(u["done_chunks"] for u in units) / total, 4) if total else 0.0
    deadline = _deadline_ts(coord, j)
    if st == "done":
        finished = db.execute("SELECT MAX(completed_at) FROM units WHERE job_id=?", (j["job_id"],)).fetchone()[0]
        eta, missed = finished, finished is not None and float(finished) > deadline
    elif st in ("queued", "running", "paused"):
        left = sum(1 for u in units if u["status"] != "done")
        unit_s = float(coord.a["scheduler"]["unit_minutes"]) * 60.0
        eta = now + left * unit_s / max(1, _live_nodes(db, now))
        missed = now > deadline
    else:
        eta, missed = None, False
    v = {"job_id": j["job_id"], "type": j["job_type"], "access_class": j["access_class"], "status": st,
         "progress": progress, "deadline": _iso(deadline), "eta": _iso(eta), "missed_deadline": bool(missed),
         "created_at": _iso(j["created_at"]), "reason": j["reason"], "units_total": len(units)}
    if full:
        ev = db.execute("SELECT * FROM events WHERE job_id=? ORDER BY id DESC LIMIT 50", (j["job_id"],)).fetchall()
        v["units"] = units
        v["events"] = [{"id": r["id"], "ts": _iso(r["ts"]), "type": r["type"], "data": json.loads(r["data"])}
                       for r in ev]
    return v


def _jobs_page(coord, where: str, args: tuple, limit, cursor: str | None, extra=None) -> dict[str, Any]:
    n = _limit(limit)
    cond, cargs = "", ()
    if cursor:
        ts, _, jid = _dec(cursor).partition("|")
        try:
            tsf = float(ts)
        except ValueError:
            raise _err(422, "bad cursor") from None
        cond, cargs = " AND (created_at < ? OR (created_at = ? AND job_id < ?))", (tsf, tsf, jid)
    now = coord.clock()
    with coord.store.lock:
        db = coord.store.db
        rows = db.execute(f"SELECT * FROM jobs WHERE {where}{cond} ORDER BY created_at DESC, job_id DESC LIMIT ?",
                          (*args, *cargs, n + 1)).fetchall()
        items = [_job_view(coord, db, j, now, False) | (extra(j) if extra else {}) for j in rows[:n]]
    nxt = _enc(f"{rows[n - 1]['created_at']!r}|{rows[n - 1]['job_id']}") if len(rows) > n else None
    return {"items": items, "next_cursor": nxt}


# ------------------------------------------------------------------ client  (role client:<client_id>)


def client_summary(coord, client_id: str) -> dict[str, Any]:
    """{client_id, jobs_total, jobs_running, server_h_used, chf_spent}. server_h_used = completed units' kWh /
    server kW; chf_spent = server_h_used x the job type's price."""
    kw = float(coord.a["server"]["electric_kw"])
    with coord.store.lock:
        db = coord.store.db
        jobs = db.execute("SELECT * FROM jobs WHERE client_id=?", (client_id,)).fetchall()
        running = sum(1 for j in jobs if _job_status(db, j) in ("running", "paused"))
        used = db.execute("""SELECT j.job_type, SUM(u.kwh_el) kwh FROM units u JOIN jobs j ON j.job_id = u.job_id
                             WHERE j.client_id=? AND u.state='done' GROUP BY j.job_type""", (client_id,)).fetchall()
    server_h = sum(float(r["kwh"]) / kw for r in used)
    chf = sum(float(r["kwh"]) / kw * coord.catalogue[r["job_type"]].price_chf_per_h
              for r in used if r["job_type"] in coord.catalogue)
    return {"client_id": client_id, "jobs_total": len(jobs), "jobs_running": running,
            "server_h_used": round(server_h, 6), "chf_spent": round(chf, 4)}


def catalogue(coord) -> list[dict[str, Any]]:
    """[{type, label, access_classes, est_unit_min, price_chf_server_h}] from the jobs catalogue."""
    unit_min = float(coord.a["scheduler"]["unit_minutes"])
    return [{"type": name, "label": name.replace("_", " ").capitalize(),
             "access_classes": [jt.access_class] + [c for c in ACCESS if c != jt.access_class],
             "default_access_class": jt.access_class, "est_unit_min": unit_min,
             "price_chf_server_h": jt.price_chf_per_h, "runtime_h": jt.runtime_h, "deadline_h": jt.deadline_h,
             "measured": jt.measured}
            for name, jt in sorted(coord.catalogue.items())]


def _submit_reply(coord, row, created: bool) -> dict[str, Any]:
    if not row["admitted"]:
        raise _err(422, {"status": "rejected", "reason": row["reason"], "job_id": row["job_id"]})
    v = get_client_job(coord, row["client_id"], row["job_id"])
    return {"job_id": row["job_id"], "status": "admitted", "eta": v["eta"] if v else None, "created": created}


def submit_client_job(coord, client_id: str, *, type: str, access_class: str, deadline_h: float,
                      idempotency_key: str, rounds: int | None = None, chunks: int | None = None) -> dict[str, Any]:
    """Admit via scheduler.admit (no `force`). Returns {job_id, status: "admitted", eta, created: bool}; the router
    answers 201 when created, 200 for an idempotent replay (same client_id + idempotency_key -> same job, never a
    duplicate). Rejected -> raises CoordError(422, {"status": "rejected", "reason": ...})."""
    def rejected(reason: str):
        return _err(422, {"status": "rejected", "reason": reason})
    if not ID_RE.match(client_id or ""):
        raise rejected("bad client id")
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= IDEM_MAX \
            or not all(c.isalnum() or c in "-_.:" for c in idempotency_key) or not idempotency_key.isascii():
        raise rejected(f"idempotency_key must be 1..{IDEM_MAX} characters of [A-Za-z0-9-_.:]")
    find = "SELECT * FROM jobs WHERE client_id=? AND idempotency_key=?"
    old = coord.store.one(find, client_id, idempotency_key)
    if old is not None:
        return _submit_reply(coord, old, created=False)
    if type not in coord.catalogue:
        raise rejected(f"unknown job type; one of {sorted(coord.catalogue)}")
    if access_class not in ACCESS:
        raise rejected(f"access_class must be one of {list(ACCESS)}")
    if not 0.25 <= float(deadline_h) <= 720:
        raise rejected("deadline_h must be in [0.25, 720]")
    core = _core()
    try:
        out = coord.submit_job(type, client_id, access_class, float(deadline_h), False, rounds, chunks,
                               client_id=client_id, idempotency_key=idempotency_key)
    except core.CoordError as e:
        if e.status == 422 and isinstance(e.detail, str):
            raise rejected(e.detail) from None
        raise
    except sqlite3.IntegrityError:  # a concurrent request with the same key won the race
        return _submit_reply(coord, coord.store.one(find, client_id, idempotency_key), created=False)
    return _submit_reply(coord, coord.store.one("SELECT * FROM jobs WHERE job_id=?", out["job_id"]), created=True)


def list_client_jobs(coord, client_id: str, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    """{items: [job summary], next_cursor}; job summary as in get_client_job without units/events."""
    return _jobs_page(coord, "client_id=?", (client_id,), limit, cursor)


def get_client_job(coord, client_id: str, job_id: str) -> dict[str, Any] | None:
    """{job_id, type, access_class, status: queued|running|paused|done|failed|cancelled, progress 0..1,
    units: [{unit_id, status, node_id|None, done_chunks, total_chunks}], deadline, eta, missed_deadline,
    events: [last 50]} or None (unknown/foreign)."""
    now = coord.clock()
    with coord.store.lock:
        db = coord.store.db
        j = db.execute("SELECT * FROM jobs WHERE job_id=? AND client_id=?", (job_id, client_id)).fetchone()
        return None if j is None else _job_view(coord, db, j, now, True)


def cancel_client_job(coord, client_id: str, job_id: str) -> dict[str, Any] | None:
    """Cancel (idempotent): pending units -> cancelled, active leases revoked (a renew after this -> 410).
    Returns the job (as get_client_job) or None."""
    now = coord.clock()
    with coord._tx() as db:
        j = db.execute("SELECT * FROM jobs WHERE job_id=? AND client_id=?", (job_id, client_id)).fetchone()
        if j is None:
            return None
        if j["admitted"] and j["cancelled_at"] is None and _job_status(db, j) != "done":
            db.execute("UPDATE jobs SET cancelled_at=? WHERE job_id=?", (now, job_id))
            revoked = revoke_leases(db, coord, "state IN ('active','paused') AND unit_id IN "
                                    "(SELECT unit_id FROM units WHERE job_id=?)", (job_id,), "job cancelled")
            db.execute("UPDATE units SET state='cancelled' WHERE job_id=? AND state IN ('pending','leased')",
                       (job_id,))
            coord._audit(db, {"type": "job_cancelled", "job": job_id, "revoked": len(revoked)})
    return get_client_job(coord, client_id, job_id)


def store_result(db, coord, unit_id: str, job_id: str, sha256: str) -> bool:
    """Open the unit's final checkpoint bundle with the job key and keep its output if it hashes to the completed
    result_sha256 (results/<unit_id>, atomic). False when no matching final checkpoint exists."""
    import trust
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from live_agent import wire
    u = db.execute("SELECT chunks FROM units WHERE unit_id=?", (unit_id,)).fetchone()
    c = db.execute("SELECT * FROM checkpoints WHERE unit_id=? ORDER BY seq DESC LIMIT 1", (unit_id,)).fetchone()
    j = db.execute("SELECT priv_key FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if u is None or c is None or j is None or not j["priv_key"] or c["next_chunk"] != u["chunks"]:
        return False
    try:
        env = wire.envelope_from_bytes((coord.dir / c["path"]).read_bytes())
        _, out = wire.bundle_from_bytes(trust.open_(env, X25519PrivateKey.from_private_bytes(j["priv_key"])))
    except Exception:  # noqa: BLE001 - unreadable/foreign bundle: no result bytes, completion itself stands
        return False
    if hashlib.sha256(out).hexdigest() != sha256:
        return False
    d = coord.dir / "results"
    d.mkdir(parents=True, exist_ok=True)
    final, tmp = d / unit_id, d / f".{unit_id}.tmp"
    with open(tmp, "wb") as f:
        f.write(out)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, final)
    db.execute("INSERT OR REPLACE INTO results(unit_id, job_id, sha256, path, bytes) VALUES(?,?,?,?,?)",
               (unit_id, job_id, sha256, str(final.relative_to(coord.dir)), len(out)))
    return True


def _owned_done_job(coord, client_id: str, job_id: str):
    j = coord.store.one("SELECT * FROM jobs WHERE job_id=? AND client_id=?", job_id, client_id)
    if j is None:
        return None
    with coord.store.lock:
        st = _job_status(coord.store.db, j)
    if st != "done":
        raise _err(409, f"job is {st}; the result exists once every unit is done")
    return j


def get_result(coord, client_id: str, job_id: str) -> tuple[bytes, str] | None:
    """(output bytes, sha256 hex) assembled from each unit's final checkpoint bundle (decrypted with the job key,
    each unit's output verified against its completed result_sha256, concatenated in unit order).
    None if unknown/foreign; CoordError(409) until every unit is done."""
    j = _owned_done_job(coord, client_id, job_id)
    if j is None:
        return None
    parts = []
    for u in coord.store.q("SELECT unit_id, result_sha256 FROM units WHERE job_id=? ORDER BY seq", job_id):
        r = coord.store.one("SELECT * FROM results WHERE unit_id=?", u["unit_id"])
        if r is None:
            with coord._tx() as db:  # completed before the final bundle was readable: try once more
                store_result(db, coord, u["unit_id"], job_id, u["result_sha256"])
            r = coord.store.one("SELECT * FROM results WHERE unit_id=?", u["unit_id"])
        if r is None:
            raise _err(409, f"result bytes for {u['unit_id']} are not available (no final checkpoint was uploaded)")
        data = (coord.dir / r["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != u["result_sha256"]:
            raise _err(500, "stored result failed its integrity check")
        parts.append(data)
    out = b"".join(parts)
    return out, hashlib.sha256(out).hexdigest()


def get_receipt(coord, client_id: str, job_id: str) -> dict[str, Any] | None:
    """{result_sha256, chunk_ids, nodes_used, kwh, heat_used_kwh, audit_head} once done (409 before).
    result_sha256 is the sha256 of GET .../result (None if a unit's bytes are unavailable); chunk_ids maps unit ->
    its completed chunk ids; nodes_used are the nodes that held a lease (= got the job key) for it."""
    j = _owned_done_job(coord, client_id, job_id)
    if j is None:
        return None
    core = _core()
    try:
        res = get_result(coord, client_id, job_id)
        sha = res[1]
    except core.CoordError:
        sha = None
    units = coord.store.q("SELECT * FROM units WHERE job_id=? ORDER BY seq", job_id)
    nodes = sorted({r["node_id"] for r in coord.store.q(
        "SELECT DISTINCT l.node_id FROM leases l JOIN units u ON u.unit_id = l.unit_id WHERE u.job_id=?", job_id)})
    kwh = sum(float(u["kwh_el"]) for u in units)
    head = coord.store.one("SELECT hash, idx FROM audit ORDER BY idx DESC LIMIT 1")
    return {"job_id": job_id, "access_class": j["access_class"], "result_sha256": sha,
            "unit_results": [{"unit_id": u["unit_id"], "result_sha256": u["result_sha256"],
                              "completed_by": u["completed_by"], "completed_at": _iso(u["completed_at"])}
                             for u in units],
            "chunk_ids": {u["unit_id"]: json.loads(u["done_chunks"] or "[]") for u in units},
            "nodes_used": nodes, "kwh": round(kwh, 6),
            "heat_used_kwh": round(kwh * float(coord.a["server"]["heat_recovery_fraction"]), 6),
            "audit_head": head["hash"] if head else None, "audit_length": (head["idx"] + 1) if head else 0}


# ------------------------------------------------------------------ nodes and sites


def _node_state(n, now: float, owner_paused: bool) -> str:
    core = _core()
    age = now - float(n["last_hb"])
    if n["tampered"]:
        return "tampered"
    if age > OFFLINE_S:
        return "offline"
    if age > core.SUSPECT_S:
        return "suspect"
    if n["drained"] or owner_paused or not n["mode_running"]:
        return "paused"
    return "online"


def _node_view(coord, db, n, now: float) -> dict[str, Any]:
    reg = coord.registry.get(n["node_id"]) or {}
    paused = site_paused(db, n["site_id"], now)
    return {"node_id": n["node_id"], "site_id": n["site_id"], "region": n["region"],
            "state": _node_state(n, now, paused), "drained": bool(n["drained"]), "tampered": bool(n["tampered"]),
            "certified": bool(reg.get("certified")), "classes": json.loads(n["eligible_classes"]),
            "server_kw_el": n["server_kw_el"], "watts": n["watts"], "running_unit": n["running_unit"],
            "progress": n["progress"], "last_heartbeat_s": round(now - float(n["last_hb"]), 3),
            "last_error": n["last_error"]}


def _site_known(db, coord, site_id: str) -> bool:
    return bool(db.execute("SELECT 1 FROM sites WHERE site_id=?", (site_id,)).fetchone()
                or db.execute("SELECT 1 FROM nodes WHERE site_id=?", (site_id,)).fetchone()
                or any(r.get("site_id") == site_id for r in coord.registry.values()))


def _site_view(coord, db, site_id: str, now: float) -> dict[str, Any]:
    core = _core()
    s = db.execute("SELECT * FROM sites WHERE site_id=?", (site_id,)).fetchone()
    o = db.execute("SELECT * FROM site_override WHERE site_id=?", (site_id,)).fetchone()
    day, month = _local_starts(coord, now)

    def total(col: str, since: float) -> float:
        v = db.execute(f"SELECT SUM({col}) FROM site_hourly WHERE site_id=? AND hour_ts >= ?",
                       (site_id, int(since // 3600 * 3600))).fetchone()[0]
        return round(float(v or 0.0), 6)

    heat_today = total("heat_kwh", day)
    p, div = float(coord.a["price"]["chf_per_kwh"]), float(coord.a["price"]["heat_value_divisor"])
    paused = site_paused(db, site_id, now)
    return {"site_id": site_id, "demand_kw": s["demand_kw"] if s else None,
            "tank_level_kwh": s["tank_level_kwh"] if s else None,
            "signal_age_s": round(now - float(s["received_at"]), 3) if s else None,
            "degraded": s is None or now - float(s["received_at"]) > core.SIGNAL_MAX_AGE_S,
            "paused": paused, "paused_until": _iso(o["until_ts"]) if paused and o["until_ts"] is not None else None,
            "heat_used_kw": coord._site_heat(db).get(site_id, 0.0),
            "nodes": [_node_view(coord, db, n, now) for n in
                      db.execute("SELECT * FROM nodes WHERE site_id=? ORDER BY node_id", (site_id,)).fetchall()],
            "heat_today_kwh": heat_today, "heat_month_kwh": total("heat_kwh", month),
            "dumped_today_kwh": total("dumped_kwh", day), "chf_heat_value_today": round(heat_today * p / div, 4)}


# ------------------------------------------------------------------ host  (role host:<site_id>)


def host_site(coord, site_id: str) -> dict[str, Any] | None:
    """{site_id, demand_kw, tank_level_kwh, degraded, paused, paused_until, nodes: [node summary],
    heat_today_kwh, heat_month_kwh, dumped_today_kwh, chf_heat_value_today} or None if no such site."""
    now = coord.clock()
    with coord.store.lock:
        db = coord.store.db
        return _site_view(coord, db, site_id, now) if _site_known(db, coord, site_id) else None


def host_node(coord, site_id: str, node_id: str) -> dict[str, Any] | None:
    """Node summary + {watts, running_unit, progress, last_heartbeat_s,
    state: online|suspect|offline|paused|tampered}, or None if the node is not at this site."""
    now = coord.clock()
    with coord.store.lock:
        db = coord.store.db
        n = db.execute("SELECT * FROM nodes WHERE node_id=? AND site_id=?", (node_id, site_id)).fetchone()
        return None if n is None else _node_view(coord, db, n, now)


def set_site_override(coord, site_id: str, *, paused: bool, until_ts: float | None = None) -> dict[str, Any]:
    """Owner override: paused -> the scheduler sees zero heat demand for the site (running units hold on their next
    renew). Idempotent, audited, emits site.paused. Returns host_site(...)."""
    now = coord.clock()
    if until_ts is not None and (not paused or float(until_ts) <= now):
        raise _err(422, "until must be in the future, and only with pause")
    with coord._tx() as db:
        if not _site_known(db, coord, site_id):
            raise _err(404, "unknown site")
        cur = db.execute("SELECT paused, until_ts FROM site_override WHERE site_id=?", (site_id,)).fetchone()
        was = site_paused(db, site_id, now)
        same_until = cur is not None and cur["until_ts"] == (None if until_ts is None else float(until_ts))
        if was != paused or (paused and not same_until):
            db.execute("""INSERT INTO site_override(site_id, paused, until_ts, at) VALUES(?,?,?,?)
                          ON CONFLICT(site_id) DO UPDATE SET paused=excluded.paused, until_ts=excluded.until_ts,
                          at=excluded.at""", (site_id, int(paused), None if until_ts is None else float(until_ts), now))
            coord._audit(db, {"type": "site_override", "site": site_id, "paused": bool(paused),
                              "until": _iso(until_ts)})
    return host_site(coord, site_id)


def host_history(coord, site_id: str, hours: int = 24) -> list[dict[str, Any]]:
    """Hourly [{ts, heat_kwh, dumped_kwh, demand_kwh}] from the coordinator's own tick log (never invented); hours
    without data are omitted."""
    hours = max(1, min(int(hours), 24 * 31))
    since = int(coord.clock() // 3600 * 3600) - (hours - 1) * 3600
    return [{"ts": _iso(r["hour_ts"]), "heat_kwh": round(r["heat_kwh"], 6), "dumped_kwh": round(r["dumped_kwh"], 6),
             "demand_kwh": round(r["demand_kwh"], 6)}
            for r in coord.store.q("SELECT * FROM site_hourly WHERE site_id=? AND hour_ts >= ? ORDER BY hour_ts",
                                   site_id, since)]


# ------------------------------------------------------------------ operator  (admin; observer = GETs)


def _all_sites(db, coord) -> list[str]:
    ids = {r[0] for r in db.execute("SELECT site_id FROM sites")} | {r[0] for r in db.execute("SELECT site_id FROM nodes")}
    return sorted(ids)


def ops_overview(coord) -> dict[str, Any]:
    """{nodes: {online, suspect, offline}, jobs: {queued, running, done, failed}, leases_active,
    heat_used_kwh_today, dumped_kwh_today, missed_deadline_pct, degraded_sites, audit: {ok, head, length}}
    (paused nodes count as online; tampered as offline; jobs also report paused and cancelled)."""
    core = _core()
    now = coord.clock()
    day, _ = _local_starts(coord, now)
    with coord.store.lock:
        db = coord.store.db
        nodes = {"online": 0, "suspect": 0, "offline": 0}
        for n in db.execute("SELECT * FROM nodes").fetchall():
            st = _node_state(n, now, site_paused(db, n["site_id"], now))
            nodes["online" if st in ("online", "paused") else "suspect" if st == "suspect" else "offline"] += 1
        jobs = {"queued": 0, "running": 0, "paused": 0, "done": 0, "failed": 0, "cancelled": 0}
        live, missed = 0, 0
        for j in db.execute("SELECT * FROM jobs").fetchall():
            v = _job_view(coord, db, j, now, False)
            jobs[v["status"]] += 1
            if v["status"] not in ("failed", "cancelled"):
                live += 1
                missed += v["missed_deadline"]
        leases = db.execute("SELECT COUNT(*) FROM leases WHERE state='active'").fetchone()[0]
        hd = db.execute("SELECT SUM(heat_kwh), SUM(dumped_kwh) FROM site_hourly WHERE hour_ts >= ?",
                        (int(day // 3600 * 3600),)).fetchone()
        degraded = [r["site_id"] for r in db.execute("SELECT site_id, received_at FROM sites ORDER BY site_id")
                    if now - float(r["received_at"]) > core.SIGNAL_MAX_AGE_S]
        head = db.execute("SELECT hash, idx FROM audit ORDER BY idx DESC LIMIT 1").fetchone()
    return {"nodes": nodes, "jobs": jobs, "leases_active": leases, "heat_used_kwh_today": round(hd[0] or 0.0, 6),
            "dumped_kwh_today": round(hd[1] or 0.0, 6),
            "missed_deadline_pct": round(100.0 * missed / live, 2) if live else 0.0, "degraded_sites": degraded,
            "audit": {"ok": coord.broker.verify_audit(), "head": head["hash"] if head else None,
                      "length": (head["idx"] + 1) if head else 0}}


def ops_nodes(coord, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    """Every node, newest registration first: node summary (as host_node) + classes, certified, drained."""
    now = coord.clock()
    with coord.store.lock:
        db = coord.store.db
        items = [_node_view(coord, db, n, now) for n in
                 db.execute("SELECT * FROM nodes ORDER BY registered_at DESC, node_id DESC").fetchall()]
    return _page(items, lambda x: x["node_id"], limit, cursor)


def ops_jobs(coord, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    """Every job (admin- and client-submitted), newest first; summaries plus client_id/customer_id."""
    return _jobs_page(coord, "1=1", (), limit, cursor,
                      extra=lambda j: {"client_id": j["client_id"], "customer_id": j["customer_id"]})


def ops_sites(coord, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    """Every site (with a signal or a node), as host_site."""
    now = coord.clock()
    with coord.store.lock:
        db = coord.store.db
        items = [_site_view(coord, db, s, now) for s in _all_sites(db, coord)]
    return _page(items, lambda x: x["site_id"], limit, cursor)


def drain_node(coord, node_id: str, drained: bool) -> dict[str, Any]:
    """drained=True: no new leases for the node; its running unit is paused on its next renew (final checkpoint,
    then another node resumes it). Idempotent, audited. {node_id, drained, changed}; unknown -> CoordError(404)."""
    with coord._tx() as db:
        n = db.execute("SELECT drained FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        if n is None:
            raise _err(404, "unknown node")
        changed = bool(n["drained"]) != bool(drained)
        if changed:
            db.execute("UPDATE nodes SET drained=? WHERE node_id=?", (int(bool(drained)), node_id))
            coord._audit(db, {"type": "node_drained" if drained else "node_undrained", "node": node_id})
    return {"node_id": node_id, "drained": bool(drained), "changed": changed}


def kill_node(coord, node_id: str) -> dict[str, Any]:
    """Revoke the node's leases NOW (demo 'pull the plug' without hardware): unit -> pending, the node's next
    renew/upload/complete -> 410. Idempotent. {node_id, revoked_lease: id|None, revoked: n}; unknown -> 404."""
    with coord._tx() as db:
        if db.execute("SELECT 1 FROM nodes WHERE node_id=?", (node_id,)).fetchone() is None:
            raise _err(404, "unknown node")
        ids = revoke_leases(db, coord, "node_id=? AND state IN ('active','paused')", (node_id,), "killed by operator")
        if ids:
            coord._audit(db, {"type": "node_killed", "node": node_id, "revoked": ids})
    return {"node_id": node_id, "revoked_lease": ids[0] if ids else None, "revoked": len(ids)}


def set_scenario(coord, site_id: str, replay: str) -> dict[str, Any]:
    """Write the site's demo scenario (coldest|july) to <state>/scenario/<site_id> (atomic); a sitesim started with
    --scenario-dir polls it and switches replay. No process is spawned from HTTP. {site_id, replay, changed}."""
    if replay not in SCENARIOS:
        raise _err(422, f"replay must be one of {list(SCENARIOS)}")
    if not ID_RE.match(site_id or ""):
        raise _err(422, "bad site id")
    with coord._tx() as db:
        if not _site_known(db, coord, site_id):
            raise _err(404, "unknown site")
        d = coord.dir / "scenario"
        f = d / site_id
        changed = (f.read_text().strip() if f.exists() else None) != replay
        if changed:
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f".{site_id}.tmp"
            tmp.write_text(replay + "\n")
            os.replace(tmp, f)
            coord._audit(db, {"type": "scenario", "site": site_id, "replay": replay})
    return {"site_id": site_id, "replay": replay, "changed": changed}


set_site_scenario = set_scenario  # P3's name (#85)


def audit_rows(coord, limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
    """{items: audit rows newest-first ({idx, hash, ...event}), next_cursor, verify: {ok, head, length}}"""
    n = _limit(limit)
    before = None
    if cursor:
        try:
            before = int(_dec(cursor))
        except ValueError:
            raise _err(422, "bad cursor") from None
    rows = coord.store.q("SELECT * FROM audit WHERE idx < ? ORDER BY idx DESC LIMIT ?",
                         before if before is not None else 1 << 62, n + 1)
    head = coord.store.one("SELECT hash, idx FROM audit ORDER BY idx DESC LIMIT 1")
    items = [json.loads(r["event"]) | {"idx": r["idx"], "hash": r["hash"]} for r in rows[:n]]
    return {"items": items, "next_cursor": _enc(str(rows[n - 1]["idx"])) if len(rows) > n else None,
            "verify": {"ok": coord.broker.verify_audit(), "head": head["hash"] if head else None,
                       "length": (head["idx"] + 1) if head else 0}}


ops_audit = audit_rows  # P3's name (#85)
