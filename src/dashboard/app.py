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
from fastapi.responses import FileResponse, JSONResponse, Response

from trust import KeyBroker, attest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "src" / "dashboard" / "fixtures"
STATIC = Path(__file__).resolve().parent / "static"
HOURS_PER_DAY = 24
JAN_HOURS = range(0, 31 * HOURS_PER_DAY)
JUL_HOURS = range(181 * HOURS_PER_DAY, 212 * HOURS_PER_DAY)  # non-leap year: Jul 1 = day 182

app = FastAPI(title="DigitalHeat dashboard")


@app.exception_handler(Exception)
async def _unhandled(_req, e: Exception):  # safety net (#55): a bad input must never surface as a bare 500
    return JSONResponse({"detail": f"run data could not be read ({type(e).__name__})"}, status_code=422)


def _incomplete(what: str, e: Exception | None = None) -> HTTPException:
    """Corrupt, empty or half-written run output -> 422 with a clear message (red team F26-F29)."""
    why = f" ({type(e).__name__})" if e is not None else ""
    return HTTPException(422, f"run incomplete or corrupt: {what}{why}")


def read_json_file(p: Path, what: str, want: type = dict) -> Any:
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise _incomplete(what, e) from e
    if not isinstance(v, want):
        raise _incomplete(f"{what} is a {type(v).__name__}, expected a {want.__name__}")
    return v


def read_csv_file(p: Path, what: str) -> pd.DataFrame:
    try:
        return pd.read_csv(p)
    except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        raise _incomplete(what, e) from e


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
    return read_json_file(p, "balance.json")


def load_hourly(d: Path) -> pd.DataFrame:
    pq, csv = d / "hourly.parquet", d / "hourly.csv"
    if pq.exists():
        try:
            df = pd.read_parquet(pq)  # needs pyarrow or fastparquet
        except Exception as e:  # no engine (ImportError) or unreadable file (e.g. ArrowInvalid)
            if not csv.exists():
                raise _incomplete("hourly.parquet unreadable and no hourly.csv fallback", e) from e
            df = read_csv_file(csv, "hourly.csv")
    elif csv.exists():
        df = read_csv_file(csv, "hourly.csv")
    else:
        raise HTTPException(404, f"no hourly.parquet/hourly.csv in {d}")
    missing = [c for c in ("demand", "dump") if c not in df.columns]
    if missing:
        raise _incomplete(f"hourly data lacks column(s) {missing}")
    if "hour" not in df.columns:
        df = df.reset_index(drop=True)
        df.insert(0, "hour", df.index)
    for c in ("hour", "demand", "dump"):
        if not pd.api.types.is_numeric_dtype(df[c]):
            raise _incomplete(f"hourly column {c!r} is not numeric")
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


SITE = STATIC / "site"  # Dhruv's frontend (#91), built by dashboard.site_build from design/frontend/
HOME = "DigitalHeat 01 Overview.dc.html"  # Dhruv: the website is the entry point, not the deck


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """The website, page 01 Overview (#91). Its pages, runtime and vendored assets are served from the root by the mount below."""
    return FileResponse(SITE / HOME, media_type="text/html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page() -> FileResponse:
    """The data dashboard (formerly at /)."""
    return FileResponse(STATIC / "index.html")


FAVICON_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' "
               "fill='#c2410c'/><path d='M16 6c4 5 6 8 6 12a6 6 0 0 1-12 0c0-2 1-4 2-5 0 2 1 3 2 3 0-4 1-7 2-10z' "
               "fill='#fff7ed'/></svg>")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """The page links an inline SVG icon; this answers browsers that still ask for /favicon.ico (#81: no 404)."""
    return Response(FAVICON_SVG, media_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})


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
    return _records(read_csv_file(p, "sweep.csv"))


