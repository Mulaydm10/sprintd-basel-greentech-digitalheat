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
