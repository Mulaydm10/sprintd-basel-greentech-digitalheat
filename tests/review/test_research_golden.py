# Design-owned end-to-end check: the built pipeline must reproduce every research number we will
# quote (research/briefing/numbers.json, Run B FINDINGS, design/PLAN). Skips cleanly until a lane lands.
import json, pathlib, subprocess, sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLD = json.loads((ROOT / "research/briefing/numbers.json").read_text())
FOLLOW = {int(r["N"]): r for r in GOLD["sweep"]["follow"]}
ALWAYS = {int(r["N"]): r for r in GOLD["sweep"]["always"]}


def _profile():
    hm = pytest.importorskip("house_model.profile")
    return hm.load_reference_profile()


def test_house_model_matches_briefing():
    df = _profile()
    assert len(df) == 8760
    assert abs(df.space_heat_kw.sum() - GOLD["space"]) / GOLD["space"] < 0.002
    assert abs(df.demand_kw.sum() - GOLD["total"]) / GOLD["total"] < 0.002
    assert int(df.heating_day.resample("D").first().sum()) == GOLD["heating_days"]
    assert round(df.temp_c.min(), 1) == GOLD["tmin"]
    assert abs(df.demand_kw.max() - GOLD["peak"]) < 0.05
    for k, v in GOLD["hours_above"].items():
        assert abs(int((df.demand_kw > float(k) * 0.8).sum()) - v) <= 2, k


def _balance(tmp_path, *args):
    pytest.importorskip("simulate_year")
    out = tmp_path / "run"
    subprocess.run([sys.executable, "-m", "simulate_year", *args, "--out", str(out)], check=True, cwd=ROOT,
                   env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"})
    return json.loads((out / "balance.json").read_text())


@pytest.mark.parametrize("N", [1, 2, 4, 6, 8, 10])
def test_thermostat_reproduces_briefing(tmp_path, N):
    b = _balance(tmp_path, "--servers", str(N), "--policy", "thermostat")
    g = FOLLOW[N]
    assert abs(b["share_covered"] - g["covered"]) < 0.003
    assert abs(b["utilisation"] - g["util"]) < 0.003
    assert abs(b["break_even_chf_per_server_h"] - g["be"]) < 0.0005
    assert b["heat_dumped_kwh"] < 1


@pytest.mark.parametrize("N", [1, 4, 8])
def test_always_on_reproduces_briefing(tmp_path, N):
    b = _balance(tmp_path, "--servers", str(N), "--policy", "always_on", "--load", "1.0")
    g = ALWAYS[N]
    assert abs(b["heat_dumped_kwh"] - g["dump"]) / max(g["dump"], 1) < 0.01
    assert abs(b["break_even_chf_per_server_h"] - g["be"]) < 0.0005


def test_patience_is_a_battery_run_b(tmp_path):
    """Run B: 24 h slack ~ -7% dump, 7 d ~ -19.5% (we measured -6.9% / -16.6% at N=4, load 0.6)."""
    d0 = _balance(tmp_path / "a", "--servers", "4", "--policy", "merit", "--slack-h", "0", "--load", "0.6")["heat_dumped_kwh"]
    d1 = _balance(tmp_path / "b", "--servers", "4", "--policy", "merit", "--slack-h", "24", "--load", "0.6")["heat_dumped_kwh"]
    d7 = _balance(tmp_path / "c", "--servers", "4", "--policy", "merit", "--slack-h", "168", "--load", "0.6")["heat_dumped_kwh"]
    assert d7 < d1 < d0
    assert 0.04 < 1 - d1 / d0 < 0.10
    assert 0.12 < 1 - d7 / d0 < 0.25
