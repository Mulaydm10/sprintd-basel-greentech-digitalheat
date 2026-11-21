"""Operator node registry (contract v1.2, red team R4 A08).

`runs/coordinator/nodes.json` = {node_id: {certified: bool, max_classes: [...], region: "CH-BS"}}, mode 600,
written only by `python -m coordinator --register-node`. It -- never the node's self-reported evidence -- decides
whether a node is certified and which access classes it may ever receive. A missing file means an empty
registry: every registration is denied (never allow-all). The file is never served over HTTP.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

CLASSES = ("public", "swiss-only", "certified")
ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")
REGION_RE = re.compile(r"^[A-Z]{2}(-[A-Z0-9]{1,8})?$")


def validate(data: object) -> dict[str, dict]:
    if not isinstance(data, dict):
        raise ValueError("registry must be a JSON object")
    out: dict[str, dict] = {}
    for nid, e in data.items():
        if not isinstance(nid, str) or not ID_RE.match(nid) or not isinstance(e, dict):
            raise ValueError(f"bad registry entry {nid!r}")
        cert, classes, region = e.get("certified"), e.get("max_classes"), e.get("region")
        if not isinstance(cert, bool) or not isinstance(classes, list) or not classes \
                or any(c not in CLASSES for c in classes) or not isinstance(region, str) or not REGION_RE.match(region):
            raise ValueError(f"bad registry entry {nid!r}")
        if set(e) - {"certified", "max_classes", "region"}:
            raise ValueError(f"bad registry entry {nid!r}: unknown fields")
        out[nid] = {"certified": cert, "max_classes": sorted(set(classes)), "region": region}
    return out


def load_registry(path: Path) -> dict[str, dict]:
    path = Path(path)
    if not path.exists():
        return {}  # deny all registrations
    return validate(json.loads(path.read_text()))


def register_node(path: Path, node_id: str, certified: bool, classes: list[str], region: str) -> dict:
    """Add or replace one entry (other entries untouched); atomic write, mode 600."""
    path = Path(path)
    data = load_registry(path)
    entry = validate({node_id: {"certified": certified, "max_classes": classes, "region": region}})[node_id]
    data[node_id] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return entry
