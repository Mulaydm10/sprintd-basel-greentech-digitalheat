"""Admission check at submit time (contracts/src/scheduler.md §v2.2, from research #29; hardened in #54).

Pure and separate from decide(). A job is accepted only if its eligible sites' *conservative* capacity
can finish it by its deadline with at least `params.deadline_safety_h` of margin, **without making any
already-admitted unit (the `backlog`) late**; otherwise it is rejected at submit with a reason. This is an
honesty gate, not a cost optimiser (Run B S1-SMART: greedy dispatch already equals the hindsight optimum).

Timing convention (same as decide/simulate_year): work placed in hour h finishes at h + 1, and a unit
with deadline_hour d must finish by d. With the margin: finish <= d - deadline_safety_h.

Feasibility (#54, red team F20/F22): an earliest-deadline-first replay of backlog + job over the forecast.
decide() serves units in deadline order, so EDF is the order the work will actually run in. Each hour a
unit runs on at most ONE eligible site and draws at most that site's kW (units are atomic: no splitting
across servers). The job's units sort after backlog units with the same deadline, so a job whose deadline
is not earlier than any backlog deadline cannot delay admitted work and one replay suffices; otherwise
the replay runs with and without the job and rejects it if any backlog unit would newly be late.

Conservative forecast helpers:
- `persistence_forecast(history, horizon)` repeats the last 24 h, 0-padded (never optimistic).
- `pessimistic_forecast(history, horizon, days)` takes, per hour of day, the MINIMUM over the last `days`
  days (the warmest recent day bounds heat-backed capacity from below), 0 for missing hours.
- `net_of_backlog(forecast, backlog_kwh)` removes committed work from the front of a forecast.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .types import InvalidInput, Params, SiteState, Unit
from .validate import validate_params, validate_queue, validate_sites

DAY_H = 24  # persistence period: the last day repeats (definition of the method, not an assumption)
EPS = 1e-9

R_OK = "admitted"
R_NO_ELIGIBLE = "no eligible site for access_class"
R_EMPTY = "job has no units"
R_DEADLINE = "cannot finish before deadline minus safety margin on conservative capacity"
R_HORIZON = "forecast horizon ends before the job could finish"
R_HARM = "would make already-admitted work miss its deadline"


@dataclass(frozen=True)
class Admission:
    accepted: bool
    reason: str
    earliest_finish_hour: int | None


def _finite(x, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise InvalidInput(f"{what} must be a finite number, got {x!r}")
    return float(x)


def _finite_nonneg(x, what: str) -> float:
    v = _finite(x, what)
    if v < 0:
        raise InvalidInput(f"{what} must be >= 0, got {x!r}")
    return v


def _horizon_ok(horizon_h) -> None:
    if isinstance(horizon_h, bool) or not isinstance(horizon_h, int) or horizon_h < 0:
        raise InvalidInput(f"horizon_h must be an int >= 0, got {horizon_h!r}")


def persistence_forecast(history_kwh_el: list[float], horizon_h: int) -> list[float]:
    """Repeat the last 24 hourly values; hours without history count as 0 capacity (negatives clip to 0)."""
    _horizon_ok(horizon_h)
    last = [max(0.0, _finite(x, "history value")) for x in history_kwh_el[-DAY_H:]]
    day = [0.0] * (DAY_H - len(last)) + last  # pad the oldest hours with 0 (conservative)
    return [day[i % DAY_H] for i in range(horizon_h)]


def pessimistic_forecast(history_kwh_el: list[float], horizon_h: int, days: int = 7) -> list[float]:
    """Per hour of day, the minimum over the last `days` days that have a value for that hour; 0 if none.
    Never above persistence_forecast: the last day is one of the days considered."""
    _horizon_ok(horizon_h)
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise InvalidInput(f"days must be an int >= 1, got {days!r}")
    hist = [max(0.0, _finite(x, "history value")) for x in history_kwh_el[-days * DAY_H:]]
    n = len(hist)
    out = []
    for i in range(horizon_h):
        k = i % DAY_H  # forecast hour (next hour + i) is the same hour of day as hist[n - d*24 + k]
        seen = [hist[n - d * DAY_H + k] for d in range(1, days + 1) if 0 <= n - d * DAY_H + k < n]
        out.append(min(seen) if seen else 0.0)  # min over the days that exist; never observed -> 0
    return out


def net_of_backlog(forecast_kwh_el: list[float], backlog_kwh_el: float) -> list[float]:
    """Consume `backlog_kwh_el` from the earliest hours of the forecast. NaN/inf/negative backlog is
    rejected (red team F23): a corrupt backlog must never free capacity."""
    left = _finite_nonneg(backlog_kwh_el, "backlog_kwh_el")
    out = []
    for c in forecast_kwh_el:
        c = _finite_nonneg(c, "forecast value")
        take = min(c, left)
        left -= take
        out.append(c - take)
    return out


def _check_forecast(fc: dict[str, list[float]]) -> None:
    for sid, xs in fc.items():
        for i, x in enumerate(xs):
            _finite_nonneg(x, f"capacity forecast for {sid} hour +{i}")  # bool/NaN/inf/negative (F25)


def _edf(units: list[Unit], sites: dict[str, tuple[float, frozenset[str]]], fc: dict[str, list[float]],
         hour: int, safety: float, horizon: int, targets: set[str] | None = None
         ) -> tuple[dict[str, int], set[str], set[str]]:
    """EDF replay of `units` (already in EDF order, so deadlines are non-decreasing). Returns (finish hour per
    finished unit, ids whose deadline - safety passed unfinished, ids still unfinished when the horizon ended).
    Cost per hour is the units served plus the late prefix, not the whole backlog. With `targets`, stops once
    they all finished."""
    remaining = {u.unit_id: u.kwh_el for u in units}
    finish: dict[str, int] = {}
    late: set[str] = set()
    open_units = list(units)
    left = set(targets) if targets is not None else None
    for i in range(horizon):
        if not open_units or (left is not None and not left):
            break
        now_end = hour + i + 1
        cap = {s: (fc[s][i] if i < len(fc.get(s, [])) else 0.0) for s in sites}
        still: list[Unit] = []
        j = 0
        while j < len(open_units):
            u = open_units[j]
            if now_end > u.deadline_hour - safety + EPS:  # its last usable hour is gone
                late.add(u.unit_id)
                j += 1
                continue
            if all(c <= EPS for c in cap.values()):
                still.extend(open_units[j:])  # capacity used up; the rest wait (deadlines are later)
                break
            best, take = None, 0.0
            for s, (kw, classes) in sites.items():  # one site per unit per hour, <= that site's kW (F22)
                if u.access_class in classes and cap[s] > EPS:
                    t = min(remaining[u.unit_id], cap[s], kw)
                    if t > take + EPS:
                        best, take = s, t
            if best is not None:
                cap[best] -= take
                remaining[u.unit_id] -= take
            if remaining[u.unit_id] <= EPS:
                finish[u.unit_id] = now_end
                if left is not None:
                    left.discard(u.unit_id)
            else:
                still.append(u)
            j += 1
        open_units = still
    return finish, late, {u.unit_id for u in open_units if u.unit_id not in finish}


def admit(job_units: list[Unit], sites: list[SiteState], hour: int,
          capacity_forecast_kwh_el: dict[str, list[float]], params: Params,
          backlog: Sequence[Unit] = ()) -> Admission:
    """capacity_forecast_kwh_el[site_id][i] = conservative electric kWh available in hour `hour + i`.
    `backlog` = already-admitted, unfinished units competing for the same sites (#54)."""
    validate_params(params)
    validate_sites(sites)
    validate_queue(job_units)
    validate_queue(list(backlog))
    if isinstance(hour, bool) or not isinstance(hour, int) or hour < 0:
        raise InvalidInput(f"hour must be an int >= 0, got {hour!r}")  # F25
    _check_forecast(capacity_forecast_kwh_el)
    if not job_units:
        return Admission(False, R_EMPTY, None)
    jobs = {u.job_id for u in job_units}
    classes = {u.access_class for u in job_units}
    if len(jobs) != 1 or len(classes) != 1:
        raise InvalidInput(f"admit() takes the units of exactly one job; got jobs {sorted(jobs)}, classes {sorted(classes)}")
    if {u.unit_id for u in job_units} & {u.unit_id for u in backlog}:
        raise InvalidInput("job units overlap the backlog")
    access = next(iter(classes))
    elig = {s.site_id: (s.server_kw_el, s.eligible_classes) for s in sites if access in s.eligible_classes}
    if not elig:
        return Admission(False, R_NO_ELIGIBLE, None)
    safety = params.deadline_safety_h
    deadline = min(u.deadline_hour for u in job_units)
    if deadline - safety < hour + 1 - EPS:  # not even one hour left: past or too-close deadline (F24)
        return Admission(False, R_DEADLINE, None)
    horizon = max((len(capacity_forecast_kwh_el.get(s, [])) for s in elig), default=0)
    if horizon == 0:
        return Admission(False, R_HORIZON, None)

    competing = [u for u in backlog if any(u.access_class in c for _kw, c in elig.values())]
    order = sorted([(u, False) for u in competing] + [(u, True) for u in job_units],
                   key=lambda t: (t[0].deadline_hour, t[1], t[0].unit_id))
    job_ids = {u.unit_id for u in job_units}
    finish, late, _open = _edf([u for u, _ in order], elig, capacity_forecast_kwh_el, hour, safety, horizon,
                               targets=job_ids)
    if not job_ids <= set(finish):
        # a job unit whose deadline passed in the replay -> deadline; otherwise the forecast simply ran out
        return Admission(False, R_DEADLINE if job_ids & late else R_HORIZON, None)
    job_finish = max(finish[i] for i in job_ids)
    if competing and deadline < max(u.deadline_hour for u in competing):
        # the job may run ahead of some admitted units: it must not make any of them newly late
        base = sorted(competing, key=lambda u: (u.deadline_hour, u.unit_id))
        _f0, late0, _o0 = _edf(base, elig, capacity_forecast_kwh_el, hour, safety, horizon)
        _f1, late1, _o1 = _edf([u for u, _ in order], elig, capacity_forecast_kwh_el, hour, safety, horizon)
        if (late1 - job_ids) - late0:
            return Admission(False, R_HARM, job_finish)
    return Admission(True, R_OK, job_finish)