@app.get("/api/ab")
def ab() -> dict[str, Any]:
    """thermostat vs always_on vs merit at the balance's N, slack and load (rows from sweep.csv)."""
    b = load_balance(run_dir())
    rows = sweep()
    keep = ("policy", "servers_per_house", "share_covered", "heat_dumped_kwh", "break_even_chf_per_server_h",
            "break_even_incl_hardware_chf_per_server_h", "pays_off_above_chf_per_server_h", "missed_deadline_pct")
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
    """Decision card: N with the lowest PAID price needed to pay off incl. hardware (pays_off_above, the #50
    definition: filler and heat-led hours do not earn the paid price) among the merit rows, and that row's own
    pays_off verdict, so the page can never say 'pays' where balance.json says it does not (red team F30)."""
    b = load_balance(run_dir())
    rows = [r for r in sweep() if r.get("policy") == "merit"]
    key = "pays_off_above_chf_per_server_h"

    def num(v: Any) -> float:
        try:
            x = float(v)
        except (TypeError, ValueError):
            return float("inf")
        return x if math.isfinite(x) else float("inf")

    have = [r for r in rows if num(r.get(key)) < float("inf")]
    best = min(have, key=lambda r: num(r.get(key))) if have else None
    rule = f"lowest {key} (paid price needed to pay off incl. hardware, #50) among merit rows of sweep.csv"
    if rows and not have:
        rule += f"; this sweep.csv predates #50 (no {key} column), so no N is ranked: re-run the sweep"
    return {
        "rule": rule,
        "chosen": None if best is None else {k: best.get(k) for k in ("servers_per_house", "share_covered",
                                                                       "heat_dumped_kwh", "missed_deadline_pct",
                                                                       "pays_off")} | {key: num(best.get(key))},
        "pays_off": b.get("pays_off"),
        "pays_off_above_chf_per_server_h": b.get(key),
        "pays_off_conditions": b.get("pays_off_conditions"),
    }


LIVE_TIMEOUT_S = 3.0
LIVE_CACHE_S = 1.0
_live_cache: dict[str, Any] = {"at": -1e9, "data": None}
_live_transport: Any = None  # test seam: an httpx transport (MockTransport) instead of the network


