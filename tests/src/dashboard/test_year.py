"""#96: the 07 Year tab: /api/year + /api/year/sizing over Y1's yearview-v1 cache, and the page in the site + Nav."""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dashboard.app as dash
from dashboard import site_build

HOURS = 48
PAGE = "DigitalHeat 07 Year.dc.html"


def summary(cov: float, dump: float, missed: float, above: float) -> dict:
    return {"coverage_pct": cov, "heat_demand_kwh": 100.0, "heat_used_kwh": cov, "dumped_kwh": dump, "backup_kwh": 100 - cov,
            "run_h": 40.0, "paid_run_h": 30.0, "ballast_run_h": 10.0, "utilisation_pct": 80.0, "missed_pct": missed,
            "electricity_cost_chf": 13.0, "heat_value_chf": 10.0, "compute_income_chf": 15.0, "ballast_income_chf": 2.5,
            "net_chf_excl_hardware": 14.5, "break_even_chf_per_server_h": 0.25, "break_even_incl_hardware_chf_per_server_h": 0.47,
            "pays_off_above_chf_per_server_h": above, "pays_off": above <= 0.5, "pays_off_conditions": "text"}


def series(n: int) -> dict:
    return {"heat_used_kwh": [0.8 * n] * HOURS, "dumped_kwh": [0.0] * HOURS, "backup_kwh": [1.0] * HOURS,
            "tank_kwh": [10.0] * HOURS, "servers_on": [n] * HOURS, "paused": [0] * HOURS, "units_done": [4] * HOURS,
            "ballast_units": [0] * HOURS, "missed": [0] * HOURS, "net_chf_cum": [0.3 * i for i in range(HOURS)],
            "heat_used_kwh_cum": [0.8 * n * (i + 1) for i in range(HOURS)]}


def write_fixture(d: Path, key: str = "k1") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    prov = {"key": key, "assumptions_hash": "a" * 64, "profile": "data/raw/basel_2025_hourly.csv", "commit": "c",
            "generated_at": "2026-11-21T20:00:00Z"}
    settings = {"servers": list(range(1, 9)), "ours": {"policy": "merit", "ballast": True, "slack_h": 24, "load": 0.6},
                "baseline": {"policy": "thermostat", "ballast": False, "slack_h": 24, "load": 0.6},
                "paid_price_chf_per_server_h": 0.5, "capex_chf_per_server": 8000, "life_years": 5, "max_dump_share": 0.1,
                "constants": {"tank_kwh": 35.0, "price_chf_per_kwh": 0.3325, "heat_value_divisor": 2.5}}
    by_n = [{"n": n, "ours": summary(20.0 * n, n, 0.0, 0.5 + n / 100), "baseline": summary(20.0 * n, 0, 5.0 * n, 0.7)}
            for n in range(1, 9)]
    (d / "index.json").write_text(json.dumps({"schema": "yearview-v1", "provenance": prov, "settings": settings, "by_n": by_n,
                                              "sizing": {"recommended_n": 3, "reason": "r", "lowest_break_even_n": 1,
                                                         "lowest_break_even_chf_per_server_h": 0.51,
                                                         "lowest_break_even_reason": "x", "rule": "rule"}}))
    for n in range(1, 9):
        (d / f"n{n}.json").write_text(json.dumps({
            "schema": "yearview-v1", "n": n, "provenance": prov, "start": "2025-01-01T00:00:00+01:00", "tz": "Europe/Zurich",
            "step_h": 1, "hours": HOURS, "summary": {"ours": by_n[n - 1]["ours"], "baseline": by_n[n - 1]["baseline"]},
            "weather": {"temp_c": [2.0] * HOURS, "demand_kwh": [5.0] * HOURS}, "ours": series(n), "baseline": series(n)}))
    return d


@pytest.fixture
def client():
    return TestClient(dash.app, client=("127.0.0.1", 5000))


@pytest.fixture
def yv(tmp_path, monkeypatch):
    d = write_fixture(tmp_path / "yearview" / "k1")
    monkeypatch.setenv("DH_YEARVIEW_DIR", str(d))
    return d


def test_sizing_and_year_are_served(client, yv):
    s = client.get("/api/year/sizing")
    assert s.status_code == 200 and s.json()["sizing"]["recommended_n"] == 3 and len(s.json()["by_n"]) == 8
    for n in (1, 4, 8):
        y = client.get(f"/api/year?n={n}").json()
        assert y["n"] == n and len(y["ours"]["servers_on"]) == y["hours"] == HOURS
    assert client.get("/api/year").json()["n"] == 4  # default N


@pytest.mark.parametrize("q", ["n=0", "n=9", "n=-1", "n=x", "n=4.5"])
def test_n_is_bounded(client, yv, q):
    assert client.get(f"/api/year?{q}").status_code == 422


def test_gzip_and_etag(client, yv):
    r = client.get("/api/year?n=4", headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip" and r.json()["n"] == 4  # httpx decodes it
    raw = (yv / "n4.json").read_bytes()
    assert len(gzip.compress(raw)) < len(raw)
    etag = r.headers["etag"]
    assert "k1" in etag and r.headers["cache-control"].startswith("public")
    again = client.get("/api/year?n=4", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    assert client.get("/api/year?n=5", headers={"If-None-Match": etag}).status_code == 200  # per-file etag


def test_latest_run_dir_is_used_without_env(client, monkeypatch, tmp_path):
    monkeypatch.delenv("DH_YEARVIEW_DIR", raising=False)
    import dashboard.year as year
    monkeypatch.setattr(year, "ROOT", tmp_path)
    assert client.get("/api/year/sizing").status_code == 404
    assert "simulate_year.yearview" in client.get("/api/year/sizing").json()["detail"]
    write_fixture(tmp_path / "runs" / "yearview" / "old", key="old")
    import os
    import time
    time.sleep(0.01)
    new = write_fixture(tmp_path / "runs" / "yearview" / "new", key="new")
    os.utime(new / "index.json", None)
    assert client.get("/api/year/sizing").json()["provenance"]["key"] == "new"


def test_bad_files_are_502_not_500(client, yv):
    (yv / "n2.json").write_text("{not json")
    assert client.get("/api/year?n=2").status_code == 502
    (yv / "n3.json").write_text(json.dumps({"schema": "other"}))
    r = client.get("/api/year?n=3")
    assert r.status_code == 502 and "yearview-v1" in r.json()["detail"]
    (yv / "n5.json").unlink()
    assert client.get("/api/year?n=5").status_code == 404


def test_year_page_is_served_offline_and_in_nav(client):
    r = client.get("/" + PAGE)
    assert r.status_code == 200
    html = r.text
    assert "./vendor/resources.js" in html and "./vendor/fonts/fonts.css" in html
    assert not re.findall(r"""(?:src|href)=["']https?://""", html)
    assert "/api/year/sizing" in html and "/api/year?n=" in html and "navActive: 7" in html
    nav = client.get("/Nav.dc.html").text
    assert '["07", "Year", "DigitalHeat%2007%20Year.dc.html"]' in nav and "&quot;max&quot;:7," in nav


def test_page_uses_only_api_numbers():
    """No invented figures in the page source: every number shown comes from /api/year*; the only literals are UI
    constants (months, colours, speeds, the 8 760-hour default)."""
    html = (site_build.EXTRA / PAGE).read_text(encoding="utf-8")
    js = html.split("data-dc-script", 1)[1]
    for banned in ("57.9", "0.552", "0.533", "31,231", "26851", "0.3325", "2.5;"):
        assert banned not in js, banned
