"""One-command live end-to-end check of the deployed system (#106).

    python -m tools.e2e --coordinator URL --site URL --client-token-file F --observer-token-file F
                        [--host-token-file F] [--client2-token-file F] [--admin-token-file F] [--only STEP,...]

Steps (PASS / FAIL / SKIP each, then a SUMMARY; exit 1 on any FAIL):
  surface    healthz; openapi lists client/host/ops/events; every website page (discovered from Nav) and every asset it
             references -> 200; /api/year/sizing, /api/year?n=1, /api/balance, /api/nodes -> 200
  roles      client -> ops 403, client -> host 403, host -> client 403; a second client sees the first one's job as 404
  client     catalogue -> submit 201 -> replay 200 (same job) -> same key + other params 409 -> events show progress ->
             done -> sha256(result) == X-Result-SHA256 == receipt.result_sha256, chunks 0..N-1 once
  cancel     submit -> DELETE -> cancelled; DELETE again idempotent; receipt 409
  host       site view, node view (each node at the site), history
  migrate    (admin) drain + kill the node running a unit mid-job -> it finishes on another node, byte-identical to an
             uninterrupted local jobs.runner run, every chunk exactly once
  pause      (admin) the running unit's site -> july: the site's signal drops to july demand within 10 s; the lease pauses
             within 10 s (by itself, or via the owner's pause with that site's host token: an empty tank still wants heat
             in july, so the scheduler rightly keeps charging it) -> coldest + resume -> leased again
  certified  (admin) a certified job runs only on certified nodes (default node-mac)
  audit      (admin) /v1/ops/audit verifies; /v1/ops/overview audit ok

Leaves the system as found: drained nodes are undrained, switched sites go back to coldest, unfinished jobs it
submitted are cancelled (finally block, also on Ctrl-C). Tokens are read from files and never printed.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote, unquote

import httpx

STEPS = ("surface", "roles", "client", "cancel", "host", "migrate", "pause", "certified", "audit")
ADMIN_STEPS = {"migrate", "pause", "certified", "audit"}


class StepFail(RuntimeError):
    pass


class Skip(RuntimeError):
    pass


@dataclass
class Config:
    coordinator: str
    site: str
    client_token: str
    observer_token: str
    host_token: str | None = None  # host flow + roles
    host_tokens: tuple[str, ...] = ()  # pause step: every host token available (picked by site)
    client2_token: str | None = None
    admin_token: str | None = None
    job_type: str = "image_tagging"
    chunks: int = 20
    rounds: int = 20_000  # client flow: small and fast
    rounds_long: int = 60_000  # migrate / pause: long enough to act mid-unit, short enough for < 5 min total
    certified_nodes: tuple[str, ...] = ("node-mac",)
    timeout_s: float = 180.0
    pause_within_s: float = 10.0
    self_pause_grace_s: float = 6.0  # pause step: wait this long for the july signal alone to pause the lease
    poll_s: float = 1.0
    transport: Any = None  # tests: an httpx transport instead of the network
    site_transport: Any = None
    tick: Callable[[], None] = lambda: None  # tests: advance a simulated node on every poll
    sleep: Callable[[float], None] = time.sleep
    reference: Callable[["Config", int], str] | None = None  # (cfg, rounds) -> sha of an uninterrupted run


def _ok(r: httpx.Response, *codes: int) -> httpx.Response:
    if r.status_code not in (codes or (200,)):
        raise StepFail(f"{r.request.method} {r.request.url.path} -> {r.status_code} {r.text[:200]}")
    return r


@dataclass
class E2E:
    cfg: Config
    out: Callable[[str], None] = print
    results: list[tuple[str, str, str, float]] = field(default_factory=list)
    _jobs: list[str] = field(default_factory=list)
    _drained: set = field(default_factory=set)
    _scenario: set = field(default_factory=set)
    _paused_hosts: list = field(default_factory=list)

    def __post_init__(self):
        c = self.cfg

        def cl(tok):
            kw = {"transport": c.transport} if c.transport is not None else {}
            return httpx.Client(base_url=c.coordinator.rstrip("/"), timeout=15.0,
                                headers={"Authorization": f"Bearer {tok}"} if tok else {}, **kw)
        self.client, self.obs = cl(c.client_token), cl(c.observer_token)
        self.anon = cl(None)
        self.host = cl(c.host_token) if c.host_token else None
        self.client2 = cl(c.client2_token) if c.client2_token else None
        self.admin = cl(c.admin_token) if c.admin_token else None
        kw = {"transport": c.site_transport} if c.site_transport is not None else {}
        self.web = httpx.Client(base_url=c.site.rstrip("/"), timeout=20.0, **kw)
        self.key = f"e2e-{int(time.time())}"

    # ------------------------------------------------------------------ helpers
    def wait(self, what: str, pred: Callable[[], Any], timeout: float | None = None) -> Any:
        t0 = time.monotonic()
        while True:
            self.cfg.tick()
            v = pred()
            if v:
                return v
            if time.monotonic() - t0 > (timeout or self.cfg.timeout_s):
                raise StepFail(f"timeout waiting for {what}")
            self.cfg.sleep(self.cfg.poll_s)

    @staticmethod
    def events_since(c: httpx.Client, after: int) -> tuple[list[dict], int]:
        """Every event visible to this token with id > after (the poll endpoint pages 200 at a time)."""
        out = []
        while True:
            d = _ok(c.get("/v1/events/poll", params={"after": after})).json()
            if not d["events"]:
                return out, after
            out += d["events"]
            after = int(d["last_id"])

    def head(self, c: httpx.Client) -> int:
        return self.events_since(c, 0)[1]

    def submit(self, tag: str, **kw) -> dict:
        body = {"type": self.cfg.job_type, "access_class": "public", "deadline_h": 24, "chunks": self.cfg.chunks,
                "rounds": self.cfg.rounds, "idempotency_key": f"{self.key}-{tag}", **kw}
        r = self.client.post("/v1/client/jobs", json=body)
        if r.status_code == 422:
            raise StepFail(f"submit rejected at admission: {r.json().get('reason', r.text[:200])}")
        _ok(r, 201)
        jid = r.json()["job_id"]
        self._jobs.append(jid)
        return {"job_id": jid, "body": body}

    def job(self, jid: str) -> dict:
        return _ok(self.client.get(f"/v1/client/jobs/{jid}")).json()

    def done(self, jid: str, timeout: float | None = None) -> dict:
        def pred():
            j = self.job(jid)
            if j["status"] in ("failed", "cancelled"):
                raise StepFail(f"job {jid} ended {j['status']}")
            return j if j["status"] == "done" else None
        return self.wait(f"job {jid} done", pred, timeout)

    def running_unit(self, jid: str, frac: float = 0.0, not_on: str | None = None):
        def pred():
            for u in self.job(jid)["units"]:
                if u["status"] == "running" and u["node_id"] and u["node_id"] != not_on \
                        and u["done_chunks"] >= frac * u["total_chunks"]:
                    return u
            return None
        return pred

    def ref_sha(self, rounds: int) -> str:
        if self.cfg.reference is not None:
            return self.cfg.reference(self.cfg, rounds)
        from .core import Config as DemoCfg, reference_sha
        return reference_sha(DemoCfg(job_type=self.cfg.job_type, chunks=self.cfg.chunks, rounds=rounds))

    def check_result(self, jid: str, ref: str | None = None) -> dict:
        r = _ok(self.client.get(f"/v1/client/jobs/{jid}/result"))
        body_sha, hdr = hashlib.sha256(r.content).hexdigest(), r.headers.get("x-result-sha256")
        rc = _ok(self.client.get(f"/v1/client/jobs/{jid}/receipt")).json()
        if not (body_sha == hdr == rc["result_sha256"]):
            raise StepFail(f"result sha mismatch: body {body_sha[:12]} header {str(hdr)[:12]} "
                           f"receipt {str(rc['result_sha256'])[:12]}")
        for unit, ids in rc["chunk_ids"].items():
            if sorted(ids) != list(range(self.cfg.chunks)) or len(set(ids)) != len(ids):
                raise StepFail(f"{unit}: chunks not exactly 0..{self.cfg.chunks - 1} once")
        if ref is not None:
            for u in rc["unit_results"]:
                if u["result_sha256"] != ref:
                    raise StepFail(f"{u['unit_id']} sha {u['result_sha256'][:12]} != uninterrupted run {ref[:12]}")
        return rc

    # ------------------------------------------------------------------ steps
    def step_surface(self) -> str:
        _ok(self.anon.get("/healthz"))
        paths = _ok(self.anon.get("/openapi.json")).json()["paths"]
        for p in ("/v1/client/", "/v1/host/", "/v1/ops/", "/v1/events"):
            if not any(k.startswith(p) for k in paths):
                raise StepFail(f"openapi has no {p}* route")
        nav = _ok(self.web.get("/Nav.dc.html")).text
        pages = sorted({unquote(m) for m in re.findall(r"DigitalHeat(?: |%20)[^\"'<>]+?\.dc\.html", nav)} | {"Nav.dc.html"})
        assets: set[str] = set()
        for pg in pages:
            html = _ok(self.web.get("/" + quote(pg))).text
            assets |= {a for a in re.findall(r"""(?:src|href)=["']\./([^"'#?]+)["']""", html)}
        css = _ok(self.web.get("/vendor/fonts/fonts.css")).text if "vendor/fonts/fonts.css" in assets else ""
        assets |= {"vendor/fonts/" + f for f in re.findall(r"url\(['\"]?([^'\")]+)", css)}
        bad = [a for a in sorted(assets) if not a.endswith(".dc.html") and self.web.get("/" + quote(a)).status_code != 200]
        if bad:
            raise StepFail(f"assets not 200: {bad[:5]}")
        for api in ("/api/year/sizing", "/api/year?n=1", "/api/balance", "/api/nodes"):
            _ok(self.web.get(api))
        return f"{len(pages)} pages, {len(assets)} assets, 4 APIs"

    def step_roles(self) -> str:
        _ok(self.client.get("/v1/ops/overview"), 403)
        _ok(self.client.get("/v1/host/site"), 403)
        notes = ["client->ops 403", "client->host 403"]
        if self.host:
            _ok(self.host.get("/v1/client/me"), 403)
            notes.append("host->client 403")
        if self.client2:
            mine = self._jobs[0] if self._jobs else self.submit("roles")["job_id"]
            _ok(self.client2.get(f"/v1/client/jobs/{mine}"), 404)
            notes.append("foreign job 404")
        return ", ".join(notes)

    def step_client(self) -> str:
        cat = _ok(self.client.get("/v1/client/catalogue")).json()
        if not any(c["type"] == self.cfg.job_type for c in cat):
            raise StepFail(f"{self.cfg.job_type} not in the catalogue")
        head = self.head(self.client)
        s = self.submit("client")
        jid = s["job_id"]
        r = _ok(self.client.post("/v1/client/jobs", json=s["body"]), 200)
        if r.json()["job_id"] != jid:
            raise StepFail("idempotent replay returned another job")
        _ok(self.client.post("/v1/client/jobs", json={**s["body"], "deadline_h": 23}), 409)
        self.done(jid)
        evs, _ = self.events_since(self.client, head)
        mine = [e for e in evs if e.get("job_id") == jid]
        kinds = {e["type"] for e in mine}
        if not {"lease.granted", "job.state"} <= kinds:
            raise StepFail(f"events for the job lack lease.granted/job.state: {sorted(kinds)}")
        rc = self.check_result(jid)
        return f"{jid} done on {rc['nodes_used']}, events {sorted(kinds)}, replay 200, mismatch 409, sha ok"

    def step_cancel(self) -> str:
        jid = self.submit("cancel")["job_id"]
        if _ok(self.client.delete(f"/v1/client/jobs/{jid}")).json()["status"] != "cancelled":
            raise StepFail("DELETE did not cancel")
        _ok(self.client.delete(f"/v1/client/jobs/{jid}"))
        _ok(self.client.get(f"/v1/client/jobs/{jid}/receipt"), 409)
        return f"{jid} cancelled, idempotent, receipt 409"

    def step_host(self) -> str:
        if not self.host:
            raise Skip("no --host-token-file")
        site = _ok(self.host.get("/v1/host/site")).json()
        for n in site["nodes"]:
            _ok(self.host.get(f"/v1/host/nodes/{n['node_id']}"))
        hist = _ok(self.host.get("/v1/host/history", params={"hours": 24})).json()
        return f"site {site['site_id']}: {len(site['nodes'])} nodes, {len(hist)} history hours, paused={site['paused']}"

    def _need_admin(self):
        if not self.admin:
            raise Skip("no --admin-token-file")

    def step_migrate(self) -> str:
        self._need_admin()
        nodes = _ok(self.admin.get("/v1/ops/nodes", params={"limit": 200})).json()["items"]
        live = [n["node_id"] for n in nodes if n["state"] == "online" and "public" in n["classes"]]
        if len(live) < 2:
            raise StepFail(f"need 2 online public nodes to migrate, have {live}")
        ref = self.ref_sha(self.cfg.rounds_long)
        jid = self.submit("migrate", rounds=self.cfg.rounds_long)["job_id"]
        u = self.wait("unit running at >= 20 %", self.running_unit(jid, 0.2))
        a = u["node_id"]
        _ok(self.admin.post(f"/v1/ops/nodes/{a}/drain"))
        self._drained.add(a)
        k = _ok(self.admin.post(f"/v1/ops/nodes/{a}/kill")).json()
        b = self.wait("unit resumed on another node", self.running_unit(jid, 0.0, not_on=a))["node_id"]
        self.done(jid)
        _ok(self.admin.post(f"/v1/ops/nodes/{a}/undrain"))
        self._drained.discard(a)
        rc = self.check_result(jid, ref)
        if not {a, b} <= set(rc["nodes_used"]):
            raise StepFail(f"receipt nodes_used {rc['nodes_used']} lacks {a} and {b}")
        return f"{a} drained+killed at {u['done_chunks']}/{u['total_chunks']} ({k['revoked']} lease), resumed on {b}, " \
               f"sha == uninterrupted {ref[:12]}"

    def _host_for(self, site: str):
        for tok in (self.cfg.host_token, *self.cfg.host_tokens):
            if not tok:
                continue
            kw = {"transport": self.cfg.transport} if self.cfg.transport is not None else {}
            c = httpx.Client(base_url=self.cfg.coordinator.rstrip("/"), timeout=15.0,
                             headers={"Authorization": f"Bearer {tok}"}, **kw)
            r = c.get("/v1/host/site")
            if r.status_code == 200 and r.json()["site_id"] == site:
                return c
        return None

    def step_pause(self) -> str:
        self._need_admin()
        jid = self.submit("pause", rounds=self.cfg.rounds_long)["job_id"]
        node = self.wait("unit running", self.running_unit(jid))["node_id"]
        site = next(n["site_id"] for n in _ok(self.admin.get("/v1/ops/nodes", params={"limit": 200})).json()["items"]
                    if n["node_id"] == node)

        def demand():
            s = next(x for x in _ok(self.admin.get("/v1/ops/sites", params={"limit": 200})).json()["items"]
                     if x["site_id"] == site)
            return s["demand_kw"], s["tank_level_kwh"]
        d0, _ = demand()
        head = self.head(self.admin)
        _ok(self.admin.post(f"/v1/ops/sites/{site}/scenario", json={"replay": "july"}))
        self._scenario.add(site)
        t0 = time.monotonic()
        d1, tank = self.wait(f"{site} signal at july demand", lambda: (lambda d: d if d[0] is not None and d[0] < d0
                                                                         else None)(demand()), self.cfg.pause_within_s)
        t_sig = time.monotonic() - t0

        def paused():
            evs, _ = self.events_since(self.admin, head)
            return next((e for e in evs if e["type"] == "lease.released" and e["data"].get("paused")
                         and e["data"].get("node") == node), None)
        how = "by itself"
        try:
            ev = self.wait(f"lease on {node} paused", paused, self.cfg.self_pause_grace_s)
        except StepFail:
            host = self._host_for(site)
            if host is None:
                raise StepFail(f"july reached {site} in {t_sig:.1f} s (demand {d0:.2f} -> {d1:.2f} kW) but the lease kept "
                               f"running (tank {tank:.1f} kWh: heat still wanted), and no host token for {site} to "
                               f"test the owner pause") from None
            t1 = time.monotonic()
            _ok(host.post("/v1/host/site/pause", json={}))
            self._paused_hosts.append(host)
            ev = self.wait(f"lease on {node} paused after the owner pause", paused, self.cfg.pause_within_s)
            how = f"by the owner's pause in {time.monotonic() - t1:.1f} s (tank {tank:.1f} kWh still wanted heat in july)"
            _ok(host.post("/v1/host/site/resume"))
            self._paused_hosts.remove(host)
        _ok(self.admin.post(f"/v1/ops/sites/{site}/scenario", json={"replay": "coldest"}))
        self._scenario.discard(site)
        self.wait("unit leased again after coldest/resume", self.running_unit(jid), 60)
        _ok(self.client.delete(f"/v1/client/jobs/{jid}"))
        return (f"{node}@{site}: july signal in {t_sig:.1f} s ({d0:.2f} -> {d1:.2f} kW); paused {how} "
                f"({ev['data'].get('reason')}); coldest -> running again")

    def step_certified(self) -> str:
        self._need_admin()
        jid = self.submit("certified", access_class="certified")["job_id"]
        self.done(jid)
        rc = self.check_result(jid)
        if not set(rc["nodes_used"]) <= set(self.cfg.certified_nodes):
            raise StepFail(f"certified job ran on {rc['nodes_used']} (allowed {list(self.cfg.certified_nodes)})")
        return f"{jid} ran only on {rc['nodes_used']}"

    def step_audit(self) -> str:
        self._need_admin()
        a = _ok(self.admin.get("/v1/ops/audit", params={"limit": 5})).json()["verify"]
        o = _ok(self.admin.get("/v1/ops/overview")).json()["audit"]
        if not (a["ok"] and o["ok"]):
            raise StepFail(f"audit does not verify: {a} / {o}")
        return f"audit verifies: {a['length']} entries, head {str(a['head'])[:12]}"

    # ------------------------------------------------------------------ run
    def cleanup(self) -> list[str]:
        done = []
        for n in sorted(self._drained):
            if self.admin and self.admin.post(f"/v1/ops/nodes/{n}/undrain").status_code == 200:
                done.append(f"undrained {n}")
        for h in self._paused_hosts:
            if h.post("/v1/host/site/resume").status_code == 200:
                done.append("owner pause lifted")
        for s in sorted(self._scenario):
            if self.admin and self.admin.post(f"/v1/ops/sites/{s}/scenario", json={"replay": "coldest"}).status_code == 200:
                done.append(f"{s} back to coldest")
        for j in self._jobs:
            try:
                st = self.client.get(f"/v1/client/jobs/{j}").json().get("status")
                if st in ("queued", "running", "paused") and self.client.delete(f"/v1/client/jobs/{j}").status_code == 200:
                    done.append(f"cancelled {j}")
            except Exception:  # noqa: BLE001 - best effort
                pass
        return done

    def run(self, steps: list[str] | None = None) -> bool:
        steps = steps or list(STEPS)
        try:
            for s in steps:
                t0 = time.monotonic()
                try:
                    msg, res = getattr(self, f"step_{s}")(), "PASS"
                except Skip as e:
                    msg, res = str(e), "SKIP"
                except StepFail as e:
                    msg, res = str(e), "FAIL"
                except httpx.HTTPError as e:
                    msg, res = f"{type(e).__name__}: {e}", "FAIL"
                dt = time.monotonic() - t0
                self.results.append((s, res, msg, dt))
                self.out(f"{res:4} {s:10} {dt:6.1f} s  {msg}")
        finally:
            for line in self.cleanup():
                self.out(f"     cleanup    {line}")
        total = sum(r[3] for r in self.results)
        counts = {k: sum(1 for r in self.results if r[1] == k) for k in ("PASS", "FAIL", "SKIP")}
        self.out(f"SUMMARY {counts['PASS']} pass, {counts['FAIL']} fail, {counts['SKIP']} skip in {total:.0f} s  "
                 + json.dumps({r[0]: r[1] for r in self.results}))
        return counts["FAIL"] == 0
