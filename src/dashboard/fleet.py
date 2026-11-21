"""/api/fleet/* (#118): serve the newest fleetview-v1 run (#119) to the 3D map and the telemetry panel.

<dir> = DH_FLEETVIEW_DIR if set, else runs/fleetview/<LATEST>, else the synthetic fixture (index.json says
"fixture": true, and the page labels it). Read-only, files only, ETag = the run key.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from common.config import ROOT

FIXTURE = ROOT / "tests" / "src" / "simulate_year" / "fixtures" / "fleetview"
FILES = {"index": ("index.json", "application/json"), "houses.u16": ("houses.u16", "application/octet-stream"),
         "fleet": ("fleet.json", "application/json"), "jobs": ("jobs.json", "application/json")}
router = APIRouter(prefix="/api/fleet")


def fleet_dir() -> Path:
    env = os.environ.get("DH_FLEETVIEW_DIR")
    if env:
        return Path(env)
    base = ROOT / "runs" / "fleetview"
    try:
        d = base / (base / "LATEST").read_text().strip()
        if (d / "index.json").exists():
            return d
    except OSError:
        pass
    return FIXTURE


@router.get("/{name}")
def fleet_file(name: str, request: Request) -> Response:
    if name not in FILES:
        raise HTTPException(404, "unknown fleet file")
    d = fleet_dir()
    fn, mt = FILES[name]
    p = d / fn
    if not p.exists():
        raise HTTPException(404, "no fleetview run: python -m simulate_year.fleetview --out runs/fleetview")
    etag = f'"{d.name}-{fn}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)
    return FileResponse(p, media_type=mt, headers={"ETag": etag, "Cache-Control": "public, max-age=600"})
