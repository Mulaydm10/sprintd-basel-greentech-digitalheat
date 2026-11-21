"""Year view (#95, schema yearview-v1): hourly arrays sum to the run's balance, the files are deterministic per key,
the sizing rule picks what it says, and a complete key folder is reused. Runs N=1..2 only (speed)."""
from __future__ import annotations

import json

import pytest

from simulate_year import yearview as yv

SERIES_TO_SUMMARY = {"heat_used_kwh": "heat_used_kwh", "dumped_kwh": "dumped_kwh", "backup_kwh": "backup_kwh",
                     "servers_on": "run_h"}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("yv")
    mp = pytest.MonkeyPatch()
    mp.setattr(yv, "SERVERS", (1, 2))
    d = yv.build(out, workers=4, log=lambda *_: None)
    yield out, d, mp
    mp.undo()


def load(d, name):
    return json.loads((d / name).read_text())


def test_files_and_schema(built):
    out, d, _ = built
    idx = load(d, "index.json")
    assert idx["schema"] == "yearview-v1" and [r["n"] for r in idx["by_n"]] == [1, 2]
    assert (out / "LATEST").read_text().strip() == d.name == idx["provenance"]["key"]
    assert yv.latest(out) == d
    st = idx["settings"]
    assert st["ours"]["policy"] == "merit" and st["ours"]["ballast"] and st["baseline"]["policy"] == "thermostat"
    assert st["baseline"]["load"] == st["ours"]["load"]  # like-for-like: the same paid work
    assert {"price_chf_per_kwh", "heat_value_divisor", "server_kw_el", "heat_recovery", "tank_kwh"} <= set(st["constants"])
    for f in ("balance.json", "hourly.csv", "sweep.csv"):
        assert (out / f).exists()
    doc = load(d, "n2.json")
    assert doc["hours"] == 8760 and doc["step_h"] == 1 and doc["start"].startswith("2025-01-01")
    for side in ("ours", "baseline"):
        assert set(doc[side]) == set(yv.SERIES) and all(len(v) == 8760 for v in doc[side].values())
    assert all(len(v) == 8760 for v in doc["weather"].values())


@pytest.mark.parametrize("n", [1, 2])
@pytest.mark.parametrize("side", ["ours", "baseline"])
def test_hourly_arrays_sum_to_the_summary(built, n, side):
    _, d, _ = built
    doc = load(d, f"n{n}.json")
    s, ser = doc["summary"][side], doc[side]
    tol = 8760 * 0.5 * 10 ** -yv.ND + 1e-3  # per-hour rounding to ND decimals
    for k, sk in SERIES_TO_SUMMARY.items():
        assert sum(ser[k]) == pytest.approx(s[sk], abs=tol), k
    assert ser["net_chf_cum"][-1] == pytest.approx(s["net_chf_excl_hardware"], abs=0.01)
    assert ser["heat_used_kwh_cum"][-1] == pytest.approx(s["heat_used_kwh"], abs=0.01)
    assert sum(doc["weather"]["demand_kwh"]) == pytest.approx(s["heat_demand_kwh"], abs=tol)
    assert max(ser["tank_kwh"]) <= load(d, "index.json")["settings"]["constants"]["tank_kwh"] + 1e-6
    assert set(ser["paused"]) <= {0, 1} and sum(ser["missed"]) >= 0


def test_sweep_csv_has_three_policies_per_n(built):
    out, _, _ = built
    import csv
    rows = list(csv.DictReader((out / "sweep.csv").open()))
    assert sorted({(r["servers_per_house"], r["policy"]) for r in rows}) == \
        sorted((str(n), p) for n in (1, 2) for p in ("merit", "thermostat", "always_on"))


def test_complete_key_is_reused_and_force_recomputes(built):
    out, d, _ = built
    before = (d / "n1.json").read_bytes()
    msgs = []
    assert yv.build(out, workers=2, log=msgs.append) == d and "reusing" in msgs[0]
    assert (d / "n1.json").read_bytes() == before


def test_deterministic_numbers(built, tmp_path):
    _, d, _ = built
    d2 = yv.build(tmp_path, workers=4, force=True, log=lambda *_: None)
    a, b = load(d, "n1.json"), load(d2, "n1.json")
    for x in (a, b):
        x["provenance"].pop("generated_at")
    assert a == b


def row(n, cov, dump, miss=0.0, above=0.6, demand=1000.0):
    return {"n": n, "ours": {"coverage_pct": cov, "dumped_kwh": dump, "missed_pct": miss, "heat_demand_kwh": demand,
                             "pays_off_above_chf_per_server_h": above, "pays_off": above <= 0.5}}


def test_sizing_rule():
    a = yv.load_assumptions()
    rows = [row(1, 20, 0, above=0.52), row(2, 40, 5), row(3, 60, 9), row(4, 60.05, 9.5), row(5, 80, 50)]
    s = yv.sizing(rows, a, max_dump_share=0.01)
    assert s["recommended_n"] == 3  # 4 adds < 0.1 pp; 5 dumps 5 %
    assert "N=3" in s["reason"] and "1%" in s["rule"]
    assert s["lowest_break_even_n"] == 1 and s["lowest_break_even_chf_per_server_h"] == 0.52
    assert yv.sizing(rows, a, max_dump_share=0.0)["recommended_n"] == 1
    assert yv.sizing([row(1, 20, 0, miss=1.0)], a)["recommended_n"] is None  # missed deadlines exclude N


def test_cache_key_changes_with_the_rule():
    assert yv.cache_key(0.01) != yv.cache_key(0.10)


def test_cli_rejects_bad_dump_share(tmp_path):
    with pytest.raises(SystemExit):
        yv.main(["--out", str(tmp_path), "--max-dump-share", "2"])
