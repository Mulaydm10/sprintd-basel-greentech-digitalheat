"""Load and validate data/assumptions.yaml (single source of truth for all numbers).

`load_assumptions()` validates on load (#38, red team F13-F16): a bad or incomplete file fails here with one
typed `ConfigError` that names the key, instead of a raw ZeroDivisionError/KeyError (or a silently wrong
number) deep inside a lane. `validate_assumptions(a)` is the same check for callers that build or modify a
dict in memory (sweeps, tests); it never mutates or repairs `a`.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """assumptions.yaml (or an assumptions dict) is missing a key or holds an invalid value."""


# Sections and keys some lane reads. Optional/metadata keys (sources, notes, ranges) are not listed.
REQUIRED: dict[str, tuple[str, ...]] = {
    "location": ("lat", "lon", "tz", "year"),
    "house": ("design_kw", "t_base_c", "t_design_span_c", "heating_day_mean_t_c", "hot_water_kwh_per_day",
              "tank_kwh"),
    "server": ("electric_kw", "heat_recovery_fraction"),
    "price": ("chf_per_kwh", "heat_value_divisor"),
    "scheduler": ("eta_heat_used", "tank_band_low_kwh", "tank_band_high_kwh", "unit_minutes", "deadline_safety_h",
                  "migration_margin_chf"),
    "hardware": ("capex_chf_per_server", "life_years"),
    "ballast": ("bid_chf_per_server_h",),
}

# (section, key) -> rule. "pos": finite > 0; "nonneg": finite >= 0; "frac": finite in [0, 1]; "finite": any real.
RULES: dict[tuple[str, str], str] = {
    ("location", "lat"): "finite", ("location", "lon"): "finite",
    ("house", "design_kw"): "nonneg", ("house", "t_base_c"): "finite", ("house", "t_design_span_c"): "pos",
    ("house", "heating_day_mean_t_c"): "finite", ("house", "hot_water_kwh_per_day"): "nonneg",
    ("house", "tank_kwh"): "nonneg",
    ("server", "electric_kw"): "pos", ("server", "heat_recovery_fraction"): "frac",
    ("price", "chf_per_kwh"): "nonneg", ("price", "heat_value_divisor"): "pos",  # F13 (0), F14 (< 0)
    ("scheduler", "eta_heat_used"): "frac", ("scheduler", "tank_band_low_kwh"): "nonneg",
    ("scheduler", "tank_band_high_kwh"): "nonneg", ("scheduler", "unit_minutes"): "pos",  # F15
    ("scheduler", "deadline_safety_h"): "nonneg", ("scheduler", "migration_margin_chf"): "nonneg",
    ("hardware", "capex_chf_per_server"): "nonneg", ("hardware", "life_years"): "pos",
    ("ballast", "bid_chf_per_server_h"): "nonneg",
}
_RULE_TEXT = {"pos": "finite and > 0", "nonneg": "finite and >= 0", "frac": "finite and in [0, 1]",
              "finite": "finite"}

# Per-job keys and rules (jobs: list may be empty; each entry must be complete).
JOB_RULES: dict[str, str] = {"runtime_h": "pos", "deadline_h": "pos", "price_chf_per_h": "nonneg",
                             "jobs_per_day": "nonneg"}
JOB_KEYS: tuple[str, ...] = ("name", "interruptible", "access_class", *JOB_RULES)


def _number(where: str, v: Any, rule: str) -> float:
    # bool is an int subclass: `true` in YAML is not a number.
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError(f"{where} must be a number ({_RULE_TEXT[rule]}), got {v!r}")
    x = float(v)
    ok = math.isfinite(x) and {"pos": x > 0, "nonneg": x >= 0, "frac": 0 <= x <= 1, "finite": True}[rule]
    if not ok:
        raise ConfigError(f"{where} must be {_RULE_TEXT[rule]}, got {v!r}")
    return x


def _section(a: dict, name: str) -> dict:
    if name not in a:
        raise ConfigError(f"missing section `{name}`")
    s = a[name]
    if not isinstance(s, dict):
        raise ConfigError(f"`{name}` must be a mapping, got {type(s).__name__}")
    return s


def validate_assumptions(a: Any) -> dict:
    """Check an assumptions dict; return it unchanged or raise ConfigError naming the first bad key."""
    if not isinstance(a, dict):
        raise ConfigError(f"assumptions must be a mapping, got {type(a).__name__}")
    for name, keys in REQUIRED.items():
        s = _section(a, name)
        for k in keys:
            if k not in s:
                raise ConfigError(f"missing key `{name}.{k}`")
    for (name, k), rule in RULES.items():
        _number(f"{name}.{k}", a[name][k], rule)

    if not isinstance(a["location"]["tz"], str) or not a["location"]["tz"]:
        raise ConfigError(f"location.tz must be a non-empty string, got {a['location']['tz']!r}")
    sch = a["scheduler"]
    if sch["tank_band_low_kwh"] > sch["tank_band_high_kwh"]:
        raise ConfigError(f"scheduler.tank_band_low_kwh ({sch['tank_band_low_kwh']}) > "
                          f"tank_band_high_kwh ({sch['tank_band_high_kwh']})")
    if sch["tank_band_high_kwh"] > a["house"]["tank_kwh"]:
        raise ConfigError(f"scheduler.tank_band_high_kwh ({sch['tank_band_high_kwh']}) > "
                          f"house.tank_kwh ({a['house']['tank_kwh']})")
    for v in a["hardware"].get("capex_range_chf", []) or []:
        _number("hardware.capex_range_chf[]", v, "nonneg")

    jobs = a.get("jobs", [])
    if not isinstance(jobs, list):
        raise ConfigError(f"`jobs` must be a list, got {type(jobs).__name__}")
    names: set[str] = set()
    for i, j in enumerate(jobs):
        if not isinstance(j, dict):
            raise ConfigError(f"jobs[{i}] must be a mapping")
        for k in JOB_KEYS:
            if k not in j:
                raise ConfigError(f"missing key `jobs[{i}].{k}`")
        if j["name"] in names:
            raise ConfigError(f"duplicate job name {j['name']!r}")
        names.add(j["name"])
        for k, rule in JOB_RULES.items():
            _number(f"jobs[{i}].{k}", j[k], rule)

    _check_ballast_bid(a)
    return a


def ballast_bid_bounds(a: dict) -> tuple[float, float]:
    """(MC_used, MC_dump) per server-hour at the configured price (contract v2 rule 2, scheduler/policy.py).

    MC_dump = p_el * kW_el; MC_used = MC_dump - heat_recovery * kW_el * (p_el / heat_value_divisor).
    """
    p = float(a["price"]["chf_per_kwh"])
    kw = float(a["server"]["electric_kw"])
    hr = float(a["server"]["heat_recovery_fraction"])
    mc_dump = p * kw
    return mc_dump - hr * kw * p / float(a["price"]["heat_value_divisor"]), mc_dump


def _check_ballast_bid(a: dict) -> None:
    """Ballast runs only where MC_used <= bid < MC_dump; outside that it either never runs or burns money."""
    bid = float(a["ballast"]["bid_chf_per_server_h"])
    lo, hi = ballast_bid_bounds(a)
    if not lo <= bid < hi:
        raise ConfigError(f"ballast.bid_chf_per_server_h {bid} must satisfy MC_used {lo:.4f} <= bid < "
                          f"MC_dump {hi:.4f} at price.chf_per_kwh {a['price']['chf_per_kwh']}")


def load_assumptions(path: Path | None = None) -> dict:
    """Read and validate assumptions.yaml. Raises ConfigError on a missing key or invalid value."""
    p = path or ROOT / "data" / "assumptions.yaml"
    with open(p) as f:
        try:
            a = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"{p}: not valid YAML: {e}") from e
    return validate_assumptions(a)
