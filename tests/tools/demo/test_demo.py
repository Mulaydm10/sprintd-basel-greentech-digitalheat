"""tools.demo (#77): dry-run plan + every step against a scripted fake coordinator. No network, no ssh."""
from __future__ import annotations

import pytest

import tools.demo.core as demo
from tools.demo.core import Config, Ctx, run_steps


class FakeCoordinator:
    """Tiny stand-in for the coordinator + two agents. Each status() call is one tick: alive nodes whose site
    wants heat lease pending units (certified only on node-mac), progress +10 %/tick, a site switched to July
    pauses its lease (then released on the next tick), a killed node's lease lapses after 3 ticks."""

    url = "http://fake"

    def __init__(self):
        self.signals = {"node-mac": demo.COLD, "node-omen2": demo.COLD}
        self.alive = {"node-mac": True, "node-omen2": True}
        self.units, self.leases, self.audit = {}, {}, []
        self.progress = {}
        self.tampered = set()
        self.n = 0

    def _ev(self, **e):
        self.audit.append({"idx": len(self.audit), **e})

    def submit(self, **job):
        self.n += 1
        jid = f"job-{self.n}"
        self.units[f"{jid}-u000"] = {"state": "pending", "access": job.get("access_class") or "public"}
        return {"job_id": jid, "admitted": True, "units": 1}

    def signal(self, site, demand, tank):
        self.signals[site] = (demand, tank)

    def warm(self, site):
        return self.signals[site][0] == 0.0

    def tamper(self, node):
        self.tampered.add(node)
        self._ev(type="tamper", node=node)
        return {"ok": True, "revoked": 0}

    def node_call(self, token, method, path, **kw):
        node = path.split("/")[3] if "/nodes/" in path and path.count("/") > 3 else kw.get("json", {}).get("node_id")
        body = ({"hold": True, "reason": "key denied: node_tampered", "retry_after_s": 5}
                if path.endswith("/lease") and node in self.tampered else {"ok": True})
        return type("R", (), {"status_code": 200, "text": "", "json": lambda self: body})()

    def status(self):
        for lid, lz in list(self.leases.items()):
            node, unit = lz["node"], lz["unit"]
            if not self.alive[node]:
                lz["dead_ticks"] = lz.get("dead_ticks", 0) + 1
                if lz["dead_ticks"] >= 3:
                    del self.leases[lid]
                    self.units[unit]["state"] = "pending"
                    self._ev(type="lease_lapsed", lease=lid, unit=unit, node=node)
                continue
            if lz.get("paused"):
                del self.leases[lid]
                self._ev(type="lease_released", lease=lid, unit=unit, node=node)
                continue
            if self.warm(node):
                lz["paused"] = True
                self.units[unit]["state"] = "pending"
                self._ev(type="lease_paused", lease=lid, unit=unit, node=node)
                continue
            self.progress[unit] = min(1.0, self.progress.get(unit, 0.0) + 0.1)
            if self.progress[unit] >= 1.0:
                del self.leases[lid]
                self.units[unit]["state"] = "done"
                self._ev(type="complete", unit=unit, node=node, result="REF")
        for node in ("node-mac", "node-omen2"):
            if not self.alive[node] or self.warm(node) or any(l["node"] == node for l in self.leases.values()):
                continue
            for unit, u in self.units.items():
                if u["state"] == "pending" and (u["access"] != "certified" or node == "node-mac"):
                    lid = f"l-{len(self.audit)}"
                    self.leases[lid] = {"node": node, "unit": unit}
                    u["state"] = "leased"
                    self._ev(type="lease", lease=lid, unit=unit, node=node)
                    break
        running = {l["node"]: l["unit"] for l in self.leases.values() if not l.get("paused")}
        sites = [{"site_id": s, "age_s": 0.5, "degraded": False} for s in self.signals]
        return {"nodes": [{"node_id": n, "running_unit": running.get(n), "progress": self.progress.get(running.get(n), 0.0),
                           "tampered": n in self.tampered} for n in ("node-mac", "node-omen2", "node-demo-tamper")],
                "leases": [{"lease_id": k, "unit_id": v["unit"], "node_id": v["node"]} for k, v in self.leases.items()
                           if not v.get("paused")],
                "recent_audit": self.audit[-20:], "audit_verifies": True, "sites": sites}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(demo, "reference_sha", lambda cfg: "REF")
    return FakeCoordinator()


