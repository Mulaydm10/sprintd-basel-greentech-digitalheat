"""Node agent (contract live_agent v2): a pure HTTP client of the coordinator (contract coordinator v1).

    register → [heartbeat thread every 2 s] → loop { lease → hold: sleep | unit: run jobs.runner }

Per unit:
- the job key comes only from the lease's ``key_release``; ``denied`` → report it in the heartbeat and drop the unit;
- a checkpoint from ``checkpoint_url`` is fetched, opened with the job key and restored, else the unit starts clean;
- ``jobs.runner`` runs as a **subprocess** (the only thing this agent ever executes) in ``runs/agent/<node_id>/<unit_id>/``;
- the lease is renewed every ``renew_every_s`` (from the lease, capped by config); checkpoints are sealed to the
  job key and uploaded (raw body + ``X-Next-Chunk/X-Out-Bytes/X-Sha256``) when progress was made, at most every
  ``upload_s``;
- a key denial arrives as ``{hold, reason: "key denied: ..."}`` (coordinator v1): it is reported in the heartbeat;
- renew says ``hold`` → **pause**: stop file (portable, #51), wait ≤ ``stop_grace_s``, kill, upload the final checkpoint;
- renew/upload/complete answers 410, or no renewal succeeded before the lease's expiry → **lapsed**: kill now and
  discard the local partial output (another node owns the unit);
- finished → upload the final checkpoint, then ``complete`` with the output's sha256 and its chunk ids.

Network errors, 5xx and 429 back off exponentially with jitter (cap 10 s) and are retried; they never crash the agent.
Ids from the coordinator are checked against ``[a-z0-9-]{1,64}`` before they name a directory.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from common.config import ROOT
from jobs.catalogue import load_catalogue
from trust import attest, open_, seal

import trust

from . import wire
from .power import PowerMeter

log = logging.getLogger("live_agent")
ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")
MEASUREMENT = "digitalheat-node-image-v1"  # what the (mock) broker expects; the attestation is labelled mock
REGION = "CH-BS"
BACKOFF_CAP_S = 10.0
TRANSCRIBERS = ("echo", "whisper-local", "elevenlabs")  # #127 live transcription backends (live_agent/transcriber.py)
BACKENDS = ("cpu-hash", "fake")  # what jobs.runner implements today; mlx / faster-whisper need runner backends


class Fatal(RuntimeError):
    """The coordinator refused us for good (401/403 on register): stop with a clear message."""


class Retry(RuntimeError):
    """A transient failure (network, 5xx, 429): back off and try again."""


@dataclass
class Config:
    node_id: str
    site_id: str
    eligible_classes: list[str] = field(default_factory=lambda: ["public"])
    server_kw_el: float = 1.0
    certified: bool = False
    backend: str = "cpu-hash"
    root: Path = ROOT / "runs" / "agent"
    python: str = sys.executable
    heartbeat_s: float = 2.0
    renew_s: float = 5.0
    upload_s: float = 10.0
    stop_grace_s: float = 5.0
    poll_s: float = 0.05
    default_rounds: int = 50  # v2.1: used only when the unit carries no `rounds` (CLI --rounds)
    default_chunks: int = 20  # v2.1: used only when the unit carries no `chunks` (CLI --chunks)
    transcriber: str | None = None  # #127: echo | whisper-local | elevenlabs (live transcription leases)
    whisper_model: str = "small.en"
    key_file: Path | None = None  # elevenlabs key (or ELEVENLABS_API_KEY); never logged

    def __post_init__(self) -> None:
        if not ID_RE.match(self.node_id) or not ID_RE.match(self.site_id):
            raise ValueError(f"node_id/site_id must match {ID_RE.pattern}")
        if self.backend in TRANSCRIBERS:  # `--backend whisper-local` (contract #127): the transcriber; batch units keep cpu-hash
            self.transcriber, self.backend = self.backend, "cpu-hash"
        if self.backend not in BACKENDS:
            raise ValueError(f"backend {self.backend!r} is not available in jobs.runner yet; use one of {BACKENDS}")


def launch_runner(python: str, job_type: str, ckpt: Path, out: Path, stop_file: Path, chunks: int, rounds: int,
                  cwd: Path) -> subprocess.Popen:
    """Start jobs.runner tied to this process (#64): it exits within one chunk if we die, even by kill -9."""
    cmd = [python, "-m", "jobs.runner", job_type, "--checkpoint", str(ckpt), "--out", str(out),
           "--stop-file", str(stop_file), "--chunks", str(chunks), "--rounds", str(rounds),
           "--parent-pid", str(os.getpid())]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    return subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(cwd))


