"""house_model tests (contracts/src/house_model.md).

Offline: the parsing/formula tests run on a committed 3-day fixture cut from the real Open-Meteo
export (Jan 1 cold, Jul 1 warm, Oct 26 DST end). The full-year invariants run only when
data/raw/basel_2025_hourly.csv exists (gitignored; `python -m house_model.fetch`).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from common.config import load_assumptions
from house_model import Tank, heating_demand_kw, load_reference_profile, server_heat_kw
from house_model.fetch import build_url
from house_model.profile import COLUMNS, DEFAULT_CSV

A = load_assumptions()
H = A["house"]
X = A["expected_checks"]
FIXTURE = Path(__file__).parent / "fixtures" / "basel_3days.csv"
full_year = pytest.mark.skipif(not DEFAULT_CSV.exists(), reason="full CSV absent; run python -m house_model.fetch")


# ------------------------------------------------------------------ formula
def test_no_demand_off_heating_day():
    assert heating_demand_kw(0.0, False) == 0.0


def test_design_point_gives_design_kw():
    t_design = H["t_base_c"] - H["t_design_span_c"]
    assert heating_demand_kw(t_design, True) == pytest.approx(H["design_kw"])


def test_no_negative_demand_above_base():
    assert heating_demand_kw(H["t_base_c"] + 5, True) == 0.0


def test_server_heat():
    assert server_heat_kw(A["server"]["electric_kw"]) == pytest.approx(
        A["server"]["electric_kw"] * A["server"]["heat_recovery_fraction"])


# ------------------------------------------------------------------ profile on fixture
@pytest.fixture(scope="module")
def fx() -> pd.DataFrame:
    return load_reference_profile(FIXTURE)


def test_fixture_shape_and_columns(fx):
    assert list(fx.columns) == COLUMNS
    assert len(fx) == 72
    assert str(fx.index.tz) == "Europe/Zurich"
    assert fx.index.is_unique and fx.index.is_monotonic_increasing


def test_dst_end_day_has_unique_hours(fx):
    oct26 = fx[fx.index.date == pd.Timestamp("2025-10-26").date()]
    assert oct26.index.is_unique  # fixed-offset export -> no ambiguous local hour after conversion


def test_heating_day_flags(fx):
    by_day = fx.groupby(fx.index.date)["heating_day"].first()
    jan1, jul1 = pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-07-01").date()
    assert bool(by_day[jan1]) is True
    assert bool(by_day[jul1]) is False


def test_space_heat_matches_formula(fx):
    for _, r in fx.iterrows():
        assert r.space_heat_kw == pytest.approx(heating_demand_kw(r.temp_c, bool(r.heating_day), H))


def test_hot_water_and_demand(fx):
    assert (fx.hot_water_kw == H["hot_water_kwh_per_day"] / 24).all()
    assert (fx.demand_kw == fx.space_heat_kw + fx.hot_water_kw).all()


def test_missing_csv_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="house_model.fetch"):
        load_reference_profile(tmp_path / "nope.csv")


def test_fetch_url_from_assumptions():
    url = build_url(A)
    assert "archive-api.open-meteo.com" in url
    assert f"start_date={A['location']['year']}-01-01" in url
    assert "timezone=auto" in url


# ------------------------------------------------------------------ full-year invariants
@full_year
def test_full_year_invariants():
    df = load_reference_profile()
    assert len(df) == 8760
    assert df.index.is_unique
    days = df.groupby(df.index.date)["heating_day"].first()
    assert int(days.sum()) == X["heating_days"]
    assert df.space_heat_kw.sum() == pytest.approx(X["verified_annual_heating_kwh"], rel=0.01)
    assert df.temp_c.min() == pytest.approx(-5.6)


# ------------------------------------------------------------------ tank
def test_tank_default_capacity_from_assumptions():
    assert Tank().capacity_kwh == H["tank_kwh"]


def test_tank_charge_and_draw_clamp():
    t = Tank(level_kwh=H["tank_kwh"] - 1.0)
    assert t.charge(3.0) == pytest.approx(1.0)
    assert t.level_kwh == pytest.approx(H["tank_kwh"])
    assert t.draw(H["tank_kwh"] + 5) == pytest.approx(H["tank_kwh"])
    assert t.level_kwh == 0.0
    assert t.draw(1.0) == 0.0


def test_tank_never_out_of_bounds_random_walk():
    import random
    rng = random.Random(0)
    t = Tank()
    for _ in range(10_000):
        x = rng.uniform(0, H["tank_kwh"] / 3)
        (t.charge if rng.random() < 0.5 else t.draw)(x)
        assert 0.0 <= t.level_kwh <= t.capacity_kwh


def test_tank_lossless_conservation():
    t = Tank()
    acc = t.charge(10.0)
    got = t.draw(4.0)
    assert t.level_kwh == pytest.approx(acc - got)


@pytest.mark.parametrize("bad", [dict(capacity_kwh=-1), dict(capacity_kwh=5, level_kwh=6), dict(level_kwh=-1)])
def test_tank_rejects_bad_init(bad):
    with pytest.raises(ValueError):
        Tank(**bad)


def test_tank_rejects_negative_flows():
    t = Tank()
    with pytest.raises(ValueError):
        t.charge(-1)
    with pytest.raises(ValueError):
        t.draw(-1)
