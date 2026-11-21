"""live_agent v2.1 / coordinator: units carry rounds/chunks from the job; every node computes the same result."""
from __future__ import annotations

import hashlib
import subprocess
import sys

from common.config import ROOT

from test_with_coordinator import H, done_units, env, heat, make_agent  # noqa: F401

R, C = 700, 4


def ref(tmp) -> bytes:
    ck = tmp / "ref2" / "job.ckpt"
    ck.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "jobs.runner", "image_tagging", "--checkpoint", str(ck), "--out",
                    str(ck.with_suffix(".out")), "--chunks", str(C), "--rounds", str(R)],
                   check=True, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True)
    return ck.with_suffix(".out").read_bytes()


def test_job_rounds_chunks_validated(env):
    for bad in ({"chunks": 0}, {"chunks": 2001}, {"rounds": 0}, {"rounds": 10**7 + 1}):
        r = env.c.post("/v1/jobs", headers=H("admin"), json={"job_type": "image_tagging", "customer_id": "c",
                                                             "force": True, **bad})
        assert r.status_code == 422, bad


def test_units_rounds_chunks_propagate_and_two_nodes_agree(env):
    for _ in range(2):
        r = env.c.post("/v1/jobs", headers=H("admin"), json={"job_type": "image_tagging", "customer_id": "c",
                                                             "force": True, "rounds": R, "chunks": C})
        assert r.status_code == 200 and r.json()["admitted"], r.text
    a = make_agent(env, "node-a", default_rounds=11, default_chunks=7)  # defaults must be ignored
    b = make_agent(env, "node-b", default_rounds=13, default_chunks=9)
    assert a.step() == "completed"
    env.clock.t += 10  # node-a goes quiet (suspect): the second unit must go to node-b
    heat(env, "node-b")
    assert b.step() == "completed"
    units = done_units(env)
    assert sorted(u["completed_by"] for u in units) == ["node-a", "node-b"]
    assert {u["rounds"] for u in units} == {R} and {u["chunks"] for u in units} == {C}
    want = hashlib.sha256(ref(env.tmp)).hexdigest()
    assert [u["result_sha256"] for u in units] == [want, want]


def test_cli_rounds_chunks_defaults(monkeypatch, tmp_path):
    import live_agent.__main__ as m
    seen = {}

    class A:
        def __init__(self, cfg, *a, **k):
            seen["cfg"] = cfg

        def run_forever(self, stop):
            pass

    monkeypatch.setattr(m, "Agent", A)
    tok = tmp_path / "t"
    tok.write_text("x" * 30)
    assert m.main(["--coordinator", "http://x", "--node-id", "n1", "--token-file", str(tok),
                   "--rounds", "5", "--chunks", "6"]) == 0
    assert seen["cfg"].default_rounds == 5 and seen["cfg"].default_chunks == 6