class Agent:
    def __init__(self, cfg: Config, http: httpx.Client, hb_http: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 rng: random.Random | None = None) -> None:
        self.cfg, self.http, self.hb_http = cfg, http, hb_http or http
        self.sleep, self.clock, self.rng = sleep, clock, rng or random.Random()
        self.workdir = cfg.root / cfg.node_id
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.power = PowerMeter(self.workdir)
        self._clean_stale_units()
        self.job_types = {j.name for j in load_catalogue()}
        self.state: dict[str, Any] = {"running_unit": None, "progress": 0.0, "last_error": None}
        self._transcriber = None  # #127: built lazily on the first live lease (Whisper loads a model)
        self._failures = 0
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None

    def _clean_stale_units(self) -> None:
        """A fresh agent holds no lease, so every unit dir left by a previous (crashed) agent is stale (#64)."""
        for p in self.workdir.iterdir():
            if p.is_dir() and not p.is_symlink() and ID_RE.match(p.name):
                shutil.rmtree(p, ignore_errors=True)

    # ------------------------------------------------------------------ HTTP with backoff
    def _post(self, path: str, http: httpx.Client | None = None, **kw) -> httpx.Response:
        try:
            r = (http or self.http).post(path, **kw)
        except httpx.TransportError as e:
            raise Retry(f"{path}: {type(e).__name__}") from e
        if r.status_code >= 500 or r.status_code == 429:
            raise Retry(f"{path}: HTTP {r.status_code}")
        return r

    def backoff(self) -> float:
        """Sleep exponentially longer after each consecutive failure, with full jitter, capped at 10 s."""
        self._failures += 1
        d = min(BACKOFF_CAP_S, 0.5 * 2 ** min(self._failures - 1, 16)) * (0.5 + self.rng.random() / 2)
        self.sleep(d)
        return d

    def _ok(self) -> None:
        self._failures = 0

    # ------------------------------------------------------------------ register + heartbeat
    def register(self) -> None:
        ev = {"node_id": self.cfg.node_id, "region": REGION, "measurement": MEASUREMENT,
              "certified": self.cfg.certified}
        body = {"node_id": self.cfg.node_id, "site_id": self.cfg.site_id,
                "eligible_classes": self.cfg.eligible_classes, "server_kw_el": self.cfg.server_kw_el,
                "attestation": wire.attestation_to_json(attest(self.cfg.node_id, ev))}
        while True:
            try:
                r = self._post("/v1/nodes/register", json=body)
            except Retry as e:
                log.warning("register: %s; backing off", e)
                self.backoff()
                continue
            if r.status_code in (401, 403):
                raise Fatal(f"register refused: HTTP {r.status_code} {r.text[:200]}")
            if r.status_code != 200:
                raise Fatal(f"register: unexpected HTTP {r.status_code} {r.text[:200]}")
            self._ok()
            return

    def heartbeat_once(self) -> bool:
        watts, source = self.power.read()
        body = {"watts": watts, "watts_source": source, "running_unit": self.state["running_unit"],
                "progress": round(float(self.state["progress"]), 4)}
        if self.cfg.transcriber:
            body["backend"] = self.cfg.transcriber  # #127: shown per node on the pages and the trace card
        if self.state["last_error"]:
            body["last_error"] = self.state["last_error"]
        try:
            r = self._post(f"/v1/nodes/{self.cfg.node_id}/heartbeat", http=self.hb_http, json=body)
            return r.status_code == 200
        except Retry:
            return False

    def start_heartbeat(self) -> None:
        def loop() -> None:
            while not self._hb_stop.wait(self.cfg.heartbeat_s):
                self.heartbeat_once()
        self.heartbeat_once()
        self._hb_thread = threading.Thread(target=loop, name="heartbeat", daemon=True)
        self._hb_thread.start()

    def stop_heartbeat(self) -> None:
        self._hb_stop.set()
        if self._hb_thread:
            self._hb_thread.join(timeout=5)

    # ------------------------------------------------------------------ main loop
    def run_forever(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        self.register()
        self.start_heartbeat()
        try:
            while not stop.is_set():
                self.step()
        finally:
            self.stop_heartbeat()

    def step(self) -> str:
        """One lease cycle. Returns what happened (for logs and tests)."""
        try:
            r = self._post(f"/v1/nodes/{self.cfg.node_id}/lease")
        except Retry as e:
            log.warning("lease: %s; backing off", e)
            self.backoff()
            return "backoff"
        if r.status_code in (401, 403):
            raise Fatal(f"lease refused: HTTP {r.status_code} {r.text[:200]}")
        if r.status_code != 200:
            log.warning("lease: HTTP %s", r.status_code)
            self.backoff()
            return "backoff"
        self._ok()
        d = r.json()
        if d.get("hold") or not d.get("unit"):
            reason = str(d.get("reason", ""))
            if reason.startswith("key denied"):  # coordinator v1: denial arrives as a hold; report it
                self.state["last_error"] = reason
            self.sleep(min(BACKOFF_CAP_S, max(0.0, float(d.get("retry_after_s", 2.0)))))
            return "denied" if reason.startswith("key denied") else "hold"
        return self.run_unit(d)

    # ------------------------------------------------------------------ one unit
    def _unit_dir(self, unit_id: str) -> Path:
        if not ID_RE.match(unit_id):
            raise ValueError(f"unit_id {unit_id!r} does not match {ID_RE.pattern}")
        d = (self.workdir / unit_id).resolve()
        if self.workdir.resolve() not in d.parents:
            raise ValueError(f"unit dir {d} escapes {self.workdir}")
        return d

    def run_live(self, lease: dict[str, Any]) -> str:
        """#127: hold a live transcription lease: long-poll segments, decrypt with the released job key, transcribe
        in seq order, post each result once; renew; stop at once on 410 (STOP moved the job). -> done | lapsed | denied."""
        kr = lease.get("key_release") or {}
        if "key_b64" not in kr:
            self.state["last_error"] = "key denied for live transcription"
            return "denied"
        if not self.cfg.transcriber:
            self.state["last_error"] = "live transcription lease but no transcriber configured (--backend echo|whisper-local|elevenlabs)"
            return "rejected"
        if self._transcriber is None:
            from .transcriber import make
            self._transcriber = make(self.cfg.transcriber, self.cfg.whisper_model, self.cfg.key_file)
        key, lease_id, unit_id = wire.key_from_json(kr), str(lease["lease_id"]), str(lease["unit"]["unit_id"])
        self.state.update(running_unit=unit_id, progress=0.0, last_error=None)
        after, last_renew = -1, self.clock()
        renew_s = min(self.cfg.renew_s, float(lease.get("renew_every_s", self.cfg.renew_s)))
        try:
            while True:
                if self.clock() - last_renew >= renew_s:
                    r = self._post(f"/v1/leases/{lease_id}/renew")
                    if r.status_code == 410:  # moved by STOP, or the job just finished here: the fetch tells which
                        f = self.http.get(f"/v1/leases/{lease_id}/segments", params={"after": after, "wait": 0})
                        return "done" if f.status_code == 200 and f.json().get("done") else "lapsed"
                    last_renew = self.clock()
                try:
                    r = self.http.get(f"/v1/leases/{lease_id}/segments", params={"after": after, "wait": min(2.0, renew_s)},
                                      timeout=httpx.Timeout(15.0, connect=5.0))
                except httpx.TransportError:
                    self.backoff()
                    continue
                if r.status_code == 410:
                    return "lapsed"
                if r.status_code != 200:
                    self.backoff()
                    continue
                self._ok()
                d = r.json()
                if d.get("done"):
                    return "done"
                after = max(after, int(d["next_seq"]) - 1)
                for s in d["segments"]:
                    if int(s["seq"]) != after + 1:
                        break  # strictly in order: refetch from the first un-accepted seq
                    wav = trust.open_(wire.envelope_from_bytes(base64.b64decode(s["envelope_b64"])), key)
                    t0 = self.clock()
                    out = self._transcriber.transcribe(wav, d.get("context", ""), int(s["seq"]))
                    body = {"text": out["text"], "backend": self.cfg.transcriber, "ms": round((self.clock() - t0) * 1000, 1)}
                    if out.get("words"):
                        body["words"] = [{"w": str(w["w"]), "t0": float(w["t0"]), "t1": float(w["t1"])} for w in out["words"][:400]]
                    rr = self._post(f"/v1/leases/{lease_id}/segments/{s['seq']}/result", json=body)
                    if rr.status_code == 410:
                        return "lapsed"
                    if rr.status_code not in (200, 201):
                        break
                    after = int(s["seq"])
                    self.state["progress"] = 0.0
                    last_renew = self.clock()  # an accepted result extends the lease on the coordinator
                if d["ended"] and not d["segments"] and int(d["next_seq"]) == after + 1:
                    return "done"
        except Retry:
            self.backoff()
            return "lapsed"
        finally:
            self.state.update(running_unit=None, progress=0.0)

    def run_unit(self, lease: dict[str, Any]) -> str:
        u, lease_id = lease["unit"], str(lease["lease_id"])
        unit_id, job_type = str(u["unit_id"]), str(u["job_type"])
        if job_type == "live_transcription" and ID_RE.match(lease_id) and ID_RE.match(unit_id):
            return self.run_live(lease)
        if not ID_RE.match(lease_id) or job_type not in self.job_types:
            self.state["last_error"] = f"rejected lease {lease_id!r}: bad id or unknown job_type {job_type!r}"
            return "rejected"
        kr = lease.get("key_release") or {}
        if "denied" in kr or "key_b64" not in kr:
            self.state["last_error"] = f"key denied for {unit_id}: {kr.get('denied', 'no key_release')}"
            log.warning(self.state["last_error"])
            return "denied"
        key = wire.key_from_json(kr)
        d = self._unit_dir(unit_id)
        shutil.rmtree(d, ignore_errors=True)  # never resume from a local partial: the coordinator's copy is truth
        d.mkdir(parents=True)
        ckpt, out, stop_file = d / "job.ckpt", d / "job.out", d / "job.stop"
        if lease.get("checkpoint_url"):
            if not self._restore(lease["checkpoint_url"], key, ckpt, out):
                return "lapsed"
        chunks = int(u.get("chunks") or self.cfg.default_chunks)  # the unit's value wins (v2.1)
        rounds = int(u.get("rounds") or (1 if self.cfg.backend == "fake" else self.cfg.default_rounds))
        renew_s = min(self.cfg.renew_s, float(lease.get("renew_every_s", self.cfg.renew_s)))
        self.state.update(running_unit=unit_id, progress=0.0, last_error=None)
        proc = launch_runner(self.cfg.python, job_type, ckpt, out, stop_file, chunks, rounds, d)
        try:
            return self._supervise(proc, lease_id, unit_id, key, ckpt, out, stop_file, chunks,
                                   float(lease.get("expires_in_s", 15)), renew_s)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            self.state.update(running_unit=None, progress=0.0)

    def _restore(self, url: str, key, ckpt: Path, out: Path) -> bool:
        while True:
            try:
                r = self.http.get(url)
            except httpx.TransportError:
                self.backoff()
                continue
            if r.status_code >= 500 or r.status_code == 429:
                self.backoff()
                continue
            break
        if r.status_code == 404:
            return True  # nothing uploaded yet: start clean
        if r.status_code != 200:
            return False
        sha = r.headers.get("X-Sha256")
        if sha and sha != wire.sha256_hex(r.content):
            self.state["last_error"] = "checkpoint download corrupted (sha256 mismatch)"
            return False
        state, log_bytes = wire.bundle_from_bytes(open_(wire.envelope_from_bytes(r.content), key))
        out.write_bytes(log_bytes)
        ckpt.write_text(json.dumps(state, sort_keys=True))
        return True

    def _supervise(self, proc, lease_id, unit_id, key, ckpt, out, stop_file, chunks, expires_in_s,
                   renew_s) -> str:
        now = self.clock()
        next_renew, last_upload, uploaded_chunk = now + renew_s, now, self._next_chunk(ckpt)
        lease_deadline = now + expires_in_s
        while proc.poll() is None:
            self.sleep(self.cfg.poll_s)
            now = self.clock()
            nc = self._next_chunk(ckpt)
            self.state["progress"] = nc / chunks if chunks else 1.0
            if now >= next_renew:
                verdict, expires = self._renew(lease_id)
                if verdict == "lapsed":
                    return self._discard(proc, unit_id, "lease lapsed (410)")
                if verdict == "ok":
                    lease_deadline = now + expires
                    next_renew = now + renew_s
                elif verdict == "hold":
                    return self._pause(proc, lease_id, key, ckpt, out, stop_file, uploaded_chunk, expires)
                else:  # transient: retry soon, but never past the lease expiry
                    next_renew = now + min(renew_s, 1.0)
            if now >= lease_deadline:
                return self._discard(proc, unit_id, "no renewal before lease expiry")
            if nc > uploaded_chunk and now - last_upload >= self.cfg.upload_s:
                res = self._upload(lease_id, key, ckpt, out)
                if res == "lapsed":
                    return self._discard(proc, unit_id, "lease lapsed on upload (410)")
                if res == "ok":
                    uploaded_chunk, last_upload = nc, now
        rc = proc.returncode
        state = self._load(ckpt)
        if rc != 0 or not state or not state.get("done"):
            err = proc.stderr.read().decode(errors="replace")[-500:] if proc.stderr else ""
            self.state["last_error"] = f"jobs.runner exited {rc} for {unit_id}: {err}"
            if state and self._upload(lease_id, key, ckpt, out) == "lapsed":
                return self._discard(proc, unit_id, "lease lapsed on upload (410)")
            return "runner-error"
        if self._upload(lease_id, key, ckpt, out) == "lapsed":
            return self._discard(proc, unit_id, "lease lapsed on final upload (410)")
        return self._complete(lease_id, unit_id, out)

    # ------------------------------------------------------------------ lease calls
    def _renew(self, lease_id: str) -> tuple[str, float]:
        try:
            r = self._post(f"/v1/leases/{lease_id}/renew")
        except Retry:
            return "retry", 0.0
        if r.status_code == 410:
            return "lapsed", 0.0
        if r.status_code != 200:
            return "retry", 0.0
        d = r.json()
        if d.get("hold") or d.get("stop"):  # {hold, final_checkpoint_within_s}: window for the one final upload
            return "hold", float(d.get("final_checkpoint_within_s") or self.cfg.stop_grace_s + 1.0)
        return "ok", float(d.get("expires_in_s", 15))

    def _upload(self, lease_id: str, key, ckpt: Path, out: Path) -> str:
        state = self._load(ckpt)
        if not state:
            return "skip"
        env = wire.envelope_to_bytes(seal(wire.bundle_to_bytes(state, out.read_bytes()), key.public_key()))
        headers = {"Content-Type": "application/octet-stream", "X-Next-Chunk": str(state["next_chunk"]),
                   "X-Out-Bytes": str(state["out_bytes"]), "X-Sha256": wire.sha256_hex(env)}
        for _ in range(6):
            try:
                r = self._post(f"/v1/leases/{lease_id}/checkpoint", content=env, headers=headers)
            except Retry:
                self.backoff()
                continue
            if r.status_code == 410:
                return "lapsed"
            self._ok()
            return "ok" if r.status_code == 200 else "failed"
        return "failed"

    def _complete(self, lease_id: str, unit_id: str, out: Path) -> str:
        data = out.read_bytes()
        chunk_ids = [int(line.split()[0]) for line in data.decode().splitlines()]
        body = {"result_sha256": wire.sha256_hex(data), "chunk_ids": chunk_ids}
        while True:
            try:
                r = self._post(f"/v1/leases/{lease_id}/complete", json=body)
            except Retry:
                self.backoff()
                continue
            break
        self._ok()
        if r.status_code == 410:
            return self._discard(None, unit_id, "lease lapsed on complete (410)")
        if r.status_code == 409:
            self.state["last_error"] = f"conflicting result for {unit_id} (409)"
            return "conflict"
        return "completed" if r.status_code == 200 else f"complete-http-{r.status_code}"

    # ------------------------------------------------------------------ stop paths
    def _pause(self, proc, lease_id, key, ckpt, out, stop_file, uploaded_chunk, final_within_s=None) -> str:
        stop_file.touch()
        grace = self.cfg.stop_grace_s
        if final_within_s is not None:  # leave ~1 s of the coordinator's window for the final upload itself
            grace = max(0.0, min(grace, final_within_s - 1.0))
        t_end = self.clock() + grace
        while proc.poll() is None and self.clock() < t_end:
            self.sleep(self.cfg.poll_s)
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if self._next_chunk(ckpt) > 0 and self._upload(lease_id, key, ckpt, out) == "lapsed":
            return "lapsed"
        return "paused"

    def _discard(self, proc, unit_id: str, why: str) -> str:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        shutil.rmtree(self._unit_dir(unit_id), ignore_errors=True)
        self.state["last_error"] = f"{unit_id}: {why}; local partial discarded"
        log.warning(self.state["last_error"])
        return "lapsed"

    @staticmethod
    def _load(ckpt: Path) -> dict[str, Any] | None:
        try:
            return json.loads(ckpt.read_text())
        except (OSError, ValueError):
            return None

    def _next_chunk(self, ckpt: Path) -> int:
        s = self._load(ckpt)
        return int(s["next_chunk"]) if s else 0
