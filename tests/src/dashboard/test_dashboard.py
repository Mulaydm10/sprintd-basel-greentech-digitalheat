"""Dashboard tests (contract v2): app starts, every endpoint 200 on the fixture, no figure hard-coded in templates."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import app as appmod

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DH_RUN_DIR", str(FIX))
    return TestClient(appmod.app)


@pytest.mark.parametrize("path", ["/", "/api/source", "/api/balance", "/api/sweep", "/api/ab", "/api/day/january",
                                  "/api/day/july", "/api/trust", "/api/decision", "/api/nodes"])
def test_every_endpoint_200_on_fixture(client, path):
    assert client.get(path).status_code == 200


def test_source_flags_fixture(client):
    assert client.get("/api/source").json()["fixture"] is True


def test_balance_has_contract_keys(client):
    keys = {"servers_per_house", "policy", "share_covered", "backup_heat_kwh", "heat_dumped_kwh",
            "break_even_chf_per_server_h", "break_even_incl_hardware_chf_per_server_h", "pays_off", "pays_off_conditions"}
    assert keys <= set(client.get("/api/balance").json())


def test_ab_has_three_policies_at_balance_n(client):
    ab = client.get("/api/ab").json()
    assert [r["policy"] for r in ab["rows"]] == ["thermostat", "always_on", "merit"]
    assert all(r["servers_per_house"] == ab["servers_per_house"] for r in ab["rows"])


def test_day_picks_coldest_january_and_24_hours(client):
    jan = client.get("/api/day/january").json()
    assert len(jan["rows"]) == 24 and jan["day_of_year"] == 10
    assert client.get("/api/day/july").json()["day_of_year"] == 196
    assert client.get("/api/day/march").status_code == 404


def test_trust_panel_is_labelled_mock_and_shows_a_denial(client):
    t = client.get("/api/trust").json()
    assert t["mock"] is True
    assert any(e["event"]["type"] == "deny" for e in t["entries"])
    if t["verified"] is not None:
        assert t["verified"] is True


def test_decision_states_rule_and_verdict(client):
    d = client.get("/api/decision").json()
    assert "rule" in d and d["chosen"]["servers_per_house"] >= 1 and isinstance(d["pays_off"], bool)


def test_nodes_stub_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("DH_LIVE_NODES", raising=False)
    assert client.get("/api/nodes").json()["enabled"] is False


def test_no_number_hard_coded_in_template():
    html = (Path(appmod.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    body = re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", body)
    assert not re.findall(r"\d", text), "figures must come from the API, not the template"


def test_parquet_without_engine_falls_back_or_explains(tmp_path, monkeypatch):
    (tmp_path / "hourly.csv").write_text((FIX / "hourly.csv").read_text())
    (tmp_path / "hourly.parquet").write_bytes(b"not really parquet")
    df = appmod.load_hourly(tmp_path)
    assert len(df) == 48


# ---------------------------------------------------------------- v3 (claim/9-v3)
@pytest.mark.parametrize("path", ["/api/provenance", "/api/ab_like_for_like", "/api/sensitivity", "/api/decision_card"])
def test_v3_endpoints_200_on_fixture(client, path):
    assert client.get(path).status_code == 200


def test_like_for_like_rows_are_same_n_and_thermostat_basis(client):
    lf = client.get("/api/ab_like_for_like").json()
    assert [r["policy"] for r in lf["rows"]] == ["thermostat", "always_on", "merit"]
    assert all(r["servers_per_house"] == lf["servers_per_house"] for r in lf["rows"])
    assert all(r["load_basis"] == "thermostat" for r in lf["rows"] if r["policy"] != "thermostat")
    assert lf["note"] is None


def test_sensitivity_sorted_by_swing_and_flagged_fixture(client):
    se = client.get("/api/sensitivity").json()
    swings = [r["swing"] for r in se["rows"]]
    assert se["fixture"] is True and swings == sorted(swings, reverse=True) and se["rows"][0]["parameter"] == "capex"


def test_decision_card_and_provenance(client):
    dc = client.get("/api/decision_card").json()
    assert dc["fixture"] is True and "recommended_n" in dc["card"]
    pv = client.get("/api/provenance").json()
    assert pv["fixture"] is True and pv["assumptions_hash"] and "balance.json" in pv["files"]


def test_real_run_dir_is_used_and_not_fixture(tmp_path, monkeypatch):
    import json as _j
    run = tmp_path / "runs" / "merit-n4-x"
    run.mkdir(parents=True)
    b = _j.loads((FIX / "balance.json").read_text())
    (run / "balance.json").write_text(_j.dumps(b | {"load_basis": "thermostat"}))
    monkeypatch.setenv("DH_RUN_DIR", str(run))
    c = TestClient(appmod.app)
    assert c.get("/api/provenance").json()["fixture"] is False
    assert c.get("/api/decision_card").json()["fixture"] is True  # falls back until #31


# ------------------------------------------------------------------ #55 hardening (red team F26-F30)
import shutil as _shutil

import dashboard.app as _dash


@pytest.fixture
def broken_run(tmp_path, monkeypatch):
    d = tmp_path / "runs" / "r1"
    d.mkdir(parents=True)
    for f in ("balance.json", "hourly.csv"):
        _shutil.copy(_dash.FIXTURE_DIR / f, d / f)
    monkeypatch.setenv("DH_RUN_DIR", str(d))
    return d


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", "", "\x00\xff"])
def test_corrupt_balance_is_422_with_message(broken_run, content):
    from fastapi.testclient import TestClient
    (broken_run / "balance.json").write_text(content, errors="ignore")
    c = TestClient(_dash.app, raise_server_exceptions=False)
    for p in ("/api/balance", "/api/ab", "/api/decision", "/api/provenance", "/api/ab_like_for_like"):
        r = c.get(p)
        assert r.status_code == 422 and "run incomplete or corrupt" in r.json()["detail"], (p, r.status_code)


def test_bad_sibling_run_is_skipped_and_listed(broken_run):
    from fastapi.testclient import TestClient
    bad = broken_run.parent / "half-written"
    bad.mkdir()
    (bad / "balance.json").write_text('{"policy": "merit", "servers_per')
    r = TestClient(_dash.app).get("/api/ab_like_for_like").json()
    assert r["skipped"] == ["half-written"]


@pytest.mark.parametrize("csv", ["hour,x\n0,1\n", "hour,demand,dump\na,1,2\n", ""])
def test_malformed_hourly_is_422(broken_run, csv):
    from fastapi.testclient import TestClient
    (broken_run / "hourly.csv").write_text(csv)
    r = TestClient(_dash.app, raise_server_exceptions=False).get("/api/day/january")
    assert r.status_code == 422 and "run incomplete" in r.json()["detail"]


def test_sensitivity_drops_non_numeric_rows(broken_run):
    from fastapi.testclient import TestClient
    (broken_run / "sensitivity.csv").write_text(
        "parameter,low,high,metric,metric_low,metric_high,metric_base\nx,1,2,m,abc,1,0.5\ny,1,2,m,0.4,0.6,0.5\n")
    r = TestClient(_dash.app).get("/api/sensitivity").json()
    assert r["skipped_rows"] == 1 and [row["parameter"] for row in r["rows"]] == ["y"]


def test_decision_ranks_by_pays_off_above_and_reports_its_verdict(broken_run):
    """F30: the lower run-hour break-even must not win when the paid price needed is higher."""
    from fastapi.testclient import TestClient
    import pandas as pd
    pd.DataFrame([
        {"policy": "merit", "servers_per_house": 4, "share_covered": 0.58, "heat_dumped_kwh": 5000,
         "missed_deadline_pct": 0, "break_even_incl_hardware_chf_per_server_h": 0.47,
         "pays_off_above_chf_per_server_h": 0.53, "pays_off": False},
        {"policy": "merit", "servers_per_house": 1, "share_covered": 0.13, "heat_dumped_kwh": 0,
         "missed_deadline_pct": 0, "break_even_incl_hardware_chf_per_server_h": 0.53,
         "pays_off_above_chf_per_server_h": 0.52, "pays_off": False},
    ]).to_csv(broken_run / "sweep.csv", index=False)
    d = TestClient(_dash.app).get("/api/decision").json()
    assert "pays_off_above" in d["rule"]
    assert d["chosen"]["servers_per_house"] == 1 and d["chosen"]["pays_off_above_chf_per_server_h"] == 0.52
    assert d["chosen"]["pays_off"] in (False, "False")


def test_decision_with_pre_50_sweep_ranks_nothing_and_says_why(broken_run):
    from fastapi.testclient import TestClient
    import pandas as pd
    pd.DataFrame([{"policy": "merit", "servers_per_house": 4, "break_even_incl_hardware_chf_per_server_h": 0.47}]
                 ).to_csv(broken_run / "sweep.csv", index=False)
    d = TestClient(_dash.app).get("/api/decision").json()
    assert d["chosen"] is None and "predates #50" in d["rule"]
