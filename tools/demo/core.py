"""Demo rehearsal steps (#77). Only the coordinator HTTP API plus configurable shell commands touch the world.

Every step prints a timeline (t+Ns) and ends with a PASS/FAIL line, and restores what it changed in `finally`:
- migrate: steer a job onto node-omen2, kill its agent at ~30 % progress, node-mac resumes from the checkpoint;
  the result sha must equal a local reference run of jobs.runner (completion requires every chunk once).
- pause: a job runs on node-mac, its site signal switches to July -> the lease is paused within 6 s -> back to
  January -> the unit resumes (from the final checkpoint) and completes.
- tamper: a THROWAWAY node is tampered -> its lease request gets "key denied: node_tampered", audit verifies.
  node-mac and node-omen2 are refused as tamper targets (hard guard).
- certified: a certified job runs only on the certified node (node-mac).

Site simulators post every second, so a step that needs a different signal stops the site's simulator, keeps its
own signal fresh (re-posted every poll, so the site never goes degraded), and restarts the simulator afterwards.
"""
from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

NEVER_TAMPER = frozenset({"node-mac", "node-omen2"})
STEPS = ("migrate", "pause", "tamper", "certified")
COLD = (5.0, 5.0)  # demand kW, tank kWh: heat wanted (January-like)
WARM = (0.0, 35.0)  # no demand, tank full (July): heat not wanted


@dataclass
class Config:
    mac: str = "node-mac"
    omen: str = "node-omen2"
    tamper_node: str = "node-demo-tamper"
    tamper_token_file: str | None = None
    job_type: str = "image_tagging"
    chunks: int = 20
    rounds: int = 100_000
    tank_kwh: float = 35.0
    poll_s: float = 1.0
    timeout_s: float = 300.0
    pause_within_s: float = 6.0
    kill_at_progress: float = 0.3
    cmd_omen_kill: str = "ssh -n omen '~/digitalheat-omen-agent.sh kill9'"  # "pull the plug" (design, #77)
    cmd_omen_start: str = "ssh -n omen '~/digitalheat-omen-agent.sh start'"
    cmd_sitesim_stop: str = "pkill -f 'coordinator.sitesim.*--site {site}( |$)'"
    sitesim_url: str = "http://127.0.0.1:8710"  # the simulators run on the Mac next to the coordinator
    # .venv/bin/python, not python3: a bare python3 can resolve to an interpreter without httpx (seen live, #77)
    cmd_sitesim_start: str = ("PYTHONPATH=src nohup .venv/bin/python -m coordinator.sitesim --coordinator {sitesim_url} "
                              "--token-file runs/coordinator/tok/site_{site} --site {site} --replay coldest --speed 60 "
                              "--loop >> runs/coordinator/sitesim-{site}.log 2>&1 &")


class Api:
    def __init__(self, url: str, admin_token: str, observer_token: str, timeout: float = 10.0):
        self.url = url.rstrip("/")
        self.admin = httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {admin_token}"}, timeout=timeout)
        self.obs = httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {observer_token}"}, timeout=timeout)

    def status(self) -> dict:
        r = self.obs.get("/v1/status")
        r.raise_for_status()
        return r.json()

    def submit(self, **job) -> dict:
        r = self.admin.post("/v1/jobs", json=job)
        r.raise_for_status()
        return r.json()

    def signal(self, site: str, demand_kw: float, tank_kwh: float) -> None:
        r = self.admin.post(f"/v1/sites/{site}/signal",
                            json={"demand_kw": demand_kw, "tank_level_kwh": tank_kwh, "ts": time.time()})
        r.raise_for_status()

    def tamper(self, node: str) -> dict:
        r = self.admin.post(f"/v1/nodes/{node}/tamper")
        r.raise_for_status()
        return r.json()

    def node_call(self, token: str, method: str, path: str, **kw) -> httpx.Response:
        with httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {token}"}, timeout=10.0) as c:
            return c.request(method, path, **kw)


