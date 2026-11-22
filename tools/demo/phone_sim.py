"""Simulated volunteer phones for wow #2 rehearsals and end-to-end tests (no real phones needed).

    python -m tools.demo.phone_sim --site https://…:8443 --code CODE [--phones 12] [--stop-after 9] [--jobs 3] [--seconds 120]

Each simulated phone joins with the event code, heartbeats every 2 s like the real page and, as a server, reports one
step of work per second while it holds a job. Server phones press STOP after a random 6-14 s of work (a phone that "feels
warm"); client phones submit --jobs jobs each. Prints a verdict: every job done, progress never lost across handovers.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
import urllib.error
import urllib.request


def call(site: str, path: str, body: dict | None = None, timeout: float = 10.0) -> tuple[int, dict]:
    req = urllib.request.Request(site.rstrip("/") + "/api/phones/" + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except (urllib.error.URLError, OSError, ValueError):  # server restarting / network blip: a real phone retries (#138)
        time.sleep(1.0)
        return 0, {}


class Phone(threading.Thread):
    def __init__(self, site: str, code: str, i: int, jobs: int, stop_range: tuple[float, float], until: float, log):
        super().__init__(daemon=True)
        self.site, self.code, self.i, self.jobs, self.stop_range, self.until, self.log = site, code, i, jobs, stop_range, until, log
        self.cred, self.role, self.seen_steps = None, None, {}

    def run(self) -> None:
        s, r = call(self.site, "join", {"code": self.code, "name": f"sim-{self.i:02d}"})
        if s != 200:
            self.log(f"sim-{self.i:02d} join {s} {r}")
            return
        self.cred, self.role = {"device_id": r["device_id"], "token": r["token"]}, r["role"]
        if self.role == "client":
            for _ in range(self.jobs):
                call(self.site, "submit", self.cred)
                time.sleep(random.uniform(2, 6))
            while time.time() < self.until:
                call(self.site, "hb", self.cred)
                time.sleep(2)
            return
        job, step, stop_at, stopped_until = None, 0, None, 0.0
        while time.time() < self.until:
            if stopped_until and time.time() >= stopped_until:
                call(self.site, "resume", self.cred); stopped_until = 0.0
            s, h = call(self.site, "hb", self.cred)
            j = h.get("job")
            if j and (job is None or j["job_id"] != job):
                job, step = j["job_id"], j["step"]
                self.seen_steps.setdefault(job, []).append(step)
                stop_at = time.time() + random.uniform(*self.stop_range)
            for _ in range(2):       # 2 steps per 2 s heartbeat
                if not job:
                    break
                step += 1
                s, p = call(self.site, "progress", {**self.cred, "job_id": job, "step": step})
                if s == 410 or p.get("state") == "done":
                    job = None
                    break
                time.sleep(1)
            if job and stop_at and time.time() >= stop_at:
                s, r = call(self.site, "stop", self.cred)
                self.log(f"sim-{self.i:02d} STOP {job} at step {r.get('step')} -> {r.get('now_on')}")
                job, stop_at, stopped_until = None, None, time.time() + random.uniform(8, 15)
            if not j:
                time.sleep(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--phones", type=int, default=12)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--seconds", type=int, default=150)
    ap.add_argument("--stop-min", type=float, default=6)
    ap.add_argument("--stop-max", type=float, default=14)
    a = ap.parse_args()
    lock = threading.Lock()
    log = lambda m: (lock.acquire(), print(time.strftime("%H:%M:%S"), m, flush=True), lock.release())  # noqa: E731
    until = time.time() + a.seconds
    ph = [Phone(a.site, a.code, i + 1, a.jobs, (a.stop_min, a.stop_max), until, log) for i in range(a.phones)]
    for p in ph:
        p.start(); time.sleep(0.4)
    for p in ph:
        p.join()
    s, st = call(a.site, "state")
    jobs = st.get("jobs", [])
    done = [j for j in jobs if j["state"] == "done"]
    moved = [j for j in jobs if len(j["hops"]) > 1]
    # progress never lost: every resume started at >= the previous phone's last reported step (server enforces), so
    # check that each job's recorded resume steps are non-decreasing across hops
    lost = [jid for p in ph for jid, steps in p.seen_steps.items() if steps != sorted(steps)]
    print(json.dumps({"phones": len(st.get("devices", [])), "jobs": len(jobs), "done": len(done), "moved": len(moved),
                      "max_hops": max((len(j["hops"]) for j in jobs), default=0), "progress_lost": lost,
                      "not_done": [(j["id"], j["state"], j["step"]) for j in jobs if j["state"] != "done"]}))
    return 0 if jobs and len(done) == len(jobs) and not lost else 1


if __name__ == "__main__":
    sys.exit(main())