def ctx_for(fake, tmp_path=None, **cfg):
    lines, cmds = [], []
    t = {"now": 0.0}

    def run_cmd(cmd):
        cmds.append(cmd)
        if "kill9" in cmd:
            fake.alive["node-omen2"] = False
        if "agent.sh start" in cmd:
            fake.alive["node-omen2"] = True
        if "coordinator.sitesim" in cmd and "nohup" in cmd:
            assert ".venv/bin/python" in cmd  # simulator restarted -> January signal again
            site = cmd.split("--site ")[1].split()[0]
            fake.signals[site] = demo.COLD
        return 0

    def sleep(s):
        t["now"] += s

    c = Ctx(fake, Config(poll_s=1.0, timeout_s=60.0, **cfg), out=lines.append, clock=lambda: t["now"], sleep=sleep,
            run_cmd=run_cmd)
    return c, lines, cmds


def test_dry_run_plans_every_step_without_side_effects(fake):
    c, lines, cmds = ctx_for(fake)
    c.dry_run = True
    res = run_steps(c, list(demo.STEPS))
    assert res == {s: True for s in demo.STEPS} and cmds == [] and fake.units == {}
    text = "\n".join(lines)
    assert "kill9" in text and "agent.sh start" in text and "[dry-run]" in text and "PASS migrate" in text


def test_migrate_kills_omen_resumes_on_mac_and_restores(fake):
    c, lines, cmds = ctx_for(fake)
    assert run_steps(c, ["migrate"]) == {"migrate": True}, "\n".join(lines)
    assert any("kill9" in x for x in cmds) and any("agent.sh start" in x for x in cmds)  # killed, then restored
    assert fake.alive["node-omen2"] and fake.signals["node-mac"] == demo.COLD and not c.held
    assert [e["node"] for e in fake.audit if e["type"] == "lease"] == ["node-omen2", "node-mac"]
    assert any(l.startswith("t+") and "lapsed" in l for l in lines)


def test_migrate_fails_on_wrong_result(fake, monkeypatch):
    monkeypatch.setattr(demo, "reference_sha", lambda cfg: "OTHER")
    c, lines, _ = ctx_for(fake)
    assert run_steps(c, ["migrate"]) == {"migrate": False}
    assert any(l.startswith("FAIL migrate") and "reference" in l for l in lines)
    assert fake.alive["node-omen2"]  # restored even on failure


def test_pause_holds_within_6s_resumes_and_restores(fake):
    c, lines, _ = ctx_for(fake)
    assert run_steps(c, ["pause"]) == {"pause": True}, "\n".join(lines)
    types = [e["type"] for e in fake.audit]
    assert types.index("lease_paused") < types.index("lease_released") < types.index("complete")
    assert any("paused after" in l for l in lines)
    assert fake.signals == {"node-mac": demo.COLD, "node-omen2": demo.COLD} and not c.held


def test_tamper_refuses_demo_nodes_and_needs_a_token(fake, tmp_path):
    c, lines, _ = ctx_for(fake, tamper_node="node-mac")
    assert run_steps(c, ["tamper"]) == {"tamper": False} and "refusing" in lines[-1]
    c, lines, _ = ctx_for(fake)
    assert run_steps(c, ["tamper"]) == {"tamper": False} and "--tamper-token-file" in lines[-1]  # no default token
    tok = tmp_path / "t"
    tok.write_text("x" * 40)
    c, lines, _ = ctx_for(fake, tamper_token_file=str(tok))
    assert run_steps(c, ["tamper"]) == {"tamper": True}, "\n".join(lines)
    assert "node-demo-tamper" in fake.tampered and "node-mac" not in fake.tampered


def test_certified_runs_only_on_mac(fake):
    fake.signals["node-mac"] = demo.COLD
    c, lines, _ = ctx_for(fake)
    assert run_steps(c, ["certified"]) == {"certified": True}, "\n".join(lines)
    assert {e["node"] for e in fake.audit if e["type"] == "lease"} == {"node-mac"}


def test_cli_dry_run_reads_tokens_from_files(tmp_path, capsys, monkeypatch):
    import tools.demo.__main__ as m
    for n in ("a", "o"):
        (tmp_path / n).write_text("t" * 40)
    code = m.main(["--coordinator", "http://127.0.0.1:1", "--admin-token-file", str(tmp_path / "a"),
                   "--observer-token-file", str(tmp_path / "o"), "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0 and "SUMMARY migrate=PASS pause=PASS tamper=PASS certified=PASS" in out
    assert "t" * 40 not in out  # tokens never printed


def test_poll_survives_a_coordinator_restart(fake):
    import httpx
    c, lines, _ = ctx_for(fake)
    real = fake.status
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx.ConnectError("Connection refused")
        return real()

    fake.status = flaky
    assert run_steps(c, ["certified"]) == {"certified": True}, "\n".join(lines)
    assert sum("unreachable" in l for l in lines) == 2