@dataclass
class Ctx:
    api: Any
    cfg: Config
    dry_run: bool = False
    out: Callable[[str], None] = print
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    run_cmd: Callable[[str], int] | None = None
    t0: float = 0.0
    audit: dict[int, dict] = field(default_factory=dict)
    held: dict[str, tuple[float, float]] = field(default_factory=dict)  # site -> signal kept fresh

    def log(self, msg: str) -> None:
        self.out(f"t+{self.clock() - self.t0:6.1f}s  {msg}")

    def sh(self, cmd: str, **fmt) -> int:
        cmd = cmd.format(url=getattr(self.api, "url", ""), sitesim_url=self.cfg.sitesim_url, **fmt)
        if self.dry_run or not cmd:
            self.log(f"$ {cmd or '(no command configured)'}{'  [dry-run]' if self.dry_run else ''}")
            return 0
        self.log(f"$ {cmd}")
        if self.run_cmd is not None:
            return self.run_cmd(cmd)
        return subprocess.run(cmd, shell=True, timeout=60).returncode

    def poll(self) -> dict:
        """One status read (keeping held signals fresh). A coordinator restart mid-step (connection refused, 5xx) is
        retried until the step's deadline instead of failing the step."""
        for attempt in range(30):
            try:
                for site, (d, t) in self.held.items():  # keep steering signals fresh (sim stopped for that site)
                    self.api.signal(site, d, t)
                st = self.api.status()
                break
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                    raise
                self.log(f"coordinator unreachable ({type(e).__name__}); retrying")
                self.sleep(self.cfg.poll_s)
        else:
            raise StepFail("coordinator unreachable for 30 polls")
        for e in st.get("recent_audit", []):
            self.audit.setdefault(e["idx"], e)
        return st

    def wait(self, what: str, pred: Callable[[dict], Any], timeout: float | None = None) -> Any:
        end = self.clock() + (timeout or self.cfg.timeout_s)
        while True:
            st = self.poll()
            got = pred(st)
            if got:
                self.log(f"ok: {what}")
                return got
            if self.clock() >= end:
                raise StepFail(f"timeout waiting for: {what}")
            self.sleep(self.cfg.poll_s)

    def events(self, kind: str, **match) -> list[dict]:
        return [e for _, e in sorted(self.audit.items())
                if e.get("type") == kind and all(e.get(k) == v for k, v in match.items())]

    def hold_signal(self, site: str, sig: tuple[float, float]) -> None:
        self.sh(self.cfg.cmd_sitesim_stop, site=site)
        self.held[site] = sig
        if not self.dry_run:
            self.api.signal(site, *sig)
        self.log(f"signal {site}: demand {sig[0]} kW, tank {sig[1]} kWh (held)")

    def release_signal(self, site: str) -> None:
        self.held.pop(site, None)
        self.sh(self.cfg.cmd_sitesim_start, site=site)
        if self.dry_run:
            self.log(f"signal {site}: simulator restarted (January replay)")
            return
        # verify the simulator really came back: its site signal must be fresh again (else the site goes degraded)
        self.wait(f"{site} simulator signalling again", lambda st: next(
            (x for x in st.get("sites", []) if x["site_id"] == site and x["age_s"] < 3.0 and not x["degraded"]), None),
            timeout=20)


class StepFail(RuntimeError):
    pass


def reference_sha(cfg: Config) -> str:
    """sha256 of an uninterrupted local jobs.runner run with the same type/chunks/rounds."""
    with tempfile.TemporaryDirectory() as d:
        ck = Path(d) / "ref.ckpt"
        subprocess.run([sys.executable, "-m", "jobs.runner", cfg.job_type, "--checkpoint", str(ck), "--out",
                        str(ck.with_suffix(".out")), "--chunks", str(cfg.chunks), "--rounds", str(cfg.rounds)],
                       check=True, capture_output=True)
        return hashlib.sha256(ck.with_suffix(".out").read_bytes()).hexdigest()


def _submit(ctx: Ctx, **extra) -> str:
    c = ctx.cfg
    job = dict(job_type=c.job_type, customer_id="demo", force=True, chunks=c.chunks, rounds=c.rounds, **extra)
    if ctx.dry_run:
        ctx.log(f"submit {job}  [dry-run]")
        return "job-dryrun-u000"
    r = ctx.api.submit(**job)
    unit = f"{r['job_id']}-u000"
    ctx.log(f"submitted {r['job_id']} ({r.get('units')} unit) -> {unit}")
    return unit


