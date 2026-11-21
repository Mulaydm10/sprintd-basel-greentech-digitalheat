"""Job arrivals (contracts/src/jobs.md).

JOBS_PER_DAY: mean arrivals per day per job type = `jobs_per_day` of each `jobs:` entry in
data/assumptions.yaml. Source: explicit ASSUMPTION (placeholder until a trace-based number, e.g. the
Alibaba cluster trace, replaces it); see JOBS_PER_DAY_SOURCE. Per day and type the count is
Poisson(jobs_per_day); each arrival hour is uniform over the day's local hours.

Unlimited-backlog mode is an explicit flag: `daily_arrivals(..., unlimited_backlog=True, servers=N)`
adds one filler job per server of the cheapest *public interruptible* type, sized to a full day, so the
servers never starve (the always-on / ballast assumption).

`to_units()` splits a Job into scheduler work units (`scheduler.unit_minutes`) for simulate_year/live_agent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from common.config import load_assumptions
from scheduler.types import Unit

from .catalogue import JobType, load_catalogue

JOBS_PER_DAY_SOURCE = "ASSUMED placeholder: jobs_per_day per type in data/assumptions.yaml `jobs:` (no trace yet)"


@dataclass(frozen=True)
class Job:
    id: str
    type: JobType
    arrival: datetime  # tz-aware, local (location.tz)
    remaining_h: float  # on the reference server


def jobs_per_day(catalogue: list[JobType] | None = None) -> dict[str, float]:
    return {j.name: j.jobs_per_day for j in (catalogue or load_catalogue())}


def daily_arrivals(
    day: date,
    rng: np.random.Generator,
    catalogue: list[JobType] | None = None,
    tz: str | None = None,
    unlimited_backlog: bool = False,
    servers: int = 0,
) -> list[Job]:
    """Jobs arriving on local `day`, sorted by (arrival, id). Deterministic for a given rng state."""
    cat = catalogue or load_catalogue()
    zone = ZoneInfo(tz or load_assumptions()["location"]["tz"])
    midnight = datetime.combine(day, time(0), tzinfo=zone)
    # Hours of this local day (23 or 25 on DST days). Same-tzinfo subtraction is wall-clock in Python,
    # so measure in UTC; then step in UTC and convert back to local.
    utc = ZoneInfo("UTC")
    next_mid = datetime.combine(day + timedelta(days=1), time(0), tzinfo=zone)
    n_hours = round((next_mid.astimezone(utc) - midnight.astimezone(utc)).total_seconds() / 3600)

    jobs: list[Job] = []
    for jt in cat:
        n = int(rng.poisson(jt.jobs_per_day)) if jt.jobs_per_day > 0 else 0
        hours = sorted(int(h) for h in rng.integers(0, n_hours, size=n))
        for i, h in enumerate(hours):
            at = (midnight.astimezone(utc) + timedelta(hours=h)).astimezone(zone)
            jobs.append(Job(f"{jt.name}-{day:%Y%m%d}-{i:03d}", jt, at, jt.runtime_h))

    if unlimited_backlog:
        filler = _filler_type(cat)
        for s in range(servers):
            jobs.append(Job(f"backlog-{filler.name}-{day:%Y%m%d}-s{s:02d}", filler, midnight, float(n_hours)))
    return sorted(jobs, key=lambda j: (j.arrival, j.id))


def _filler_type(cat: list[JobType]) -> JobType:
    pool = [j for j in cat if j.access_class == "public" and j.interruptible]
    if not pool:
        raise ValueError("unlimited_backlog needs a public, interruptible job type in the catalogue")
    return min(pool, key=lambda j: (j.price_chf_per_h, j.name))


def to_units(job: Job, year_start: datetime, unit_minutes: float, server_kw_el: float) -> list[Unit]:
    """Split a job into ~unit_minutes work units. Hour indices are relative to `year_start` (tz-aware)."""
    unit_h = unit_minutes / 60.0
    n = max(1, math.ceil(job.remaining_h / unit_h - 1e-9))
    utc = ZoneInfo("UTC")
    arrival_hour = math.floor((job.arrival.astimezone(utc) - year_start.astimezone(utc)).total_seconds() / 3600 + 1e-9)
    deadline_hour = arrival_hour + math.ceil(job.type.deadline_h - 1e-9)
    out = []
    left = job.remaining_h
    for i in range(n):
        h = min(unit_h, left)
        left -= h
        out.append(Unit(
            unit_id=f"{job.id}#{i:03d}",
            job_id=job.id,
            job_class=job.type.name,
            access_class=job.type.access_class,
            kwh_el=h * server_kw_el,
            bid_chf_per_server_h=job.type.price_chf_per_h,
            deadline_hour=deadline_hour,
            slack_h=job.type.slack_h,
            checkpointable=job.type.interruptible,
        ))
    return out
