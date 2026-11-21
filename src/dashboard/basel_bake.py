"""Bake central Basel from OpenStreetMap into a small static file for the 3D map on 07 Year (#109).

    python -m dashboard.basel_bake [--raw runs/osm/basel_raw.json] [--fetch]

--fetch queries the public Overpass API once (buildings, the Rhine and other water, main streets in the bbox below) and
caches the raw answer; without it the cached raw file is used. Output: src/dashboard/static/site/data/basel3d.json.

Map data (c) OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright); the page shows this.

Format (ints, local metres x east / y north from ORIGIN, quantised to Q metres, rings delta-encoded):
  buildings: [[height_dm, kind, x0, y0, dx1, dy1, ...], ...]   kind 1 = residential, 0 = other
  water:     [[x0, y0, dx1, dy1, ...], ...]                     polygons (the Rhine and other water)
  rivers:    [[...], ...]                                       centre lines
  roads:     [[...], ...]                                       main streets (primary .. tertiary)
  reference: building index of the reference house; fleet: building indices of the ILLUSTRATIVE fleet
  hub:       [x, y] of the coordinator (Messe Basel)
  districts: [{name, ring, houses}] Basel's Wohnviertel (OSM admin_level 9), houses = simulated house ids inside
  hexes:     [[x, y, district], ...] centres of a HEX_M hex grid clipped to the districts (#112)
  live:      {node_id: building index}: the live nodes drawn as named houses (placed for illustration; live data)
The reference house carries the real yearview numbers; the fleet is illustrative (scaled from the reference).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from pathlib import Path

from common.config import ROOT

BBOX = (47.538, 7.560, 47.578, 7.625)  # south, west, north, east: Basel-Stadt core, both banks of the Rhine
ORIGIN = (47.558, 7.5925)  # lat, lon of (0, 0)
Q = 0.5  # metres per coordinate unit
MIN_AREA_M2 = 30.0
REF_SPOT = (47.5455, 7.5945)  # Gundeldingen: a residential block south of the station
HUB = (47.5636, 7.6006)  # Messe Basel
FLEET = 48
FLEET_SEED = 2025
FLEET_MIN_SPACING_M = 140.0
RESIDENTIAL = {"house", "residential", "apartments", "detached", "semidetached_house", "terrace", "dormitory"}
RAW = ROOT / "runs" / "osm" / "basel_raw.json"
DISTRICTS_RAW = ROOT / "runs" / "osm" / "basel_districts.json"
DISTRICT_QUERY = "[out:json][timeout:90];relation[\"boundary\"=\"administrative\"][\"admin_level\"=\"9\"]({b});out ids;"
HEX_M = 120.0
LIVE_SPOTS = {"node-mac": (47.5640, 7.5965), "node-omen2": (47.5655, 7.5770)}  # Matthaeus, St. Johann
OUT = Path(__file__).resolve().parent / "static" / "site" / "data" / "basel3d.json"
QUERY = ("[out:json][timeout:120];(way[\"building\"]({b});way[\"waterway\"=\"river\"]({b});way[\"natural\"=\"water\"]({b});"
         "relation[\"natural\"=\"water\"]({b});way[\"highway\"~\"^(primary|secondary|tertiary|trunk)$\"]({b}););"
         "out geom tags;")


def project(lat: float, lon: float) -> tuple[float, float]:
    k = 111_320.0
    return (lon - ORIGIN[1]) * k * math.cos(math.radians(ORIGIN[0])), (lat - ORIGIN[0]) * 110_540.0


def ring(geom: list[dict]) -> list[tuple[float, float]]:
    pts = [project(p["lat"], p["lon"]) for p in geom]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def area(pts) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2


def enc(pts) -> list[int]:
    out, px, py = [], 0, 0
    for i, (x, y) in enumerate(pts):
        qx, qy = round(x / Q), round(y / Q)
        out += [qx, qy] if i == 0 else [qx - px, qy - py]
        px, py = qx, qy
    return out


def height_m(t: dict) -> float:
    for k in ("height", "building:height"):
        try:
            return max(2.5, min(150.0, float(str(t[k]).split()[0].replace(",", "."))))
        except (KeyError, ValueError):
            pass
    try:
        return max(2.5, min(150.0, float(t["building:levels"]) * 3.1 + 1.5))
    except (KeyError, ValueError):
        pass
    b = t.get("building", "yes")
    return 3.0 if b in ("garage", "garages", "shed", "roof", "carport") else 12.0 if b in RESIDENTIAL else 10.0


def stitch(segments: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Join a multipolygon's outer way segments end to end into closed rings."""
    segs = [list(s) for s in segments if len(s) >= 2]
    rings = []
    while segs:
        cur = segs.pop(0)
        changed = True
        while changed and cur[0] != cur[-1]:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == cur[-1]:
                    cur += s[1:]
                elif s[-1] == cur[-1]:
                    cur += s[::-1][1:]
                elif s[-1] == cur[0]:
                    cur = s[:-1] + cur
                elif s[0] == cur[0]:
                    cur = s[::-1][:-1] + cur
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if len(cur) >= 4:
            rings.append(cur[:-1] if cur[0] == cur[-1] else cur)
    return rings


def inside(x: float, y: float, ring) -> bool:
    c = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def districts(raw: dict | None) -> list[tuple[str, list]]:
    out = []
    for e in (raw or {}).get("elements", []):
        segs = [[project(p["lat"], p["lon"]) for p in m["geometry"]] for m in e.get("members", [])
                if m.get("role") == "outer" and m.get("geometry")]
        rings = stitch(segs)
        if rings:
            out.append((e.get("tags", {}).get("name", str(e["id"])), max(rings, key=area)))
    return sorted(out)


