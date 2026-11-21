"""Admission check at submit time (contracts/src/scheduler.md §v2.2, from research #29).

Pure and separate from decide(). A job is accepted only if its eligible sites' *conservative* capacity
can finish it by its deadline with at least `params.deadline_safety_h` of margin; otherwise it is
rejected at submit with a reason. This is an honesty gate ("we tell you now that we can't make it"),
not a cost optimiser: Run B S1-SMART showed greedy dispatch already equals the hindsight optimum.

Timing convention (same as decide/simulate_year): work placed in hour h finishes at h + 1, and a unit
with deadline_hour d must finish by d. With the margin: finish <= d - deadline_safety_h.

Conservative forecast helpers:
- `persistence_forecast(history, horizon)` repeats the last 24 h of observed heat-used capacity and
  pads with 0 when fewer than 24 h exist (never optimistic).
- `net_of_backlog(forecast, backlog_kwh)` removes already-committed work from the front of a forecast,
  so admitting a job never double-books capacity that queued work will use.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .types import InvalidInput, Params, SiteState, Unit
from .validate import validate_params, validate_queue, validate_sites

DAY_H = 24  # persistence period: the last day repeats (definition of the method, not an assumption)

R_OK = "admitted"
R_NO_ELIGIBLE = "no eligible site for access_class"
R_EMPTY = "job has no units"
R_DEADLINE = "cannot finish before deadline minus safety margin on conservative capacity"
R_HORIZON = "forecast horizon ends before the job could finish"


@dataclass(frozen=True)
class Admission:
    accepted: bool
    reason: str
    earliest_finish_hour: int | None


def persistence_forecast(history_kwh_el: list[float], horizon_h: int) -> list[float]:
    """Repeat the last 24 hourly values; hours without history count as 0 capacity."""
    if horizon_h < 0:
        raise InvalidInput(f"horizon_h must be >= 0, got {horizon_h}")
    last = [max(0.0, float(x)) for x in history_kwh_el[-DAY_H:]]
    day = [0.0] * (DAY_H - len(last)) + last  # pad the oldest hours with 0 (conservative)
    return [day[i % DAY_H] for i in range(horizon_h)]


def net_of_backlog(forecast_kwh_el: list[float], backlog_kwh_el: float) -> list[float]:
    """Consume `backlog_kwh_el` from the earliest hours of the forecast."""
    out, left = [], max(0.0, backlog_kwh_el)
    for c in forecast_kwh_el:
        take = min(c, left)
        left -= take
        out.append(c - take)
    return out


def _check_forecast(fc: dict[str, list[float]]) -> None:
    for sid, xs in fc.items():
        for i, x in enumerate(xs):
            if not (isinstance(x, (int, float)) and math.isfinite(x) and x >= 0):
                raise InvalidInput(f"capacity forecast for {sid} hour +{i} must be finite and >= 0, got {x!r}")


def admit(job_units: list[Unit], sites: list[SiteState], hour: int,
          capacity_forecast_kwh_el: dict[str, list[float]], params: Params) -> Admission:
    """capacity_forecast_kwh_el[site_id][i] = conservative electric kWh available in hour `hour + i`."""
    validate_params(params)
    validate_sites(sites)
    validate_queue(job_units)
    _check_forecast(capacity_forecast_kwh_el)
    if not job_units:
        return Admission(False, R_EMPTY, None)
    jobs = {u.job_id for u in job_units}
    classes = {u.access_class for u in job_units}
    if len(jobs) != 1 or len(classes) != 1:
        raise InvalidInput(f"admit() takes the units of exactly one job; got jobs {sorted(jobs)}, classes {sorted(classes)}")
    access = next(iter(classes))
    elig = sorted(s.site_id for s in sites if access in s.eligible_classes)
    if not elig:
        return Admission(False, R_NO_ELIGIBLE, None)

    need = sum(u.kwh_el for u in job_units)
    deadline = min(u.deadline_hour for u in job_units)
    latest_finish = deadline - params.deadline_safety_h
    horizon = max((len(capacity_forecast_kwh_el.get(s, [])) for s in elig), default=0)

    got = 0.0
    for i in range(horizon):
        got += sum(capacity_forecast_kwh_el[s][i] for s in elig if i < len(capacity_forecast_kwh_el.get(s, [])))
        if got >= need - 1e-9:
            finish = hour + i + 1
            if finish <= latest_finish + 1e-9:
                return Admission(True, R_OK, finish)
            return Admission(False, R_DEADLINE, finish)
        if hour + i + 1 > latest_finish + 1e-9:
            return Admission(False, R_DEADLINE, None)
    return Admission(False, R_HORIZON, None)
