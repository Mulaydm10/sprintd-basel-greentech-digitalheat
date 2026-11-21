"""python -m coordinator.sitesim --coordinator URL --token-file T --site S [--replay coldest|july|year] [--speed 3600]

Site simulator (contract coordinator v1.1): replays the house_model reference profile and posts heat signals
`POST /v1/sites/{site}/signal {demand_kw, tank_level_kwh, ts}` so the demo can run "January" and "July" live.

- `--replay coldest`: the day with the lowest mean temperature; `july`: 2025-07-15; `year`: the whole profile.
- `--speed`: simulated seconds per real second (default 3600 = 1 sim hour per real second).
- A signal is posted at least once per real second and at least once per simulated hour (the coordinator marks a
  site degraded after 2 ticks without one). `demand_kw` is the profile row of the current sim hour; `ts` is the
  simulated epoch time.
- Tank model (kept simple): every signal reply carries `heat_used_kw` (the heat recovered by the site's nodes that
  hold active leases). Between posts, tank += (heat_used_kw - demand_kw) * sim_dt, clamped to [0, capacity];
  heat above capacity is dumped, demand the tank cannot cover is the backup heater's.
- Network errors, 5xx and 429 back off exponentially with full jitter (cap 10 s) and retry the same signal;
  401/403/422 stop with a clear message. The token is read from a file and never logged.
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx
import pandas as pd

from common.config import load_assumptions

log = logging.getLogger("coordinator.sitesim")
REPLAYS = ("coldest", "july", "year")
JULY_DAY = "2025-07-15"
BACKOFF_CAP_S = 10.0
MAX_POST_INTERVAL_S = 1.0


class Fatal(RuntimeError):
    pass


def replay_rows(profile: pd.DataFrame, replay: str) -> pd.DataFrame:
    if replay == "year":
        return profile
    dates = pd.Index(profile.index.date)
    if replay == "coldest":
        day = profile["temp_c"].groupby(dates).mean().idxmin()
    elif replay == "july":
        day = pd.Timestamp(JULY_DAY).date()
    else:
        raise ValueError(f"replay must be one of {REPLAYS}")
    rows = profile[dates == day]
    if rows.empty:
        raise ValueError(f"profile has no rows for {day}")
    return rows


@dataclass
class SiteSim:
    http: httpx.Client
    site_id: str
    rows: pd.DataFrame
    speed: float = 3600.0
    capacity_kwh: float = 35.0
    tank_kwh: float = 17.5
    sleep: Callable[[float], None] = time.sleep
    rng: random.Random = field(default_factory=random.Random)
    sim_s: float = 0.0
    failures: int = 0
    posted: list[dict] = field(default_factory=list)

    @property
    def interval_s(self) -> float:
        return min(MAX_POST_INTERVAL_S, 3600.0 / self.speed)

    def done(self) -> bool:
        return self.sim_s >= len(self.rows) * 3600.0

    def backoff(self) -> float:
        self.failures += 1
        d = min(BACKOFF_CAP_S, 0.5 * 2 ** min(self.failures - 1, 16)) * (0.5 + self.rng.random() / 2)
        self.sleep(d)
        return d

    def post(self) -> float:
        """Post the signal for the current sim time (retrying with backoff); return the reported heat used."""
        i = int(self.sim_s // 3600)
        row = self.rows.iloc[i]
        body = {"demand_kw": round(float(row["demand_kw"]), 6), "tank_level_kwh": round(self.tank_kwh, 6),
                "ts": float(self.rows.index[i].timestamp()) + self.sim_s % 3600}
        while True:
            try:
                r = self.http.post(f"/v1/sites/{self.site_id}/signal", json=body)
            except httpx.TransportError as e:
                log.warning("signal: %s; backing off", type(e).__name__)
                self.backoff()
                continue
            if r.status_code >= 500 or r.status_code == 429:
                log.warning("signal: HTTP %s; backing off", r.status_code)
                self.backoff()
                continue
            if r.status_code != 200:
                raise Fatal(f"signal refused: HTTP {r.status_code} {r.text[:200]}")
            self.failures = 0
            self.posted.append(body)
            return float(r.json().get("heat_used_kw") or 0.0)

    def step(self) -> None:
        demand = float(self.rows.iloc[int(self.sim_s // 3600)]["demand_kw"])
        heat = self.post()
        dt_real = self.interval_s
        self.sleep(dt_real)
        dt_h = dt_real * self.speed / 3600.0
        self.tank_kwh = min(self.capacity_kwh, max(0.0, self.tank_kwh + (heat - demand) * dt_h))
        self.sim_s += dt_real * self.speed

    def run(self, stop: Callable[[], bool] = lambda: False) -> None:
        while not self.done() and not stop():
            self.step()


def main(argv: list[str] | None = None) -> int:
    from house_model import load_reference_profile
    from live_agent.__main__ import client, read_token

    from .auth import ID_RE
    p = argparse.ArgumentParser(prog="python -m coordinator.sitesim", description=__doc__.splitlines()[0])
    p.add_argument("--coordinator", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--site", required=True)
    p.add_argument("--replay", default="coldest", choices=REPLAYS)
    p.add_argument("--speed", type=float, default=3600.0, help="sim seconds per real second")
    p.add_argument("--tank0", type=float, default=None, help="initial tank kWh (default: half the capacity)")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not ID_RE.match(a.site) or not a.speed > 0:
        raise SystemExit("--site must match [a-z0-9-]{1,64} and --speed must be > 0")
    cap = float(load_assumptions()["house"]["tank_kwh"])
    from pathlib import Path
    with client(a.coordinator, read_token(Path(a.token_file))) as http:
        sim = SiteSim(http, a.site, replay_rows(load_reference_profile(), a.replay), a.speed, cap,
                      cap / 2 if a.tank0 is None else min(cap, max(0.0, a.tank0)))
        try:
            sim.run()
        except Fatal as e:
            print(f"sitesim: {e}", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
