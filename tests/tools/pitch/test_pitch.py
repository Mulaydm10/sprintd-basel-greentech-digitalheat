"""#47: pitch numbers + end-to-end proof that the dashboard shows exactly what simulate_year computed.

house_model (real CSV) -> jobs catalogue -> simulate_year run_one -> dashboard API (TestClient, DH_RUN_DIR)
must return the same numbers as balance.json, and every pitch number must equal its balance.json key.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from common.config import ROOT, load_assumptions
from jobs.catalogue import load_catalogue
from tools.pitch.numbers import (RUN_KEYS, assumed_paths, depends, fmt, numbers_for_card, numbers_for_run,
                                 render_markdown, section_assumed)

YAML = (ROOT / "data" / "assumptions.yaml").read_text()
SAMPLE = """\
price:
  chf_per_kwh: 0.33  # ElCom
  heat_value_divisor: 2.5
jobs:
  - name: a
    price_chf_per_h: 1.7
    source: "ASSUMED: placeholder"
  - name: b
    source: "measured"
ballast:  # filler
  bid_chf_per_server_h: 0.25   # ASSUMED
hardware:  # ASSUMED, unsourced
  capex_chf_per_server: 8000
"""


def test_assumed_paths_on_sample():
    assert assumed_paths(SAMPLE) == {"jobs[0]", "ballast.bid_chf_per_server_h", "hardware"}


def test_assumed_paths_on_real_yaml_cover_known_assumptions():
    a = assumed_paths(YAML)
    assert "hardware" in a and "ballast.bid_chf_per_server_h" in a
    jobs = load_assumptions()["jobs"]
    assert {f"jobs[{i}]" for i, j in enumerate(jobs) if "ASSUMED" in j["source"]} <= a
    assert not section_assumed(a, "price") and not section_assumed(a, "house")


def test_depends_rules():
    th = {"policy": "thermostat", "ballast": False}
    assert "jobs" not in depends(th, "share_covered") and "jobs" in depends(th, "missed_deadline_pct")
    assert "hardware" in depends(th, "break_even_incl_hardware_chf_per_server_h")
    assert {"hardware", "jobs"} <= set(depends(th, "pays_off_above_chf_per_server_h"))
    assert "ballast" not in depends(th, "ballast_run_h")  # implicit ballast: no bid involved
    me = {"policy": "merit", "ballast": True}
    assert {"jobs", "ballast"} <= set(depends(me, "share_covered"))


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Real year: thermostat + merit+ballast on the same paid stream, N=2 (fast, ~2 s)."""
    from simulate_year.cli import run_one
    root = tmp_path_factory.mktemp("runs")
    assert len(load_catalogue()) >= 2  # jobs lane feeds the paid stream
    out = {}
    for name, pol, bal in (("thermo", "thermostat", False), ("meritb", "merit", True)):
        out[name] = root / name
        run_one(2, pol, 24.0, "thermostat", 0, out[name], ballast=bal)
    return out


def test_pitch_numbers_equal_balance_and_flags(runs):
    a = assumed_paths(YAML)
    for name, d in runs.items():
        b = json.loads((d / "balance.json").read_text())
        nums = numbers_for_run(d, name, a, "sha", house=name == "thermo")
        assert {n.key for n in nums} >= {k for _l, k, _f in RUN_KEYS if k in b}
        for n in nums:
            assert n.value == b[n.key] and n.run_id == d.name and n.assumptions_hash == b["assumptions_hash"]
        by_key = {n.key: n for n in nums}
        assert "break_even_incl_hardware_chf_per_server_h" not in by_key  # #50: quote pays_off_above instead
        assert by_key["pays_off_above_chf_per_server_h"].assumed  # capex is ASSUMED
        assert {"hardware", "jobs[0]"} <= set(by_key["pays_off"].assumed_inputs) | {"jobs[0]"}
        if name == "thermo":
            assert not by_key["share_covered"].assumed  # heat physics only: not ASSUMED
            assert not by_key["heat_demand_kwh"].assumed
        else:
            assert "ballast.bid_chf_per_server_h" in by_key["share_covered"].assumed_inputs
    md = render_markdown(nums, {"code_sha": "abc", "assumptions_hash": "h", "runs_root": "r", "assumed": sorted(a)})
    assert md.count("\n| ") >= len(nums) and "**ASSUMED**" in md


@pytest.mark.parametrize("name", ["thermo", "meritb"])
def test_dashboard_api_shows_exactly_balance_json(runs, name, monkeypatch):
    """'Judges click any number': the dashboard API serves the run's numbers unchanged, with provenance."""
    from dashboard.app import app
    d = runs[name]
    monkeypatch.setenv("DH_RUN_DIR", str(d))
    b = json.loads((d / "balance.json").read_text())
    c = TestClient(app)
    assert c.get("/api/balance").json() == b
    prov = c.get("/api/provenance").json()
    assert prov["assumptions_hash"] == b["assumptions_hash"] and prov["run_id"] == d.name and not prov["fixture"]
    assert c.get("/api/day/january").json()["rows"], "hourly data reaches the day replay"


def test_like_for_like_view_matches_runs(runs, monkeypatch):
    from dashboard.app import app
    monkeypatch.setenv("DH_RUN_DIR", str(runs["meritb"]))
    rows = TestClient(app).get("/api/ab_like_for_like").json()["rows"]
    got = {r["run_id"]: r for r in rows}
    for d in runs.values():
        b = json.loads((d / "balance.json").read_text())
        assert got[d.name]["share_covered"] == b["share_covered"]
        assert got[d.name]["missed_deadline_pct"] == b["missed_deadline_pct"]


def test_fmt():
    assert fmt(0.5803, "pct") == "58.03%" and fmt(None, "pct") == "n/a" and fmt(9910.4, "kwh") == "9,910 kWh"
    assert fmt(True, "bool") == "yes" and fmt(False, "bool") == "no"


def test_card_numbers_trace_and_are_assumed(tmp_path):
    card = {"recommended_n": 1, "pays_off_above_chf_per_server_h": 0.5303, "assumptions_hash": "h", "basis": "x"}
    p = tmp_path / "pitch" / "decision_card.json"
    p.parent.mkdir()
    p.write_text(json.dumps(card))
    nums = numbers_for_card(p, assumed_paths(YAML), "sha")
    assert [(n.key, n.value) for n in nums] == [("recommended_n", 1), ("pays_off_above_chf_per_server_h", 0.5303)]
    assert all(n.assumed and n.run_id == "pitch" and n.file == "decision_card.json" for n in nums)


def test_cli_writes_markdown(tmp_path, monkeypatch):
    import tools.pitch.__main__ as pm
    monkeypatch.setattr(pm, "CANON", [("thermostat", "thermostat", False)])
    out = tmp_path / "PITCH.md"
    assert pm.main(["--out", str(out), "--runs", str(tmp_path / "runs"), "--servers", "1", "--no-card"]) == 0
    text = out.read_text()
    assert "annual heat demand" in text and "code sha" in text and "thermostat-n1" in text
