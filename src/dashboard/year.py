"""Year tab data (#96, schema ``yearview-v1`` agreed with Y1 on #95): serves Y1's cached JSON, never recomputes.

    GET /api/year/sizing   -> <dir>/index.json   (per-N summaries for ours + thermostat baseline, sizing rule)
    GET /api/year?n=1..8   -> <dir>/n<N>.json    (8 760-hour columnar series + summaries)

<dir> = ``DH_YEARVIEW_DIR`` if set, else the newest ``runs/yearview/<key>/`` holding an ``index.json``.
Responses are gzip-compressed when the client accepts it (~1 MB → ~0.2 MB per N), carry ``ETag`` = the run key and are
cacheable (the files are content-addressed by Y1's key). No data → 404 with the command that makes it; never invented.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "yearview-v1"
N_MAX = 8
_cache: dict[tuple[str, float], bytes] = {}  # (path, mtime) -> gzipped bytes

router = APIRouter(prefix="/api/year", tags=["year"])


def year_dir() -> Path:
    env = os.environ.get("DH_YEARVIEW_DIR")
    if env:
        return Path(env)
    base = ROOT / "runs" / "yearview"
    runs = sorted((p.parent for p in base.glob("*/index.json")), key=lambda p: p.stat().st_mtime) if base.exists() else []
    if not runs:
        raise HTTPException(404, "no year simulation yet: run python -m simulate_year.yearview --out runs/yearview")
    return runs[-1]


def _serve(request: Request, path: Path) -> Response:
    if not path.is_file():
        raise HTTPException(404, f"{path.name} not found in the year simulation output")
    st = path.stat()
    raw = path.read_bytes()
    try:
        doc = json.loads(raw)
    except ValueError:
        raise HTTPException(502, f"{path.name} is not valid JSON") from None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise HTTPException(502, f"{path.name}: expected schema {SCHEMA}, got {doc.get('schema') if isinstance(doc, dict) else '?'}")
    etag = '"' + str((doc.get("provenance") or {}).get("key", int(st.st_mtime))) + '-' + path.stem + '"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=3600", "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    if "gzip" in request.headers.get("accept-encoding", ""):
        key = (str(path), st.st_mtime)
        if key not in _cache:
            _cache.clear() if len(_cache) > 32 else None
            _cache[key] = gzip.compress(raw, compresslevel=6)
        return Response(_cache[key], media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(raw, media_type="application/json", headers=headers)


@router.get("/sizing")
def sizing(request: Request) -> Response:
    return _serve(request, year_dir() / "index.json")


@router.get("")
def year(request: Request, n: Annotated[int, Query(ge=1, le=N_MAX)] = 4) -> Response:
    return _serve(request, year_dir() / f"n{n}.json")
