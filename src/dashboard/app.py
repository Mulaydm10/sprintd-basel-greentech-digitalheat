"""DigitalHeat dashboard (contract: contracts/src/dashboard.md v2).

Read-only FastAPI app + one static HTML page (no build step). Serve:  python -m dashboard  (port 8700).
Data source, in order: env DH_RUN_DIR, else the newest runs/<id>/ holding a balance.json, else the test
fixture (the page then shows a FIXTURE banner). No figure lives in the HTML: every number is fetched
from these endpoints and carries the balance.json key it came from.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from trust import KeyBroker, attest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "src" / "dashboard" / "fixtures"
STATIC = Path(__file__).resolve().parent / "static"
HOURS_PER_DAY = 24
JAN_HOURS = range(0, 31 * HOURS_PER_DAY)
JUL_HOURS = range(181 * HOURS_PER_DAY, 212 * HOURS_PER_DAY)  # non-leap year: Jul 1 = day 182

app = FastAPI(title="DigitalHeat dashboard")


def run_dir() -> Path:
    env = os.environ.get("DH_RUN_DIR")
    if env:
        return Path(env)
    runs = sorted((p.parent for p in (ROOT / "runs").glob("*/balance.json")), key=lambda p: p.stat().st_mtime)
    return runs[-1] if runs else FIXTURE_DIR


def _clean(v: Any) -> Any:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def load_balance(d: Path) -> dict[str, Any]:
    p = d / "balance.json"
    if not p.exists():
        raise HTTPException(404, f"no balance.json in {d}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_hourly(d: Path) -> pd.DataFrame:
    pq, csv = d / "hourly.parquet", d / "hourly.csv"
    if pq.exists():
        try:
            df = pd.read_parquet(pq)  # needs pyarrow or fastparquet
        except Exception as e:  # no engine (ImportError) or unreadable file (e.g. ArrowInvalid)
            if not csv.exists():
                raise HTTPException(500, f"cannot read hourly.parquet ({type(e).__name__}) and no hourly.csv fallback") from e
            df = pd.read_csv(csv)
    elif csv.exists():
        df = pd.read_csv(csv)
    else:
        raise HTTPException(404, f"no hourly.parquet/hourly.csv in {d}")
    if "hour" not in df.columns:
        df = df.reset_index(drop=True)
        df.insert(0, "hour", df.index)
    return df


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{k: _clean(v.item() if hasattr(v, "item") else v) for k, v in r.items()} for r in df.to_dict("records")]


def pick_day(df: pd.DataFrame, which: str) -> tuple[int, pd.DataFrame]:
    """January: the coldest day (max daily demand). July: the day with the most heat dumped
    (the summer problem); falls back to the first July day present."""
    df = df.copy()
    df["day"] = df["hour"] // HOURS_PER_DAY
    hours = JAN_HOURS if which == "january" else JUL_HOURS
    sub = df[df["hour"].isin(hours)]
    if sub.empty:
        raise HTTPException(404, f"no {which} hours in hourly data")
    col = "demand" if which == "january" else "dump"
    day = int(sub.groupby("day")[col].sum().idxmax())
    return day, sub[sub["day"] == day].drop(columns="day")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/source")
def source() -> dict[str, Any]:
    d = run_dir()
    return {"run_dir": str(d), "fixture": d.resolve() == FIXTURE_DIR.resolve()}


@app.get("/api/balance")
def balance() -> dict[str, Any]:
    return load_balance(run_dir())


@app.get("/api/sweep")
def sweep() -> list[dict[str, Any]]:
    p = run_dir() / "sweep.csv"
    if not p.exists():
        return []
    return _records(pd.read_csv(p))


@app.get("/api/ab")
def ab() -> dict[str, Any]:
    """thermostat vs always_on vs merit at the balance's N, slack and load (rows from sweep.csv)."""
    b = load_balance(run_dir())
    rows = sweep()
    keep = ("policy", "servers_per_house", "share_covered", "heat_dumped_kwh", "break_even_chf_per_server_h",
            "break_even_incl_hardware_chf_per_server_h", "missed_deadline_pct")
    out = []
    for pol in ("thermostat", "always_on", "merit"):
        cand = [r for r in rows if r.get("policy") == pol and r.get("servers_per_house") == b.get("servers_per_house")]
        for k in ("slack_h", "load"):
            narrowed = [r for r in cand if r.get(k) == b.get(k)]
            cand = narrowed or cand
        if cand:
            out.append({k: cand[0].get(k) for k in keep})
    return {"servers_per_house": b.get("servers_per_house"), "rows": out}