def _lease_of(unit: str, node: str | None = None):
    def pred(st):
        for lz in st.get("leases", []):
            if lz["unit_id"] == unit and (node is None or lz["node_id"] == node):
                return lz
        return None
    return pred


def _completed(ctx: Ctx, unit: str):
    def pred(_st):
        ev = ctx.events("complete", unit=unit)
        return ev[-1] if ev else None
    return pred


def _progress(unit: str, node: str, frac: float):
    def pred(st):
        n = next((x for x in st.get("nodes", []) if x["node_id"] == node), None)
        return n is not None and n.get("running_unit") == unit and (n.get("progress") or 0) >= frac
    return pred


# ------------------------------------------------------------------ steps
def step_migrate(ctx: Ctx) -> None:
    c = ctx.cfg
    ref = "dry-run" if ctx.dry_run else reference_sha(c)
    ctx.log(f"reference sha (local uninterrupted run): {ref[:16]}")
    killed = False
    try:
        ctx.hold_signal(c.mac, WARM)  # steer the job to the Omen
        unit = _submit(ctx)
        if ctx.dry_run:
            ctx.log(f"wait: lease on {c.omen}; progress >= {c.kill_at_progress}; kill; {c.mac} resumes; sha == ref")
            ctx.sh(c.cmd_omen_kill)
            return
        lz = ctx.wait(f"{unit} leased by {c.omen}", _lease_of(unit, c.omen))
        ctx.wait(f"{c.omen} progress >= {c.kill_at_progress:.0%}", _progress(unit, c.omen, c.kill_at_progress))
        ctx.sh(c.cmd_omen_kill)
        killed = True
        ctx.release_signal(c.mac)  # node-mac's site wants heat again: it picks up the unit after the lease lapses
        ctx.wait(f"lease {lz['lease_id']} lapsed", lambda st: ctx.events("lease_lapsed", lease=lz["lease_id"]))
        ctx.wait(f"{unit} leased by {c.mac}", _lease_of(unit, c.mac))
        done = ctx.wait(f"{unit} completed", _completed(ctx, unit))
        if done["node"] != c.mac:
            raise StepFail(f"completed by {done['node']}, expected {c.mac}")
        if done["result"] != ref:
            raise StepFail(f"result {done['result'][:16]} != reference {ref[:16]}")
        ctx.log("result sha == reference (every chunk exactly once: the coordinator requires chunk ids 0..N-1)")
    finally:
        ctx.release_signal(c.mac) if c.mac in ctx.held else None
        if killed or ctx.dry_run:
            ctx.sh(c.cmd_omen_start)


def step_pause(ctx: Ctx) -> None:
    c = ctx.cfg
    try:
        ctx.hold_signal(c.omen, WARM)  # steer the job to node-mac
        unit = _submit(ctx)
        if ctx.dry_run:
            ctx.log(f"wait: lease on {c.mac}; set {c.mac} July; paused <= {c.pause_within_s:g}s; January; resume; done")
            ctx.hold_signal(c.mac, WARM)
            ctx.release_signal(c.mac)
            return
        lz = ctx.wait(f"{unit} leased by {c.mac}", _lease_of(unit, c.mac))
        ctx.wait(f"{c.mac} progress >= 20%", _progress(unit, c.mac, 0.2))
        ctx.hold_signal(c.mac, WARM)
        t = ctx.clock()
        ctx.wait("lease paused (July)", lambda st: ctx.events("lease_paused", lease=lz["lease_id"]),
                 timeout=c.pause_within_s + 2 * c.poll_s)
        took = ctx.clock() - t
        if took > c.pause_within_s:
            raise StepFail(f"pause took {took:.1f}s > {c.pause_within_s:g}s")
        ctx.log(f"paused after {took:.1f}s")
        ctx.wait("final checkpoint uploaded (lease released)",
                 lambda st: ctx.events("lease_released", lease=lz["lease_id"]), timeout=30)
        ctx.release_signal(c.mac)  # January again
        ctx.wait(f"{unit} leased again", lambda st: next((x for x in st.get("leases", [])
                                                         if x["unit_id"] == unit and x["lease_id"] != lz["lease_id"]), None))
        done = ctx.wait(f"{unit} completed", _completed(ctx, unit))
        ctx.log(f"completed by {done['node']} after resuming from the checkpoint")
    finally:
        for site in (c.mac, c.omen):
            if site in ctx.held:
                ctx.release_signal(site)