def _live_fetch() -> dict[str, Any]:
    """GET {DH_COORDINATOR_URL}/v1/status with the observer token read server-side from DH_OBSERVER_TOKEN_FILE.
    The token never reaches the page. Any failure -> {ok: False, error} (the page shows a banner), never a 500."""
    import time as _time

    import httpx

    now = _time.monotonic()
    if _live_cache["data"] is not None and now - _live_cache["at"] < LIVE_CACHE_S:
        return _live_cache["data"]
    url = os.environ.get("DH_COORDINATOR_URL", "http://127.0.0.1:8710").rstrip("/")
    tok_file = os.environ.get("DH_OBSERVER_TOKEN_FILE", "")
    out: dict[str, Any] = {"enabled": True, "coordinator": url}
    try:
        token = Path(tok_file).read_text().strip() if tok_file else ""
        if not token:
            raise ValueError("DH_OBSERVER_TOKEN_FILE is not set or empty")
        kw = {"transport": _live_transport} if _live_transport is not None else {}
        with httpx.Client(base_url=url, timeout=LIVE_TIMEOUT_S, **kw) as c:
            r = c.get("/v1/status", headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            raise RuntimeError(f"coordinator answered HTTP {r.status_code}")
        st = r.json()
        if not isinstance(st, dict):
            raise ValueError("unexpected status payload")
        out |= {
            "ok": True,
            "nodes": [{k: n.get(k) for k in ("node_id", "site_id", "suspect", "degraded", "tampered", "running_unit",
                                              "progress", "watts", "last_error")} for n in st.get("nodes", [])],
            "leases": [{k: x.get(k) for k in ("lease_id", "unit_id", "node_id", "expires_in_s")}
                       for x in st.get("leases", [])],
            "sites": [{k: x.get(k) for k in ("site_id", "demand_kw", "tank_level_kwh", "heat_used_kw", "age_s",
                                              "degraded")} for x in st.get("sites", [])],
            "queue": st.get("queue", {}),
            "audit": [{k: v for k, v in e.items()} for e in st.get("recent_audit", [])[:10]],
            "audit_verifies": st.get("audit_verifies"),
        }
    except Exception as e:  # noqa: BLE001 - any failure is shown as a banner, not a 500
        msg = str(e) if isinstance(e, (ValueError, RuntimeError)) else type(e).__name__
        out |= {"ok": False, "error": f"coordinator unreachable or unreadable: {msg}"}
    _live_cache.update(at=now, data=out)
    return out


@app.get("/api/nodes")
def nodes() -> dict[str, Any]:
    """Live nodes from the coordinator's /v1/status (#78), enabled with DH_LIVE_NODES=1."""
    if os.environ.get("DH_LIVE_NODES") != "1":
        return {"enabled": False, "nodes": [],
                "note": "live view off: set DH_LIVE_NODES=1, DH_COORDINATOR_URL and DH_OBSERVER_TOKEN_FILE"}
    return _live_fetch()


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
    skipped: list[str] = []
    for p in sorted(root.glob("*/balance.json")) if root.exists() else []:
        try:
            b = read_json_file(p, f"{p.parent.name}/balance.json")
        except HTTPException:
            skipped.append(p.parent.name)  # half-written or corrupt sibling run: listed, not fatal (F27)
            continue
        if b.get("servers_per_house") != n:
            continue
        if b.get("policy") == "thermostat" or b.get("load_basis") == "thermostat":
            rows.append({k: b.get(k) for k in keep} | {"run_id": p.parent.name})
    order = {"thermostat": 0, "always_on": 1, "merit": 2}
    rows.sort(key=lambda r: (order.get(r["policy"], 9), r["run_id"]))
    note = None if any(r["policy"] != "thermostat" for r in rows) else \
        "no like-for-like run yet: python -m simulate_year --servers N --policy merit --slack-h 24 --load thermostat"
    return {"servers_per_house": n, "rows": rows, "note": note, "skipped": skipped}


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
    df = read_csv_file(p, "sensitivity.csv")
    skipped = 0
    if {"metric_low", "metric_high"} <= set(df.columns):
        for c in ("metric_low", "metric_high"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        bad = df["metric_low"].isna() | df["metric_high"].isna()
        skipped = int(bad.sum())  # non-numeric rows are dropped and counted, not fatal (F29)
        df = df[~bad]
        df = df.assign(swing=(df["metric_high"] - df["metric_low"]).abs()).sort_values("swing", ascending=False)
    return {"fixture": fixture, "source": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
            "rows": _records(df), "skipped_rows": skipped}


@app.get("/api/decision_card")
def decision_card() -> dict[str, Any]:
    """#31 decision_card.json, shown key by key (whatever keys it carries), with its source file."""
    p, fixture = _run_or_fixture("decision_card.json")
    if p is None:
        return {"fixture": True, "card": {}, "note": "no decision_card.json yet (#31)"}
    return {"fixture": fixture, "source": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
            "card": read_json_file(p, "decision_card.json")}


# ================================================================ #91: LIVE controls (local-only proxy) + the site
from .live import router as _live_router  # noqa: E402
from .year import router as _year_router  # noqa: E402

app.include_router(_live_router)
app.include_router(_year_router)  # #96: /api/year, /api/year/sizing (Y1's yearview-v1 cache)
from .fleet import router as _fleet_router  # noqa: E402
app.include_router(_fleet_router)  # #118: /api/fleet/* (fleetview-v1 from #119)
from .phones import router as _phones_router  # noqa: E402
app.include_router(_phones_router)  # wow #2: volunteer phone fleet
# Mounted last so every /api route above wins; serves the pages, support.js, deck-stage.js and vendor/ at the root,
# where the pages' relative links and their same-origin "./api/..." calls resolve.
from fastapi.staticfiles import StaticFiles  # noqa: E402

app.mount("/", StaticFiles(directory=SITE), name="site")