@app.get("/api/day/{which}")
def day(which: str) -> dict[str, Any]:
    if which not in ("january", "july"):
        raise HTTPException(404, "which must be january or july")
    d, df = pick_day(load_hourly(run_dir()), which)
    return {"which": which, "day_of_year": d + 1, "rows": _records(df)}


@app.get("/api/trust")
def trust_panel() -> dict[str, Any]:
    """Audit log + a denied example from src/trust (#10), labelled MOCK (attestation is a mock)."""
    b = KeyBroker()
    b.register_job("job-1", "canton-bs", "swiss-only")
    ev = {"measurement": next(iter(b.expected_measurements)), "certified": False}
    b.release("job-1", "BL-01", attest("BL-01", {**ev, "region": "CH-BL"}), "CH-BL")
    b.release("job-1", "FRA-1", attest("FRA-1", {**ev, "region": "DE-HE"}), "CH-BS")
    b.tamper("BL-01")
    b.release("job-1", "BL-01", attest("BL-01", {**ev, "region": "CH-BL"}), "CH-BL")
    entries = [{"index": e.index, "event": dict(e.event), "hash": e.hash, "prev_hash": e.prev_hash} for e in b.audit.entries]
    return {"mock": True, "source": "src/trust demo sequence", "verified": b.audit.verify(), "entries": entries}


@app.get("/api/decision")
def decision() -> dict[str, Any]:
    """Decision card: N with the lowest break-even incl. hardware for the merit policy (rule stated in
    the output), plus the run's pays_off verdict and its computed conditions."""
    b = load_balance(run_dir())
    rows = [r for r in sweep() if r.get("policy") == "merit"]

    def hw(r: dict[str, Any]) -> float:
        v = r.get("break_even_incl_hardware_chf_per_server_h")
        if isinstance(v, str):
            try:
                v = json.loads(v.replace("'", '"')).get("value")
            except (ValueError, AttributeError):
                v = None
        if isinstance(v, dict):
            v = v.get("value")
        return float(v) if v is not None else float("inf")

    best = min(rows, key=hw) if rows else None
    return {
        "rule": "lowest break_even_incl_hardware_chf_per_server_h among merit rows of sweep.csv",
        "chosen": None if best is None else {k: best.get(k) for k in ("servers_per_house", "share_covered",
                                                                       "heat_dumped_kwh", "missed_deadline_pct")}
        | {"break_even_incl_hardware_chf_per_server_h": hw(best)},
        "pays_off": b.get("pays_off"),
        "pays_off_conditions": b.get("pays_off_conditions"),
    }


@app.get("/api/nodes")
def nodes() -> dict[str, Any]:
    """Live nodes from #8 (GET /status). Stubbed behind DH_LIVE_NODES until #8 lands."""
    enabled = os.environ.get("DH_LIVE_NODES") == "1"
    return {"enabled": enabled, "nodes": [], "note": "stub until #8 live_agent exposes GET /status"}


# ================================================================ v3 (claim/9-v3): real runs, like-for-like A/B,
# sensitivity, decision card, per-number provenance. #31 outputs fall back to fixtures until it lands.
def _runs_root(d: Path) -> Path:
    """Where sibling runs live: the fixture's runs/ folder, else the run's parent (runs/)."""
    return FIXTURE_DIR / "runs" if d.resolve() == FIXTURE_DIR.resolve() else d.parent