def step_tamper(ctx: Ctx) -> None:
    c = ctx.cfg
    node = c.tamper_node
    if node in NEVER_TAMPER:
        raise StepFail(f"refusing to tamper {node}: demo nodes are never tampered")
    if ctx.dry_run:
        ctx.log(f"register {node}; tamper {node} (admin); {node} lease -> 'key denied: node_tampered'; audit verifies")
        return
    tok_file = Path(c.tamper_token_file) if c.tamper_token_file else Path(f"runs/coordinator/tok/node_{node}")
    if not tok_file.exists():
        raise StepFail(f"no token for {node} at {tok_file}; pass --tamper-token-file (the throwaway node's own token)")
    tok = tok_file.read_text().strip()
    import trust  # noqa: PLC0415
    ev = {"measurement": "digitalheat-node-image-v1", "region": "CH-BS", "certified": False}
    a = trust.attest(node, ev)
    import base64  # noqa: PLC0415
    body = {"node_id": node, "site_id": node, "eligible_classes": ["public"], "server_kw_el": 1.0,
            "attestation": {"node_id": node, "evidence": ev, "signature_b64": base64.b64encode(a.signature).decode(),
                            "mock": True}}
    r = ctx.api.node_call(tok, "POST", "/v1/nodes/register", json=body)
    ctx.log(f"register {node}: HTTP {r.status_code}")
    if r.status_code != 200:
        raise StepFail(f"cannot register {node}: {r.text[:200]}")
    ctx.log(f"tamper {node}: {ctx.api.tamper(node)}")
    r = ctx.api.node_call(tok, "POST", f"/v1/nodes/{node}/lease").json()
    ctx.log(f"{node} asks for work: {r}")
    if r.get("reason") != "key denied: node_tampered":
        raise StepFail(f"expected key denied, got {r}")
    st = ctx.poll()
    if not st.get("audit_verifies"):
        raise StepFail("audit chain does not verify")
    if not next((n for n in st["nodes"] if n["node_id"] == node), {}).get("tampered"):
        raise StepFail(f"{node} not shown as tampered")
    ctx.log("key denied, node shown tampered, audit chain verifies")


def step_certified(ctx: Ctx) -> None:
    c = ctx.cfg
    unit = _submit(ctx, access_class="certified")
    if ctx.dry_run:
        ctx.log(f"wait: {unit} runs only on {c.mac} (the certified node)")
        return
    done = ctx.wait(f"{unit} completed", _completed(ctx, unit))
    leased_by = {e["node"] for e in ctx.events("lease", unit=unit)}
    if done["node"] != c.mac or leased_by - {c.mac}:
        raise StepFail(f"certified unit ran on {leased_by or {done['node']}}, expected only {c.mac}")
    ctx.log(f"certified unit leased only by {sorted(leased_by) or [c.mac]} and completed by {done['node']}")


STEP_FUNCS = {"migrate": step_migrate, "pause": step_pause, "tamper": step_tamper, "certified": step_certified}


def run_steps(ctx: Ctx, steps: list[str]) -> dict[str, bool]:
    results = {}
    for name in steps:
        ctx.t0 = ctx.clock()
        ctx.out(f"=== {name} {'(dry-run)' if ctx.dry_run else ''}")
        try:
            STEP_FUNCS[name](ctx)
            results[name] = True
            ctx.out(f"PASS {name} ({ctx.clock() - ctx.t0:.1f}s)")
        except (StepFail, httpx.HTTPError, subprocess.SubprocessError) as e:
            results[name] = False
            ctx.out(f"FAIL {name}: {e}")
    return results


def quote(s: str) -> str:
    return shlex.quote(s)
