"""#38: validated assumptions loader (red team F13-F16)."""
from __future__ import annotations

import copy

import pytest
import yaml

from common.config import (REQUIRED, ROOT, ConfigError, ballast_bid_bounds, load_assumptions,
                           validate_assumptions)

A = load_assumptions()


def _with(section: str, key: str, value) -> dict:
    a = copy.deepcopy(A)
    a[section][key] = value
    return a


def test_shipped_file_is_valid_and_unchanged():
    raw = yaml.safe_load((ROOT / "data" / "assumptions.yaml").read_text())
    assert load_assumptions() == raw  # validation never repairs or adds keys


def test_validate_returns_same_object_and_does_not_mutate():
    a = copy.deepcopy(A)
    before = copy.deepcopy(a)
    assert validate_assumptions(a) is a
    assert a == before


def test_config_error_is_a_value_error():
    assert issubclass(ConfigError, ValueError)


@pytest.mark.parametrize("section", sorted(REQUIRED))
def test_missing_section_names_it(section):  # F16
    a = copy.deepcopy(A)
    del a[section]
    with pytest.raises(ConfigError, match=f"`{section}`"):
        validate_assumptions(a)


@pytest.mark.parametrize("section,key", [(s, k) for s, ks in REQUIRED.items() for k in ks])
def test_missing_key_names_it(section, key):  # F16
    a = copy.deepcopy(A)
    del a[section][key]
    with pytest.raises(ConfigError, match=f"`{section}.{key}`"):
        validate_assumptions(a)


@pytest.mark.parametrize("value", [0, 0.0, -2.5, float("nan"), float("inf")])
def test_heat_value_divisor_must_be_positive(value):  # F13, F14
    with pytest.raises(ConfigError, match="heat_value_divisor"):
        validate_assumptions(_with("price", "heat_value_divisor", value))


@pytest.mark.parametrize("value", [0, -15, float("nan")])
def test_unit_minutes_must_be_positive(value):  # F15
    with pytest.raises(ConfigError, match="unit_minutes"):
        validate_assumptions(_with("scheduler", "unit_minutes", value))


@pytest.mark.parametrize("section,key,value", [
    ("price", "chf_per_kwh", -0.01), ("price", "chf_per_kwh", float("nan")), ("price", "chf_per_kwh", "abc"),
    ("price", "chf_per_kwh", None), ("price", "chf_per_kwh", True),
    ("house", "tank_kwh", -5.0), ("house", "t_base_c", float("inf")),
    ("server", "electric_kw", 0), ("server", "heat_recovery_fraction", 1.5),
    ("scheduler", "eta_heat_used", -0.1), ("scheduler", "deadline_safety_h", -1),
    ("hardware", "life_years", 0), ("hardware", "capex_chf_per_server", -1),
    ("ballast", "bid_chf_per_server_h", float("nan")),
])
def test_bad_numbers_name_the_key(section, key, value):
    with pytest.raises(ConfigError, match=f"{section}.{key}"):
        validate_assumptions(_with(section, key, value))


def test_band_order_and_tank_fit():
    with pytest.raises(ConfigError, match="tank_band_low_kwh"):
        validate_assumptions(_with("scheduler", "tank_band_low_kwh", 34.0))
    with pytest.raises(ConfigError, match="house.tank_kwh"):
        validate_assumptions(_with("house", "tank_kwh", 30.0))


def test_ballast_bounds_match_scheduler_formula():
    lo, hi = ballast_bid_bounds(A)
    p, kw, hr, div = 0.3325, 1.0, 0.8, 2.5  # the shipped file's values
    assert hi == pytest.approx(p * kw)
    assert lo == pytest.approx(p * kw - hr * kw * p / div)
    assert lo <= A["ballast"]["bid_chf_per_server_h"] < hi


@pytest.mark.parametrize("bid", [0.20, 0.3325, 0.40])
def test_ballast_bid_outside_band_is_an_error(bid):
    with pytest.raises(ConfigError, match="ballast.bid_chf_per_server_h"):
        validate_assumptions(_with("ballast", "bid_chf_per_server_h", bid))


def test_ballast_band_follows_price():
    """At a lower price the band moves down; the same bid can fall out of it."""
    with pytest.raises(ConfigError, match="MC_dump"):
        validate_assumptions(_with("price", "chf_per_kwh", 0.20))


def test_jobs_are_checked():
    a = copy.deepcopy(A)
    a["jobs"] = []
    validate_assumptions(a)  # an empty catalogue is allowed (simulate_year handles it)
    a = copy.deepcopy(A)
    del a["jobs"][0]["deadline_h"]
    with pytest.raises(ConfigError, match=r"jobs\[0\].deadline_h"):
        validate_assumptions(a)
    a = copy.deepcopy(A)
    a["jobs"][1]["runtime_h"] = 0
    with pytest.raises(ConfigError, match=r"jobs\[1\].runtime_h"):
        validate_assumptions(a)
    a = copy.deepcopy(A)
    a["jobs"][1]["name"] = a["jobs"][0]["name"]
    with pytest.raises(ConfigError, match="duplicate"):
        validate_assumptions(a)


@pytest.mark.parametrize("doc", ["", "- just\n- a list\n", "price: [1, 2]\n", "price: {chf_per_kwh: 0.3\n"])
def test_load_rejects_malformed_files(tmp_path, doc):
    p = tmp_path / "a.yaml"
    p.write_text(doc)
    with pytest.raises(ConfigError):
        load_assumptions(p)
