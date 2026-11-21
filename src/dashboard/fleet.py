"""Fleet data for the 07 Year telemetry panel and the on-map fleet view (#118, schema ``fleetview-v1`` from #119).

    GET /api/fleet/index         -> <dir>/index.json   (houses, assumed block, totals ours + thermostat)
    GET /api/fleet/fleet         -> <dir>/fleet.json   (columnar per-hour fleet series)
    GET /api/fleet/jobs          -> <dir>/jobs.json    (every M-th job fully traced: unit -> [hour, house] runs)
    GET /api/fleet/houses.u16    -> <dir>/houses.u16   (uint16 [field][house][hour], scales in index.json)

<dir> = ``DH_FLEETVIEW_DIR`` if set, else <runs/fleetview>/LATEST, else the newest ``runs/fleetview/<key>/``.
Serves the files as written (gzip when accepted, ETag = run key); never recomputes and never invents: no data -> 404
with the command that makes it. Only these four names are served (no path from the request ever reaches the disk).
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "fleetview-v1"
FILES = {"index": ("index.json", "application/json"), "fleet": ("fleet.json", "application/json"),
         "jobs": ("jobs.json", "application/json"), "houses.u16": ("houses.u16", "application/octet-stream")}
_cache: dict[tuple[str, float], bytes] = {}

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


def fleet_dir() -> Path:
    env = os.environ.get("DH_FLEETVIEW_DIR")
    if env:
        return Path(env)
    base = ROOT / "runs" / "fleetview"
    latest = base / "LATEST"
    if latest.is_file():
        d = base / latest.read_text().strip()
        if (d / "index.json").is_file():
            return d
    runs = sorted((p.parent for p in base.glob("*/index.json")), key=lambda p: p.stat().st_mtime) if base.exists() else []
    if not runs:
        raise HTTPException(404, "no fleet simulation yet: run python -m simulate_year.fleetview --out runs/fleetview")
    return runs[-1]


def _key(d: Path) -> str:
    try:
        idx = json.loads((d / "index.json").read_text())
    except (OSError, ValueError):
        raise HTTPException(502, "index.json missing or not valid JSON") from None
    if not isinstance(idx, dict) or idx.get("schema") != SCHEMA:
        raise HTTPException(502, f"expected schema {SCHEMA}")
    return str((idx.get("provenance") or {}).get("key", "nokey"))


def _serve(request: Request, name: str) -> Response:
    if name not in FILES:
        raise HTTPException(404, "unknown fleet file")
    d = fleet_dir()
    fname, media = FILES[name]
    path = d / fname
    if not path.is_file():
        raise HTTPException(404, f"{fname} not found in the fleet simulation output")
    etag = f'"{_key(d)}-{name}"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=3600", "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    st = path.stat()
    if "gzip" in request.headers.get("accept-encoding", ""):
        k = (str(path), st.st_mtime)
        if k not in _cache:
            if len(_cache) > 16:
                _cache.clear()
            _cache[k] = gzip.compress(path.read_bytes(), compresslevel=6)
        return Response(_cache[k], media_type=media, headers={**headers, "Content-Encoding": "gzip"})
    return Response(path.read_bytes(), media_type=media, headers=headers)


@router.get("/index")
def index(request: Request) -> Response:
    return _serve(request, "index")


@router.get("/fleet")
def fleet(request: Request) -> Response:
    return _serve(request, "fleet")


@router.get("/jobs")
def jobs(request: Request) -> Response:
    return _serve(request, "jobs")


@router.get("/houses.u16")
def houses(request: Request) -> Response:
    return _serve(request, "houses.u16")
