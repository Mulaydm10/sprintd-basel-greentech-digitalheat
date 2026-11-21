"""v1.2: certification + class ceiling come from the operator registry nodes.json, never from node evidence."""
from __future__ import annotations

import base64
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
import trust  # noqa: E402
from coordinator.__main__ import main  # noqa: E402
from coordinator.app import create_app  # noqa: E402
from coordinator.registry import load_registry  # noqa: E402
from test_coordinator import H, ROLES, TOK, Clock, hb, lease, submit  # noqa: E402

ALL = ["public", "swiss-only", "certified"]


def client(tmp_path, registry=None, clock=None):
    clock = clock or Clock()
    app = create_app(tmp_path, tokens=ROLES, clock=clock, registry=registry)
    app.state.limiter.clock = clock
    return TestClient(app), app


def reg_body(node, classes=ALL, certified=False, region="CH-BS"):
    ev = {"measurement": "digitalheat-node-image-v1", "region": region, "certified": certified}
    a = trust.attest(node, ev)
    return {"node_id": node, "site_id": f"site-{node[-1]}", "eligible_classes": list(classes), "server_kw_el": 1.0,
            "attestation": {"node_id": node, "evidence": ev, "signature_b64": base64.b64encode(a.signature).decode(),
                            "mock": True}}


def audit_types(app):
    return [e.event["type"] for e in app.state.coord.broker.audit.entries]


def test_missing_registry_file_denies_all(tmp_path):
    c, app = client(tmp_path)  # no registry passed, no nodes.json -> deny all
    r = c.post("/v1/nodes/register", headers=H("node-a"), json=reg_body("node-a"))
    assert r.status_code == 403 and r.json()["detail"] == "node not in registry"


def test_unregistered_node_403(tmp_path):
    c, app = client(tmp_path, {"node-b": {"certified": True, "max_classes": ALL, "region": "CH-BS"}})
    r = c.post("/v1/nodes/register", headers=H("node-a"), json=reg_body("node-a", certified=True))
    assert r.status_code == 403 and r.json()["detail"] == "node not in registry"
    assert "register_denied" in audit_types(app)


def test_uncertified_claim_rejected_and_never_gets_certified_unit(tmp_path):
    c, app = client(tmp_path, {"node-a": {"certified": False, "max_classes": ALL, "region": "CH-BS"}})
    r = c.post("/v1/nodes/register", headers=H("node-a"), json=reg_body("node-a", certified=True))
    assert r.status_code == 200 and r.json()["certified"] is False
    assert "certified" not in r.json()["eligible_classes"]
    assert "certified_claim_rejected" in audit_types(app)
    hb(c, "node-a")
    submit(c, access_class="certified")
    for _ in range(3):
        out = lease(c, "node-a")
        assert "unit" not in out or out["unit"]["access_class"] != "certified"
    # even if the scheduler were bypassed, the key guard refuses (defense in depth)
    coord = app.state.coord
    job_id = next(iter(coord.broker._jobs))
    att = trust.attest("node-a", {"measurement": "digitalheat-node-image-v1", "region": "CH-BS", "certified": True})
    assert isinstance(coord._release(job_id, "node-a", att, "CH-BS"), trust.Denied)


def test_classes_clipped_to_ceiling(tmp_path):
    c, _ = client(tmp_path, {"node-a": {"certified": True, "max_classes": ["public"], "region": "CH-BS"}})
    r = c.post("/v1/nodes/register", headers=H("node-a"), json=reg_body("node-a", classes=ALL, certified=True))
    assert r.status_code == 200 and r.json()["eligible_classes"] == ["public"]
    c2, _ = client(tmp_path / "b", {"node-b": {"certified": False, "max_classes": ["public"], "region": "CH-BS"}})
    r = c2.post("/v1/nodes/register", headers=H("node-b"), json=reg_body("node-b", classes=["certified"]))
    assert r.status_code == 403


def test_registry_certified_node_gets_certified_units(tmp_path):
    c, _ = client(tmp_path, {"node-a": {"certified": True, "max_classes": ALL, "region": "CH-BS"}})
    r = c.post("/v1/nodes/register", headers=H("node-a"), json=reg_body("node-a", certified=True))
    assert r.status_code == 200 and r.json()["certified"] is True
    hb(c, "node-a")
    submit(c, access_class="certified")
    out = lease(c, "node-a")
    assert out.get("unit", {}).get("access_class") == "certified", out


def test_registry_file_never_served(tmp_path):
    assert main(["--state", str(tmp_path), "--register-node", "node-a", "--certified", "--classes", ",".join(ALL)]) == 0
    c, _ = client(tmp_path)  # loads nodes.json
    for path in ["/nodes.json", "/v1/nodes.json", "/v1/nodes/nodes.json", "/v1/status", "/runs/coordinator/nodes.json",
                 "/v1/checkpoints/nodes.json/latest"]:
        for hdr in (H("admin"), H("observer"), H("node-a"), {}):
            r = c.get(path, headers=hdr)
            assert "max_classes" not in r.text


def test_cli_register_node_additive_atomic_mode600(tmp_path):
    assert main(["--state", str(tmp_path), "--register-node", "node-a", "--certified", "--classes", ",".join(ALL)]) == 0
    assert main(["--state", str(tmp_path), "--register-node", "node-b", "--classes", "public", "--region", "CH-BL"]) == 0
    p = tmp_path / "nodes.json"
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    reg = load_registry(p)
    assert reg["node-a"] == {"certified": True, "max_classes": sorted(ALL), "region": "CH-BS"}
    assert reg["node-b"] == {"certified": False, "max_classes": ["public"], "region": "CH-BL"}
    assert not [x for x in os.listdir(tmp_path) if ".tmp" in x]
    with pytest.raises(SystemExit):
        main(["--state", str(tmp_path), "--register-node", "node-c", "--classes", "secret"])
    with pytest.raises(SystemExit):
        main(["--state", str(tmp_path), "--register-node", "../x"])
    assert set(json.loads(p.read_text())) == {"node-a", "node-b"}
