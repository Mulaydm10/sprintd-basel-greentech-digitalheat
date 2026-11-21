"""Input validation for decide() (#21, red team F1–F6). Raises InvalidInput; never repairs silently.

Validation runs at the top of decide(), not in the dataclass constructors: callers (sim, live agent,
red-team tests) build states freely, and decide() is the single gate that must never act on bad input.
"""
from __future__ import annotations

import math

from .types import InvalidInput, Params, SiteState, Unit

_INF = math.inf


def _finite(x) -> bool:
    try:
        return -_INF < x < _INF
    except TypeError:
        return False


def validate_params(p: Params) -> None:
    if not _finite(p.deadline_safety_h) or p.deadline_safety_h < 0:
        raise InvalidInput(f"params: deadline_safety_h must be finite and >= 0, got {p.deadline_safety_h}")


def validate_sites(sites: list[SiteState]) -> None:
    seen: set[str] = set()
    for s in sites:
        sid = s.site_id
        if sid in seen:
            raise InvalidInput(f"duplicate site_id {sid!r}")
        seen.add(sid)
        if not (_finite(s.server_kw_el) and s.server_kw_el > 0):  # F5
            raise InvalidInput(f"site {sid}: server_kw_el must be finite and > 0, got {s.server_kw_el}")
        if not (_finite(s.heat_recovery) and 0.0 <= s.heat_recovery <= 1.0):  # F4
            raise InvalidInput(f"site {sid}: heat_recovery must be in [0, 1], got {s.heat_recovery}")
        if not (_finite(s.band_low_kwh) and _finite(s.band_high_kwh) and s.band_low_kwh <= s.band_high_kwh):  # F6
            raise InvalidInput(f"site {sid}: need band_low_kwh <= band_high_kwh, got {s.band_low_kwh} > {s.band_high_kwh}")
        if not (isinstance(s.servers, int) and s.servers >= 0):
            raise InvalidInput(f"site {sid}: servers must be an int >= 0, got {s.servers!r}")
        for name in ("demand_kw", "dhw_demand_kw", "tank_level_kwh", "tank_cap_kwh"):
            v = getattr(s, name)
            if not (_finite(v) and v >= 0):
                raise InvalidInput(f"site {sid}: {name} must be finite and >= 0, got {v}")
        for name in ("p_el_chf_kwh", "heat_value_chf_kwh"):
            if not _finite(getattr(s, name)):
                raise InvalidInput(f"site {sid}: {name} must be finite, got {getattr(s, name)}")
        if s.night_cap_kw is not None and not (_finite(s.night_cap_kw) and s.night_cap_kw >= 0):
            raise InvalidInput(f"site {sid}: night_cap_kw must be None or finite >= 0, got {s.night_cap_kw}")


def validate_queue(queue: list[Unit]) -> None:
    """O(U). F1 negative/NaN kwh, F2 NaN bid, F3 duplicate unit_ids, plus NaN/negative slack.
    +inf bid is allowed ("pay any price"); eligibility still applies."""
    seen: set[str] = set()
    add = seen.add
    for u in queue:
        k = u.kwh_el
        if not (0.0 < k < _INF):  # also False for NaN
            raise InvalidInput(f"unit {u.unit_id}: kwh_el must be finite and > 0, got {k}")
        b = u.bid_chf_per_server_h
        if b != b:
            raise InvalidInput(f"unit {u.unit_id}: bid is NaN")
        if not u.slack_h >= 0:  # NaN or negative
            raise InvalidInput(f"unit {u.unit_id}: slack_h must be >= 0, got {u.slack_h}")
        add(u.unit_id)
    if len(seen) != len(queue):
        counts: dict[str, int] = {}
        for u in queue:
            counts[u.unit_id] = counts.get(u.unit_id, 0) + 1
        dups = sorted(i for i, c in counts.items() if c > 1)
        raise InvalidInput(f"duplicate unit_id(s): {dups[:5]}{' ...' if len(dups) > 5 else ''}")