def _git_commit() -> str | None:
    """HEAD commit read from .git files (no subprocess). Works for plain checkouts and worktrees."""
    git = ROOT / ".git"
    try:
        if git.is_file():  # worktree: "gitdir: <path>"
            git = Path(git.read_text().split(":", 1)[1].strip())
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(" ", 1)[1]
        for base in (git, git.parent.parent if git.parent.name == "worktrees" else git):
            p = base / ref
            if p.exists():
                return p.read_text().strip()
        packed = (git.parent.parent if git.parent.name == "worktrees" else git) / "packed-refs"
        for line in packed.read_text().splitlines() if packed.exists() else []:
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except OSError:
        return None
    return None


@app.get("/api/provenance")
def provenance() -> dict[str, Any]:
    """Where every number on the page comes from: run folder, assumptions hash, code commit, input files."""
    d = run_dir()
    b = load_balance(d)
    files = {p.name: p.stat().st_mtime for p in sorted(d.iterdir()) if p.is_file()} if d.exists() else {}
    return {"run_id": d.name, "run_dir": str(d), "fixture": d.resolve() == FIXTURE_DIR.resolve(),
            "assumptions_hash": b.get("assumptions_hash"), "load_basis": b.get("load_basis"),
            "code_commit": _git_commit(), "files": sorted(files), "producer": "python -m simulate_year (src/simulate_year)"}


@app.get("/api/ab_like_for_like")
def ab_like_for_like() -> dict[str, Any]:
    """#25: thermostat vs merit/always_on selling the SAME paid work (load_basis == 'thermostat'), same N."""
    d = run_dir()
    n = load_balance(d).get("servers_per_house")
    keep = ("policy", "servers_per_house", "slack_h", "load", "load_basis", "share_covered", "heat_dumped_kwh",
            "backup_heat_kwh", "utilisation", "break_even_chf_per_server_h", "missed_deadline_pct", "compute_income_chf")
    rows, root = [], _runs_root(d)
    for p in sorted(root.glob("*/balance.json")) if root.exists() else []:
        b = json.loads(p.read_text(encoding="utf-8"))
        if b.get("servers_per_house") != n:
            continue
        if b.get("policy") == "thermostat" or b.get("load_basis") == "thermostat":
            rows.append({k: b.get(k) for k in keep} | {"run_id": p.parent.name})
    order = {"thermostat": 0, "always_on": 1, "merit": 2}
    rows.sort(key=lambda r: (order.get(r["policy"], 9), r["run_id"]))
    note = None if any(r["policy"] != "thermostat" for r in rows) else \
        "no like-for-like run yet: python -m simulate_year --servers N --policy merit --slack-h 24 --load thermostat"
    return {"servers_per_house": n, "rows": rows, "note": note}


def _run_or_fixture(name: str) -> tuple[Path | None, bool]:
    d = run_dir()
    p = d / name
    if p.exists():
        return p, d.resolve() == FIXTURE_DIR.resolve()
    f = FIXTURE_DIR / name
    return (f, True) if f.exists() else (None, True)


@app.get("/api/sensitivity")
def sensitivity() -> dict[str, Any]:
    """#31 tornado: one row per parameter with the metric at its low and high setting. Sorted by swing.
    Column names are read as given; expected: parameter, low, high, metric_low, metric_high, metric_base, metric."""
    p, fixture = _run_or_fixture("sensitivity.csv")
    if p is None:
        return {"fixture": True, "rows": [], "note": "no sensitivity.csv yet (#31)"}
    df = pd.read_csv(p)
    if {"metric_low", "metric_high"} <= set(df.columns):
        df = df.assign(swing=(df["metric_high"] - df["metric_low"]).abs()).sort_values("swing", ascending=False)
    return {"fixture": fixture, "source": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
            "rows": _records(df)}


@app.get("/api/decision_card")
def decision_card() -> dict[str, Any]:
    """#31 decision_card.json, shown key by key (whatever keys it carries), with its source file."""
    p, fixture = _run_or_fixture("decision_card.json")
    if p is None:
        return {"fixture": True, "card": {}, "note": "no decision_card.json yet (#31)"}
    return {"fixture": fixture, "source": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
            "card": json.loads(p.read_text(encoding="utf-8"))}