def hexes(dist: list[tuple[str, list]]) -> list[list[int]]:
    out, w, h = [], HEX_M * math.sqrt(3), HEX_M * 1.5
    xs = [p[0] for _, r in dist for p in r]
    ys = [p[1] for _, r in dist for p in r]
    if not xs:
        return out
    row, y = 0, min(ys)
    while y <= max(ys):
        x = min(xs) + (w / 2 if row % 2 else 0)
        while x <= max(xs):
            for di, (_, r) in enumerate(dist):
                if inside(x, y, r):
                    out.append([round(x / Q), round(y / Q), di])
                    break
            x += w
        y += h
        row += 1
    return out


def bake(raw: dict, district_raw: dict | None = None) -> dict:
    blds, water, rivers, roads = [], [], [], []
    for e in raw["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and "building" in t and "geometry" in e:
            pts = ring(e["geometry"])
            a = area(pts)
            if len(pts) >= 3 and a >= MIN_AREA_M2:
                blds.append((pts, height_m(t), 1 if t["building"] in RESIDENTIAL else 0, a))
        elif t.get("waterway") == "river" and "geometry" in e:
            rivers.append(ring(e["geometry"]))
        elif t.get("natural") == "water":
            if e["type"] == "way" and "geometry" in e:
                water.append(ring(e["geometry"]))
            elif e["type"] == "relation":
                water += [ring(m["geometry"]) for m in e.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
        elif "highway" in t and "geometry" in e:
            roads.append(ring(e["geometry"]))
    # reference house: the residential building nearest REF_SPOT with a house-sized footprint
    rx, ry = project(*REF_SPOT)
    cand = [i for i, b in enumerate(blds) if b[2] == 1 and 90 <= b[3] <= 400]
    centroid = [(sum(p[0] for p in b[0]) / len(b[0]), sum(p[1] for p in b[0]) / len(b[0])) for b in blds]
    ref = min(cand, key=lambda i: math.hypot(centroid[i][0] - rx, centroid[i][1] - ry))
    rng = random.Random(FLEET_SEED)
    pool = [i for i in cand if i != ref]
    rng.shuffle(pool)
    fleet: list[int] = []
    for i in pool:
        if all(math.hypot(centroid[i][0] - centroid[j][0], centroid[i][1] - centroid[j][1]) >= FLEET_MIN_SPACING_M
               for j in fleet + [ref]):
            fleet.append(i)
        if len(fleet) == FLEET:
            break
    sims = [ref] + fleet
    taken = set(sims)
    live = {}
    for node, spot in LIVE_SPOTS.items():
        lx, ly = project(*spot)
        i = min((i for i in cand if i not in taken), key=lambda i: math.hypot(centroid[i][0] - lx, centroid[i][1] - ly))
        live[node] = i
        taken.add(i)
    dist = districts(district_raw)
    dist_out = [{"name": n, "ring": enc(r), "houses": [k for k, b in enumerate(sims) if inside(*centroid[b], r)]}
                for n, r in dist]
    return {
        "schema": "basel3d-v1",
        "districts": dist_out, "hexes": hexes(dist), "hex_m": HEX_M, "live": live, "attribution": "Map data © OpenStreetMap contributors, ODbL",
        "origin": ORIGIN, "bbox": BBOX, "q": Q,
        "buildings": [[round(h * 10), k] + enc(p) for p, h, k, _ in blds],
        "areas_m2": [round(b[3]) for b in blds],
        "water": [enc(p) for p in water if len(p) >= 3], "rivers": [enc(p) for p in rivers if len(p) >= 2],
        "roads": [enc(p) for p in roads if len(p) >= 2],
        "reference": ref, "fleet": fleet, "hub": [round(v / Q) for v in project(*HUB)],
        "fleet_note": "illustrative fleet: each house = the reference house's simulated year scaled by its footprint "
                      "(seeded variation); only the reference house is a graded number",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dashboard.basel_bake")
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--fetch", action="store_true", help="query Overpass once and cache the raw answer at --raw")
    ap.add_argument("--districts-raw", type=Path, default=DISTRICTS_RAW)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if a.fetch:
        a.raw.parent.mkdir(parents=True, exist_ok=True)
        q = QUERY.format(b=",".join(str(v) for v in BBOX))
        subprocess.run(["curl", "-sf", "-A", "osm-extract-script/1.0", "--max-time", "200", "--data-urlencode",
                        f"data={q}", "https://overpass-api.de/api/interpreter", "-o", str(a.raw)], check=True)
        ids = subprocess.run(["curl", "-sf", "-A", "osm-extract-script/1.0", "--max-time", "120", "--data-urlencode",
                              "data=" + DISTRICT_QUERY.format(b=",".join(str(v) for v in BBOX)),
                              "https://overpass-api.de/api/interpreter"], check=True, capture_output=True, text=True)
        rel = ",".join(str(e["id"]) for e in json.loads(ids.stdout)["elements"])
        subprocess.run(["curl", "-sf", "-A", "osm-extract-script/1.0", "--max-time", "120", "--data-urlencode",
                        f"data=[out:json][timeout:90];relation(id:{rel});out geom;",
                        "https://overpass-api.de/api/interpreter", "-o", str(a.districts_raw)], check=True)
    draw = json.loads(a.districts_raw.read_text()) if a.districts_raw.exists() else None
    d = bake(json.loads(a.raw.read_text()), draw)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(d, separators=(",", ":")))
    print(f"{a.out}: {len(d['buildings'])} buildings, {len(d['districts'])} districts, {len(d['hexes'])} hexes, "
          f"live {d['live']}, {len(d['water'])} water, {len(d['roads'])} roads, "
          f"reference #{d['reference']}, fleet {len(d['fleet'])}; {a.out.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
