"""Coordinator logic (contracts/src/coordinator.md v1), independent of HTTP so tests can drive it directly.

Policy: one `scheduler.decide()` tick per lease request over all live nodes and the pending queue (imported,
never forked); admission via `scheduler.admit`; units via `jobs.arrivals.to_units`; keys and audit via
`trust.KeyBroker` (job keys and the audit hash chain are persisted, so a restart rebuilds the broker exactly).

Time: every method takes `now` from the injected clock. Lease timers freeze while the coordinator is down:
on start, leases are first lapsed as of the last moment the coordinator was alive (`meta.alive_at`), then
every still-active lease and node timer is shifted by the downtime.

Heat signals (v1.1): `POST /v1/sites/{site_id}/signal` stores the latest {demand_kw, tank_level_kwh, ts} per site
(table `sites`). Every decide() tick uses it for each node of that site; it wins over the legacy heartbeat
fields (kept for backward compatibility). Its age is measured on the coordinator's clock from receipt.
`status()["sites"]` reports per site the heat produced by the nodes holding active leases there
(server_kw_el x heat_recovery_fraction) as `heat_produced_kw`; `heat_used_kw` is the same number (all
recovered heat goes to the house/tank; the simulator clamps the tank at its capacity = dump).
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import math
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

import trust
from common.config import load_assumptions
from jobs.arrivals import Job, to_units
from jobs.runner import DEFAULT_ROUNDS as RUNNER_DEFAULT_ROUNDS
from jobs.catalogue import by_name, load_catalogue
from scheduler import Assign, Hold, Params, Route, SiteState, Unit, decide, heat_value_chf_kwh
from scheduler.admit import admit
from scheduler.policy import used_capacity_kwh_el

from .registry import load_registry, validate as validate_registry
from .store import Store

VERSION = "coordinator-v1"
# Protocol constants from the contract (not physical assumptions).
HEARTBEAT_S = 2.0
SUSPECT_S = 6.0
LEASE_S = 15.0
SIGNAL_MAX_AGE_S = 2 * HEARTBEAT_S  # "older than 2 ticks" -> degraded
MAX_CHUNKS, MAX_ROUNDS = 2000, 10_000_000  # bounds for JobIn.chunks / JobIn.rounds (v2.1 demo sizing)
CHUNKS_PER_UNIT = 20  # a unit (~15 min) is N runner chunks; completion must report exactly 0..N-1
HOLD_RETRY_S = 5.0
MIN_ROUND_S = 2e-6  # completion floor per runner round (F35): 10x below the fastest measured (M4: ~20.7 us/round)
MIN_PROGRESS_FOR_COMPLETE = 0.5  # or a heartbeat showing >= half the unit done on this node (F35)
REREGISTER_MIN_S = 10.0  # a CHANGED re-registration at most this often per node (F36)
REGION_KEY = "region"


class CoordError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _priv_bytes(k: X25519PrivateKey) -> bytes:
    return k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                           serialization.NoEncryption())


class Coordinator:
    def __init__(self, state_dir: Path, clock, assumptions: dict | None = None, registry: dict | None = None):
        self.dir = Path(state_dir)
        # v1.2: operator registry decides certification + class ceiling (missing file -> {} -> deny all)
        self.registry = validate_registry(registry) if registry is not None else load_registry(self.dir / "nodes.json")
        self.ckpt_dir = self.dir / "ckpt"
        self.clock = clock
        self.a = assumptions or load_assumptions()
        self.catalogue = by_name(load_catalogue(self.a))
        self.store = Store(self.dir / "state.db")
        self.broker = trust.KeyBroker()
        self._rebuild_broker()
        self._recover(self.clock())

    # ------------------------------------------------------------------ persistence of broker + audit
    def _rebuild_broker(self) -> None:
        entries = [trust.AuditEntry(r["idx"], json.loads(r["event"]), r["prev_hash"], r["hash"])
                   for r in self.store.q("SELECT * FROM audit ORDER BY idx")]
        self.broker.audit.entries = entries
        if not self.broker.audit.verify():
            raise RuntimeError("audit hash chain in state.db does not verify; refusing to start")
        for r in self.store.q("SELECT * FROM jobs WHERE admitted=1"):
            priv = X25519PrivateKey.from_private_bytes(r["priv_key"]) if r["priv_key"] else None
            self.broker._jobs[r["job_id"]] = trust._Job(r["customer_id"], r["access_class"], priv)
        for r in self.store.q("SELECT node_id FROM nodes WHERE tampered=1"):
            self.broker._tampered.add(r["node_id"])
        self.broker._published = None

    @contextmanager
    def _tx(self):
        try:
            with self.store.tx(commit_on=(CoordError,)) as db:
                yield db
        except CoordError:
            raise
        except BaseException:
            # rolled back: the in-memory broker may hold audit entries/keys that never reached disk
            self.broker = trust.KeyBroker()
            self._rebuild_broker()
            raise

    def _persist_audit(self, db) -> None:
        have = db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        for e in self.broker.audit.entries[have:]:
            db.execute("INSERT INTO audit(idx, event, prev_hash, hash) VALUES(?,?,?,?)",
                       (e.index, json.dumps(dict(e.event), sort_keys=True), e.prev_hash, e.hash))

    def _audit(self, db, event: dict) -> None:
        self.broker._log(event)
        self._persist_audit(db)

    def _touch(self, db, now: float) -> None:
        Store.meta_set(db, "alive_at", now)

    # ------------------------------------------------------------------ restart: timers frozen while down
    def _recover(self, now: float) -> None:
        raw = self.store.meta_get("alive_at")
        with self._tx() as db:
            if raw is not None:
                alive_at = float(raw)
                self._expire(db, alive_at)  # what had lapsed before we went down stays lapsed
                down = max(0.0, now - alive_at)
                if down > 0:
                    db.execute("UPDATE leases SET expires_at = expires_at + ? WHERE state='active'", (down,))
                    db.execute("UPDATE nodes SET last_hb = last_hb + ?, signal_at = signal_at + ?", (down, down))
                    db.execute("UPDATE sites SET received_at = received_at + ?", (down,))
                    self._audit(db, {"type": "coordinator_restart", "downtime_s": round(down, 3)})
            self._touch(db, now)

    def tick(self) -> None:
        """Server-mode heartbeat of the coordinator itself (keeps alive_at fresh, lapses expired leases)."""
        now = self.clock()
        with self._tx() as db:
            self._expire(db, now)
            self._touch(db, now)

    # ------------------------------------------------------------------ helpers
    def _expire(self, db, now: float) -> None:
        # a paused lease no longer holds its unit (already pending); it only lapses its final-upload window
        db.execute("UPDATE leases SET state='lapsed' WHERE state='paused' AND expires_at <= ?", (now,))
        for r in db.execute("SELECT lease_id, unit_id, node_id FROM leases WHERE state='active' AND expires_at <= ?",
                            (now,)).fetchall():
            db.execute("UPDATE leases SET state='lapsed' WHERE lease_id=?", (r["lease_id"],))
            db.execute("UPDATE units SET state='pending' WHERE unit_id=? AND state='leased'", (r["unit_id"],))
            self._audit(db, {"type": "lease_lapsed", "lease": r["lease_id"], "unit": r["unit_id"], "node": r["node_id"]})

    def _hour(self, now: float) -> int:
        tz = ZoneInfo(self.a["location"]["tz"])
        t = datetime.fromtimestamp(now, tz)
        start = datetime(t.year, 1, 1, tzinfo=tz)
        return int((now - start.timestamp()) // 3600)

    def _year_start(self, now: float) -> datetime:
        tz = ZoneInfo(self.a["location"]["tz"])
        return datetime(datetime.fromtimestamp(now, tz).year, 1, 1, tzinfo=tz)

    def _degraded(self, n, now: float) -> bool:
        return n["signal_at"] is None or now - n["signal_at"] > SIGNAL_MAX_AGE_S

    def _site(self, n, hour: int) -> SiteState:
        a, h, s = self.a, self.a["house"], self.a["scheduler"]
        p, div = float(a["price"]["chf_per_kwh"]), float(a["price"]["heat_value_divisor"])
        cap = float(h["tank_kwh"])
        demand = max(0.0, float(n["demand_kw"] or 0.0))  # persistence: last value reported
        tank = min(max(0.0, float(n["tank_level_kwh"] or 0.0)), cap)
        return SiteState(n["node_id"], hour, demand, tank, cap, 1, float(n["server_kw_el"]),
                         float(a["server"]["heat_recovery_fraction"]), p,
                         heat_value_chf_kwh(p, div, demand, tank, float(s["tank_band_high_kwh"])),
                         frozenset(json.loads(n["eligible_classes"])), None, False,
                         float(s["tank_band_low_kwh"]), float(s["tank_band_high_kwh"]), bool(n["mode_running"]))

    @staticmethod
    def _unit(r) -> Unit:
        return Unit(r["unit_id"], r["job_id"], r["job_class"], r["access_class"], r["kwh_el"], r["bid"],
                    r["deadline_hour"], r["slack_h"], bool(r["checkpointable"]))

    @staticmethod
    def _with_signal(db, n) -> dict | None:
        """The node row with its site's latest signal. F33: heartbeat heat fields never drive scheduling; a site
        without a signal row has no heat data (degraded: persistence/no-dump rules)."""
        if n is None:
            return None
        d = dict(n)
        d.update(demand_kw=None, tank_level_kwh=None, signal_at=None)
        s = db.execute("SELECT * FROM sites WHERE site_id=?", (d["site_id"],)).fetchone()
        if s is not None:
            d.update(demand_kw=s["demand_kw"], tank_level_kwh=s["tank_level_kwh"], signal_at=s["received_at"])
        return d

    def _node(self, db, node_id: str):
        n = self._with_signal(db, db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone())
        if n is None:
            raise CoordError(404, "node not registered")
        return n

    def _attestation(self, n) -> trust.Attestation:
        d = json.loads(n["attestation"])
        return trust.Attestation(d["node_id"], d["evidence"], base64.b64decode(d["signature_b64"]))

    def _release(self, job_id: str, node_id: str, att: trust.Attestation, region: str):
        """KeyBroker.release, plus the v1.2 rule: a certified job's key only goes to a registry-certified node
        (the broker alone would trust the self-reported evidence flag)."""
        job = self.broker._jobs.get(job_id)
        reg = self.registry.get(node_id)
        if job is not None and job.access_class == "certified" and not (reg and reg["certified"]):
            self.broker._log({"type": "deny", "job": job_id, "node": node_id, "region": region,
                              "attestation": "mock", "reason": "not_certified_in_registry"})
            return trust.Denied("not_certified_in_registry", job_id, node_id)
        return self.broker.release(job_id, node_id, att, region)

    def _live(self, db, now: float, requester: str):
        return [self._with_signal(db, n)
                for n in db.execute("SELECT * FROM nodes WHERE tampered=0 ORDER BY node_id").fetchall()
                if n["node_id"] == requester or now - n["last_hb"] <= SUSPECT_S]

    # ------------------------------------------------------------------ site signals (v1.1)
    def site_signal(self, site_id: str, demand_kw: float, tank_level_kwh: float, ts: float) -> dict:
        now = self.clock()
        cap = float(self.a["house"]["tank_kwh"])
        if tank_level_kwh > cap + 1e-9:
            raise CoordError(422, f"tank_level_kwh must be <= the tank capacity {cap}")
        with self._tx() as db:
            self._touch(db, now)
            self._expire(db, now)
            db.execute("""INSERT INTO sites(site_id, demand_kw, tank_level_kwh, ts, received_at) VALUES(?,?,?,?,?)
                          ON CONFLICT(site_id) DO UPDATE SET demand_kw=excluded.demand_kw,
                          tank_level_kwh=excluded.tank_level_kwh, ts=excluded.ts, received_at=excluded.received_at""",
                       (site_id, float(demand_kw), float(tank_level_kwh), float(ts), now))
            heat = self._site_heat(db).get(site_id, 0.0)
        return {"ok": True, "site_id": site_id, "heat_produced_kw": heat, "heat_used_kw": heat}

    def _site_heat(self, db) -> dict[str, float]:
        frac = float(self.a["server"]["heat_recovery_fraction"])
        out: dict[str, float] = {}
        for r in db.execute("""SELECT n.site_id, n.server_kw_el FROM leases l JOIN nodes n ON n.node_id = l.node_id
                               WHERE l.state='active'""").fetchall():
            out[r["site_id"]] = round(out.get(r["site_id"], 0.0) + float(r["server_kw_el"]) * frac, 6)
        return out

    # ------------------------------------------------------------------ nodes
    def register(self, node_id: str, site_id: str, eligible: list[str], kw: float, att: dict) -> dict:
        now = self.clock()
        attestation = trust.Attestation(att["node_id"], att["evidence"], base64.b64decode(att["signature_b64"]))
        ok = (attestation.node_id == node_id and attestation.is_valid()
              and attestation.evidence.get("measurement") in self.broker.expected_measurements
              and isinstance(attestation.evidence.get(REGION_KEY), str))
        reg = self.registry.get(node_id)
        with self._tx() as db:
            self._touch(db, now)
            if reg is None:
                self._audit(db, {"type": "register_denied", "node": node_id, "reason": "not_in_registry"})
                raise CoordError(403, "node not in registry")
            if site_id != reg["site_id"]:
                self._audit(db, {"type": "register_denied", "node": node_id, "reason": "site_not_in_registry"})
                raise CoordError(403, "site not in registry for this node")
            if not ok:
                self._audit(db, {"type": "register_denied", "node": node_id, "attestation": "mock"})
                raise CoordError(403, "attestation rejected")
            region = attestation.evidence[REGION_KEY]
            # registry ceiling first (#69): never more classes than the operator allows; certified only if registered so
            ceiling = set(reg["max_classes"])
            claim_rejected = False
            if not reg["certified"]:
                ceiling.discard("certified")
                claim_rejected = attestation.evidence.get("certified") is True
            eligible = [c for c in eligible if c in ceiling]
            classes = json.dumps(sorted(set(eligible)))
            old = db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
            if eligible and old is not None and (old["site_id"], old["eligible_classes"], float(old["server_kw_el"]),
                                                 old["attestation"], old["region"]) == (site_id, classes, float(kw),
                                                                                       json.dumps(att), region):
                # identical re-register: idempotent, no audit entry (F36, #71)
                db.execute("UPDATE nodes SET last_hb=? WHERE node_id=?", (now, node_id))
                return {"ok": True, "node_id": node_id, "eligible_classes": sorted(set(eligible)),
                        "certified": bool(reg["certified"]), "heartbeat_s": HEARTBEAT_S, "lease_s": LEASE_S,
                        "unchanged": True}
            if claim_rejected:
                self._audit(db, {"type": "certified_claim_rejected", "node": node_id})
            if not eligible:
                self._audit(db, {"type": "register_denied", "node": node_id, "reason": "no_allowed_classes"})
                raise CoordError(403, "no requested class is allowed for this node by the registry")
            if old is not None and now - float(old["registered_at"]) < REREGISTER_MIN_S:
                raise CoordError(429, f"registration changed too often; retry in {REREGISTER_MIN_S:g} s")
            db.execute("""INSERT INTO nodes(node_id, site_id, eligible_classes, server_kw_el, attestation, region,
                          registered_at, last_hb) VALUES(?,?,?,?,?,?,?,?)
                          ON CONFLICT(node_id) DO UPDATE SET site_id=excluded.site_id,
                          eligible_classes=excluded.eligible_classes, server_kw_el=excluded.server_kw_el,
                          attestation=excluded.attestation, region=excluded.region, last_hb=excluded.last_hb,
                          registered_at=excluded.registered_at""",
                       (node_id, site_id, classes, kw, json.dumps(att), region, now, now))
            self._audit(db, {"type": "register_node", "node": node_id, "site": site_id, "region": region,
                             "attestation": "mock", "classes": sorted(set(eligible)),
                             "certified": bool(reg["certified"])})
        return {"ok": True, "node_id": node_id, "eligible_classes": sorted(set(eligible)),
                "certified": bool(reg["certified"]), "heartbeat_s": HEARTBEAT_S, "lease_s": LEASE_S}

    def heartbeat(self, node_id: str, hb: dict) -> dict:
        now = self.clock()
        with self._tx() as db:
            self._touch(db, now)
            self._expire(db, now)
            self._node(db, node_id)
            sets = {"last_hb": now, "watts": hb.get("watts"), "running_unit": hb.get("running_unit"),
                    "progress": hb.get("progress"), "last_error": hb.get("last_error")}
            if hb.get("tank_level_kwh") is not None or hb.get("demand_kw") is not None:
                sets.update(tank_level_kwh=hb.get("tank_level_kwh"), demand_kw=hb.get("demand_kw"), signal_at=now)
            db.execute(f"UPDATE nodes SET {', '.join(k + '=?' for k in sets)} WHERE node_id=?",
                       (*sets.values(), node_id))
            n = self._node(db, node_id)
        return {"ok": True, "degraded": self._degraded(n, now)}

    # ------------------------------------------------------------------ leases
    def lease(self, node_id: str) -> dict:
        now = self.clock()
        with self._tx() as db:
            self._touch(db, now)
            self._expire(db, now)
            me = self._node(db, node_id)
            if me["tampered"]:
                self._audit(db, {"type": "lease_refused", "node": node_id, "reason": "node_tampered"})
                return {"hold": True, "reason": "key denied: node_tampered", "retry_after_s": HOLD_RETRY_S}
            cur = db.execute("SELECT * FROM leases WHERE node_id=? AND state='active'", (node_id,)).fetchone()
            if cur is not None:  # one unit at a time per node: re-asking returns the same lease (idempotent)
                return self._lease_payload(db, cur, now, self._degraded(me, now), key=None)
            queue = [self._unit(r) for r in db.execute("SELECT * FROM units WHERE state='pending'").fetchall()]
            if not queue:
                return {"hold": True, "reason": "no work", "retry_after_s": HOLD_RETRY_S}
            hour = self._hour(now)
            live = self._live(db, now, node_id)
            degraded = self._degraded(me, now)
            params = Params.from_assumptions(self.a, policy="merit", slack_enabled=not degraded)
            dec = decide([self._site(n, hour) for n in live], queue, hour, params)
            for sid, mode in dec.next_mode.items():
                db.execute("UPDATE nodes SET mode_running=? WHERE node_id=?", (int(mode), sid))
            mine = [x.unit_id for x in dec.actions if isinstance(x, Assign) and x.site_id == node_id]
            if not mine:
                held = [x.reason for x in dec.actions if isinstance(x, Hold)]
                return {"hold": True, "reason": held[0] if held else "work assigned to other nodes",
                        "retry_after_s": HOLD_RETRY_S, "degraded": degraded}
            if degraded:
                r = next(x for x in dec.actions if isinstance(x, Route) and x.site_id == node_id)
                if r.dump_kwh > 0 and r.space_kwh + r.dhw_kwh + r.tank_kwh <= 1e-9:
                    return {"hold": True, "reason": "degraded: no dump-only work on stale heat data",
                            "retry_after_s": HOLD_RETRY_S, "degraded": True}
            u = db.execute("SELECT * FROM units WHERE unit_id=?", (mine[0],)).fetchone()
            rel = self._release(u["job_id"], node_id, self._attestation(me), me["region"])
            self._persist_audit(db)
            if isinstance(rel, trust.Denied):
                return {"hold": True, "reason": f"key denied: {rel.reason}", "retry_after_s": HOLD_RETRY_S,
                        "degraded": degraded}
            lease_id = "l-" + secrets.token_hex(8)
            db.execute("INSERT INTO leases VALUES(?,?,?,?,?,?)",
                       (lease_id, u["unit_id"], node_id, "active", now, now + LEASE_S))
            db.execute("UPDATE units SET state='leased' WHERE unit_id=?", (u["unit_id"],))
            self._audit(db, {"type": "lease", "lease": lease_id, "unit": u["unit_id"], "node": node_id,
                             "degraded": degraded})
            cur = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
            return self._lease_payload(db, cur, now, degraded, key=rel)

    def _lease_payload(self, db, lease, now: float, degraded: bool, key) -> dict:
        u = db.execute("SELECT * FROM units WHERE unit_id=?", (lease["unit_id"],)).fetchone()
        has_ckpt = db.execute("SELECT 1 FROM checkpoints WHERE unit_id=? LIMIT 1", (u["unit_id"],)).fetchone()
        if key is None:  # re-issued lease: release again (audited) so the node can re-open checkpoints
            n = self._node(db, lease["node_id"])
            key = self._release(u["job_id"], lease["node_id"], self._attestation(n), n["region"])
            self._persist_audit(db)
            if isinstance(key, trust.Denied):
                return {"hold": True, "reason": f"key denied: {key.reason}", "retry_after_s": HOLD_RETRY_S}
        unit = {"unit_id": u["unit_id"], "job_id": u["job_id"], "job_type": u["job_class"],
                "access_class": u["access_class"], "chunks": u["chunks"], "kwh_el": u["kwh_el"],
                "deadline_hour": u["deadline_hour"]}
        if u["rounds"] is not None:
            unit["rounds"] = u["rounds"]
        return {"unit": unit,
                "lease_id": lease["lease_id"], "expires_in_s": round(lease["expires_at"] - now, 3),
                "renew_every_s": LEASE_S / 3,
                "checkpoint_url": f"/v1/checkpoints/{u['unit_id']}/latest" if has_ckpt else None,
                "key_release": {"job_id": u["job_id"], "key_b64": _b64(_priv_bytes(key.key)), "mock": True},
                "degraded": degraded}

    def _owned_lease(self, db, lease_id: str, node_id: str):
        lz = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
        if lz is None:
            raise CoordError(404, "unknown lease")
        if lz["node_id"] != node_id:
            raise CoordError(403, "lease belongs to another node")
        return lz

    def renew(self, node_id: str, lease_id: str) -> dict:
        """Extend the lease, unless the heat signal says this unit should stop on this node now.

        Each renewal re-runs the policy for this unit on this node's own site (same decide(), imported). If it
        is held (no heat wanted / site idle / bid below MC) and not deadline-forced, the lease is PAUSED: the
        reply is {hold}, the unit returns to pending at once (another node with heat demand can lease it:
        migration = lease end + reassign), and the paused lease accepts ONE final checkpoint upload within
        LEASE_S before it is released. Renew/complete on a paused or released lease -> 410."""
        now = self.clock()
        with self._tx() as db:
            self._touch(db, now)
            self._expire(db, now)
            lz = self._owned_lease(db, lease_id, node_id)
            if lz["state"] != "active":
                raise CoordError(410, f"lease {lz['state']}: stop and discard local work")
            me = self._node(db, node_id)
            u = db.execute("SELECT * FROM units WHERE unit_id=?", (lz["unit_id"],)).fetchone()
            hour = self._hour(now)
            degraded = self._degraded(me, now)
            params = Params.from_assumptions(self.a, policy="merit", slack_enabled=not degraded)
            dec = decide([self._site(me, hour)], [self._unit(u)], hour, params)
            db.execute("UPDATE nodes SET mode_running=? WHERE node_id=?", (int(dec.next_mode[node_id]), node_id))
            held = next((x for x in dec.actions if isinstance(x, Hold) and x.unit_id == u["unit_id"]), None)
            if held is None and degraded:
                r = next(x for x in dec.actions if isinstance(x, Route) and x.site_id == node_id)
                if r.dump_kwh > 0 and r.space_kwh + r.dhw_kwh + r.tank_kwh <= 1e-9:
                    held = Hold(u["unit_id"], "degraded: no dump-only work on stale heat data")
            if held is not None:
                db.execute("UPDATE leases SET state='paused', expires_at=? WHERE lease_id=?", (now + LEASE_S, lease_id))
                db.execute("UPDATE units SET state='pending' WHERE unit_id=? AND state='leased'", (u["unit_id"],))
                self._audit(db, {"type": "lease_paused", "lease": lease_id, "unit": u["unit_id"], "node": node_id,
                                 "reason": held.reason, "degraded": degraded})
                return {"hold": True, "reason": held.reason, "retry_after_s": HOLD_RETRY_S,
                        "final_checkpoint_within_s": LEASE_S, "degraded": degraded}
            db.execute("UPDATE leases SET expires_at=? WHERE lease_id=?", (now + LEASE_S, lease_id))
        return {"ok": True, "expires_in_s": LEASE_S}

    def checkpoint(self, node_id: str, lease_id: str, body: bytes, next_chunk: int, out_bytes: int,
                   sha256: str) -> dict:
        now = self.clock()
        if hashlib.sha256(body).hexdigest() != sha256:
            raise CoordError(422, "sha256 does not match the uploaded bytes")
        with self._tx() as db:
            self._touch(db, now)
            self._expire(db, now)
            lz = self._owned_lease(db, lease_id, node_id)
            if lz["state"] not in ("active", "paused"):
                raise CoordError(410, f"lease {lz['state']}")
            u = db.execute("SELECT chunks, state FROM units WHERE unit_id=?", (lz["unit_id"],)).fetchone()
            if lz["state"] == "paused" and u["state"] != "pending":
                raise CoordError(410, "unit already re-leased; final checkpoint no longer accepted")
            if not 0 <= next_chunk <= u["chunks"]:
                raise CoordError(422, f"next_chunk must be in [0, {u['chunks']}]")
            seq = (db.execute("SELECT MAX(seq) FROM checkpoints WHERE unit_id=?", (lz["unit_id"],)).fetchone()[0]
                   or 0) + 1
            d = self.ckpt_dir / lz["unit_id"]  # unit ids are generated here and match [a-z0-9-]
            d.mkdir(parents=True, exist_ok=True)
            final, tmp = d / str(seq), d / f".{seq}.tmp"
            with open(tmp, "wb") as f:
                f.write(body)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, final)
            db.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?,?,?,?)",
                       (lz["unit_id"], seq, next_chunk, out_bytes, sha256, str(final.relative_to(self.dir)),
                        node_id, now))
            if lz["state"] == "paused":  # the one final checkpoint after a pause
                db.execute("UPDATE leases SET state='released' WHERE lease_id=?", (lease_id,))
                self._audit(db, {"type": "lease_released", "lease": lease_id, "unit": lz["unit_id"], "node": node_id,
                                 "next_chunk": next_chunk})
        return {"ok": True, "seq": seq}

    def latest_checkpoint(self, node_id: str, unit_id: str) -> tuple[bytes, dict]:
        now = self.clock()
        with self._tx() as db:
            self._touch(db, now)
            self._expire(db, now)
            held = db.execute("SELECT 1 FROM leases WHERE unit_id=? AND node_id=? AND state='active'",
                              (unit_id, node_id)).fetchone()
            if held is None:
                raise CoordError(403, "only the current lease holder may read this checkpoint")
            c = db.execute("SELECT * FROM checkpoints WHERE unit_id=? ORDER BY seq DESC LIMIT 1",
                           (unit_id,)).fetchone()
            if c is None:
                raise CoordError(404, "no checkpoint yet")
            data = (self.dir / c["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != c["sha256"]:
            raise CoordError(500, "stored checkpoint failed its integrity check")
        return data, {"x-next-chunk": str(c["next_chunk"]), "x-out-bytes": str(c["out_bytes"]),
                      "x-sha256": c["sha256"], "x-seq": str(c["seq"])}

    def complete(self, node_id: str, lease_id: str, result_sha256: str, chunk_ids: list[int]) -> dict:
        now = self.clock()
        with self._tx() as db:
            self._touch(db, now)
            self._expire(db, now)
            lz = self._owned_lease(db, lease_id, node_id)
            u = db.execute("SELECT * FROM units WHERE unit_id=?", (lz["unit_id"],)).fetchone()
            if u["state"] == "done":  # idempotent and content-addressed
                if u["result_sha256"] == result_sha256:
                    return {"ok": True, "duplicate": True, "unit_id": u["unit_id"]}
                self._audit(db, {"type": "complete_conflict", "unit": u["unit_id"], "node": node_id,
                                 "have": u["result_sha256"], "got": result_sha256})
                raise CoordError(409, "conflicting result for an already completed unit")
            if lz["state"] != "active":
                raise CoordError(410, f"lease {lz['state']}: another node owns this unit now")
            if sorted(chunk_ids) != list(range(u["chunks"])) or len(set(chunk_ids)) != len(chunk_ids):
                raise CoordError(422, f"chunk_ids must be exactly 0..{u['chunks'] - 1}, each once")
            # plausibility (F35): evidence of work (a checkpoint for this unit, or this node reporting >= half of it
            # done) and no faster than the unit's chunks could possibly run since it was first leased
            first = db.execute("SELECT MIN(issued_at) FROM leases WHERE unit_id=?", (u["unit_id"],)).fetchone()[0]
            ckpt = db.execute("SELECT 1 FROM checkpoints WHERE unit_id=? LIMIT 1", (u["unit_id"],)).fetchone()
            me = db.execute("SELECT running_unit, progress FROM nodes WHERE node_id=?", (node_id,)).fetchone()
            progressed = me is not None and me["running_unit"] == u["unit_id"] and \
                (me["progress"] or 0.0) >= MIN_PROGRESS_FOR_COMPLETE
            floor = u["chunks"] * (u["rounds"] or RUNNER_DEFAULT_ROUNDS) * MIN_ROUND_S
            if not (ckpt or progressed) or now - float(first) < floor:
                self._audit(db, {"type": "complete_implausible", "unit": u["unit_id"], "node": node_id,
                                 "elapsed_s": round(now - float(first), 3), "checkpoint": bool(ckpt),
                                 "progress": me["progress"] if me is not None else None})
                raise CoordError(422, f"completion without evidence of work: need a checkpoint or progress >= "
                                      f"{MIN_PROGRESS_FOR_COMPLETE:g}, and >= {floor:g} s since the first lease")
            db.execute("""UPDATE units SET state='done', result_sha256=?, done_chunks=?, completed_at=?, completed_by=?
                          WHERE unit_id=?""", (result_sha256, json.dumps(sorted(chunk_ids)), now, node_id, u["unit_id"]))
            db.execute("UPDATE leases SET state='completed' WHERE lease_id=?", (lease_id,))
            self._audit(db, {"type": "complete", "unit": u["unit_id"], "node": node_id, "result": result_sha256})
        return {"ok": True, "duplicate": False, "unit_id": u["unit_id"]}

    # ------------------------------------------------------------------ admin / observer
    def submit_job(self, job_type: str, customer_id: str, access_class: str | None, deadline_h: float | None,
                   force: bool, rounds: int | None = None, chunks: int | None = None) -> dict:
        now = self.clock()
        if chunks is not None and not 1 <= chunks <= MAX_CHUNKS:
            raise CoordError(422, f"chunks must be in [1, {MAX_CHUNKS}]")
        if rounds is not None and not 1 <= rounds <= MAX_ROUNDS:
            raise CoordError(422, f"rounds must be in [1, {MAX_ROUNDS}]")
        if job_type not in self.catalogue:
            raise CoordError(422, f"unknown job_type; one of {sorted(self.catalogue)}")
        jt = self.catalogue[job_type]
        if access_class is not None:
            jt = dataclasses.replace(jt, access_class=access_class)
        if deadline_h is not None:
            if deadline_h < jt.runtime_h:
                raise CoordError(422, f"deadline_h must be >= runtime_h {jt.runtime_h}")
            jt = dataclasses.replace(jt, deadline_h=float(deadline_h))
        job_id = "job-" + secrets.token_hex(6)
        start = self._year_start(now)
        job = Job(job_id, jt, datetime.fromtimestamp(now, timezone.utc), jt.runtime_h)
        units = [dataclasses.replace(u, unit_id=f"{job_id}-u{i:03d}")
                 for i, u in enumerate(to_units(job, start, self.a["scheduler"]["unit_minutes"],
                                                self.a["server"]["electric_kw"]))]
        hour = self._hour(now)
        with self._tx() as db:
            self._touch(db, now)
            live = self._live(db, now, "")
            sites = [self._site(n, hour) for n in live]
            if force:
                ok, reason = True, "admitted (forced by admin)"
            elif not sites:
                ok, reason = False, "no live node"
            else:
                horizon = max(1, units[0].deadline_hour - hour + 1)
                fc = {s.site_id: [used_capacity_kwh_el(s)] * horizon for s in sites}  # persistence of now
                adm = admit(units, sites, hour, fc, Params.from_assumptions(self.a))
                ok, reason = adm.accepted, adm.reason
            pub = None
            if ok:
                pub = self.broker.register_job(job_id, customer_id, jt.access_class)
                priv = _priv_bytes(self.broker._jobs[job_id].priv)
            else:
                priv = None
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                       (job_id, job_type, jt.access_class, customer_id, units[0].deadline_hour, priv, now, int(ok),
                        reason))
            if ok:
                for i, u in enumerate(units):
                    db.execute("""INSERT INTO units(unit_id, job_id, seq, job_class, access_class, kwh_el, bid,
                                  deadline_hour, slack_h, checkpointable, chunks, state, rounds)
                                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                               (u.unit_id, job_id, i, u.job_class, u.access_class, u.kwh_el, u.bid_chf_per_server_h,
                                u.deadline_hour, u.slack_h, int(u.checkpointable), chunks or CHUNKS_PER_UNIT,
                                "pending", rounds))
            self._audit(db, {"type": "submit", "job": job_id, "admitted": ok, "reason": reason, "units": len(units)})
            self._persist_audit(db)
        out = {"job_id": job_id, "admitted": ok, "reason": reason, "units": len(units) if ok else 0}
        if pub is not None:
            out["job_public_key_b64"] = _b64(pub.public_bytes(serialization.Encoding.Raw,
                                                              serialization.PublicFormat.Raw))
        return out

    def tamper(self, node_id: str) -> dict:
        now = self.clock()
        with self._tx() as db:
            self._touch(db, now)
            self._node(db, node_id)
            self.broker.tamper(node_id)
            db.execute("UPDATE nodes SET tampered=1 WHERE node_id=?", (node_id,))
            revoked = 0
            for lz in db.execute("SELECT lease_id, unit_id FROM leases WHERE node_id=? AND state='active'",
                                 (node_id,)).fetchall():
                db.execute("UPDATE leases SET state='revoked' WHERE lease_id=?", (lz["lease_id"],))
                db.execute("UPDATE units SET state='pending' WHERE unit_id=? AND state='leased'", (lz["unit_id"],))
                revoked += 1
            self._persist_audit(db)
            self._audit(db, {"type": "leases_revoked", "node": node_id, "count": revoked})
        return {"ok": True, "revoked": revoked}

    def status(self) -> dict:
        now = self.clock()
        with self._tx() as db:
            self._touch(db, now)
            self._expire(db, now)
            nodes = [{"node_id": n["node_id"], "site_id": n["site_id"], "region": n["region"],
                      "suspect": now - n["last_hb"] > SUSPECT_S, "degraded": self._degraded(n, now),
                      "tampered": bool(n["tampered"]), "watts": n["watts"], "running_unit": n["running_unit"],
                      "progress": n["progress"], "mode_running": bool(n["mode_running"]),
                      "last_error": n["last_error"]}
                     for n in (self._with_signal(db, r) for r in db.execute("SELECT * FROM nodes ORDER BY node_id"))]
            heat = self._site_heat(db)
            sites = [{"site_id": r["site_id"], "demand_kw": r["demand_kw"], "tank_level_kwh": r["tank_level_kwh"],
                      "ts": r["ts"], "age_s": round(now - r["received_at"], 3),
                      "degraded": now - r["received_at"] > SIGNAL_MAX_AGE_S,
                      "heat_produced_kw": heat.get(r["site_id"], 0.0), "heat_used_kw": heat.get(r["site_id"], 0.0)}
                     for r in db.execute("SELECT * FROM sites ORDER BY site_id")]
            leases = [dict(r) | {"expires_in_s": round(r["expires_at"] - now, 3)}
                      for r in db.execute("SELECT lease_id, unit_id, node_id, expires_at FROM leases "
                                          "WHERE state='active' ORDER BY issued_at")]
            for lz in leases:
                lz.pop("expires_at")
            queue = {r["state"]: r["c"] for r in db.execute("SELECT state, COUNT(*) c FROM units GROUP BY state")}
            audit = [json.loads(r["event"]) | {"idx": r["idx"]}
                     for r in db.execute("SELECT idx, event FROM audit ORDER BY idx DESC LIMIT 20")]
        return {"version": VERSION, "nodes": nodes, "sites": sites, "leases": leases, "queue": queue, "recent_audit": audit,
                "audit_verifies": self.broker.verify_audit(), "degraded": [n["node_id"] for n in nodes if n["degraded"]]}
