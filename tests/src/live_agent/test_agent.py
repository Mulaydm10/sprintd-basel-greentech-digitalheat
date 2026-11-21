"""live_agent v2 against an in-process coordinator (TestClient transport) with the cpu-hash backend."""
from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from common.config import ROOT
from live_agent import wire
from live_agent.agent import Agent, Config, Fatal
from trust import attest, generate_keypair, open_, seal

from fake_coordinator import FakeCoordinator  # noqa: E402  (same dir; pytest prepends it)

CHUNKS, ROUNDS = 120, 400  # a few seconds of cpu-hash work; tests trigger on progress, not wall-clock
LONG = 400  # pause/lapse units: long enough that a fast machine (M4) cannot finish before the trigger lands
FAST = dict(renew_s=0.1, upload_s=0.1, stop_grace_s=5.0, poll_s=0.01, heartbeat_s=0.1)


def reference_log(tmp_path: Path, chunks: int = CHUNKS, rounds: int = ROUNDS) -> bytes:
    ck = tmp_path / "ref" / "job.ckpt"
    ck.parent.mkdir(parents=True)
    env = {"PYTHONPATH": str(ROOT / "src")}
    subprocess.run([sys.executable, "-m", "jobs.runner", "image_tagging", "--checkpoint", str(ck), "--out",
                    str(ck.with_suffix(".out")), "--chunks", str(chunks), "--rounds", str(rounds)], check=True,
                   env=env, capture_output=True)
    return ck.with_suffix(".out").read_bytes()


@pytest.fixture
def coord():
    return FakeCoordinator()


def make_agent(coord: FakeCoordinator, tmp_path: Path, node: str = "node-a", token: str = "tok-a",
               sleeps: list | None = None, **cfg) -> Agent:
    app = coord.app()
    hdr = {"Authorization": f"Bearer {token}"}
    http, hb = TestClient(app, headers=hdr), TestClient(app, headers=hdr)
    rec = sleeps if sleeps is not None else []

    def sleep(s):
        rec.append(s)
        time.sleep(min(s, 0.02))  # real time stays short; the requested value is what we assert on

    a = Agent(Config(node_id=node, site_id=node, root=tmp_path / "agent", **{**FAST, **cfg}), http, hb_http=hb,
              sleep=sleep)
    a.register()
    return a


def in_thread(fn):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", fn()), daemon=True)
    t.start()
    return t, out


def wait_until(cond, timeout=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.005)
    raise AssertionError("condition not reached")


# ------------------------------------------------------------------ wire
def test_wire_roundtrips():
    a = attest("node-a", {"region": "CH-BS", "measurement": "m"})
    assert wire.attestation_from_json(wire.attestation_to_json(a)).is_valid()
    priv, pub = generate_keypair()
    k = wire.key_from_json(wire.key_to_json(priv))
    env = seal(b"secret", pub, aad=b"u1")
    assert open_(wire.envelope_from_bytes(wire.envelope_to_bytes(env)), k) == b"secret"
    ck = {"next_chunk": 2, "out_bytes": 4, "done": False}
    assert wire.bundle_from_bytes(wire.bundle_to_bytes(ck, b"abcdEXTRA")) == (ck, b"abcd")
    with pytest.raises(ValueError):
        wire.bundle_to_bytes({"out_bytes": 9}, b"short")
    with pytest.raises(ValueError):
        wire.key_from_json({"key_b64": wire.b64e(b"x" * 31)})


# ------------------------------------------------------------------ happy path
def test_unit_completes_exactly_once_and_matches_reference(coord, tmp_path):
    coord.submit("job-1-u000", chunks=CHUNKS, rounds=ROUNDS)
    a = make_agent(coord, tmp_path)
    assert a.step() == "completed"
    u = coord.units["job-1-u000"]
    ref = reference_log(tmp_path)
    assert u.result_sha256 == hashlib.sha256(ref).hexdigest()
    assert u.chunk_ids == list(range(CHUNKS)) and u.completions == 1
    assert coord.checkpoints["job-1-u000"], "checkpoints were uploaded while running"
    assert a.step() == "hold"  # queue empty


def test_heartbeat_reports_measured_or_null_watts(coord, tmp_path):
    a = make_agent(coord, tmp_path)
    assert a.heartbeat_once()
    hb = coord.heartbeats[-1]
    assert hb["watts_source"] in ("rapl", "nvml", "powermetrics-file", "none")
    assert (hb["watts"] is None) == (hb["watts_source"] == "none")
    (a.workdir / "watts.txt").write_text("37.5\n")  # a human-run powermetrics sampler
    a.heartbeat_once()
    assert coord.heartbeats[-1]["watts"] == 37.5 and coord.heartbeats[-1]["watts_source"] == "powermetrics-file"


# ------------------------------------------------------------------ pause / resume / migrate
def test_pause_uploads_checkpoint_and_another_node_resumes_exactly_once(coord, tmp_path):
    """Coordinator says hold → stop file → final checkpoint; node B fetches it and finishes. Output == reference."""
    coord.submit("job-2-u000", chunks=LONG, rounds=ROUNDS)
    a = make_agent(coord, tmp_path, "node-a", "tok-a")
    t, out = in_thread(a.step)
    wait_until(lambda: a.state["progress"] >= 0.05)
    coord.knobs.hold_renew = True
    t.join(30)
    assert out["r"] == "paused"
    seq = coord.checkpoints["job-2-u000"]
    paused_at = int(seq[-1][1]["X-Next-Chunk"])
    assert 0 < paused_at < LONG
    coord.knobs.hold_renew = False
    b = make_agent(coord, tmp_path, "node-b", "tok-b")
    assert b.step() == "completed"
    u = coord.units["job-2-u000"]
    assert u.result_sha256 == hashlib.sha256(reference_log(tmp_path, chunks=LONG)).hexdigest()
    assert u.chunk_ids == list(range(LONG))  # every chunk exactly once across the two nodes
    assert int(coord.checkpoints["job-2-u000"][-1][1]["X-Next-Chunk"]) == LONG


def test_lapsed_lease_kills_and_discards_local_output(coord, tmp_path):
    coord.submit("job-3-u000", chunks=LONG, rounds=ROUNDS)
    a = make_agent(coord, tmp_path)
    t, out = in_thread(a.step)
    wait_until(lambda: a.state["progress"] >= 0.03)
    coord.knobs.lapse_on_renew = True
    t.join(30)
    assert out["r"] == "lapsed"
    assert not (a.workdir / "job-3-u000").exists()  # partial output discarded: the other node owns it now
    assert "410" in a.state["last_error"]
    assert not coord.units["job-3-u000"].done


def test_no_renewal_before_expiry_counts_as_lapsed(coord, tmp_path):
    """Coordinator unreachable mid-lease (every renew 503): the agent must not run past its lease."""
    coord.knobs.expires_in_s = 0.6
    coord.submit("job-4-u000", chunks=100_000, rounds=ROUNDS)
    a = make_agent(coord, tmp_path)
    coord.knobs.fail_renew = True
    t0 = time.time()
    assert a.step() == "lapsed"
    assert time.time() - t0 < 10
    assert "expiry" in a.state["last_error"]


# ------------------------------------------------------------------ errors
def test_backoff_on_5xx_is_exponential_capped_and_recovers(coord, tmp_path):
    sleeps: list[float] = []
    coord.submit("job-5-u000", chunks=10, rounds=10)
    a = make_agent(coord, tmp_path, sleeps=sleeps)
    coord.knobs.fail_next = 8
    results = [a.step() for _ in range(8)]
    assert results == ["backoff"] * 8
    backoffs = [s for s in sleeps if s > a.cfg.poll_s]
    assert len(backoffs) == 8 and max(backoffs) <= 10.0
    assert backoffs[3] > backoffs[0] and backoffs[-1] >= 5.0  # grows, then sits near the cap (jittered)
    assert a.step() == "completed"


def test_key_denied_is_reported_and_nothing_runs(coord, tmp_path):
    coord.submit("job-6-u000", chunks=10, rounds=10)
    a = make_agent(coord, tmp_path)
    coord.broker.tamper("node-a")
    assert a.step() == "denied"
    assert "node_tampered" in a.state["last_error"]
    a.heartbeat_once()
    assert "node_tampered" in coord.heartbeats[-1]["last_error"]
    assert not (a.workdir / "job-6-u000").exists()


def test_register_with_bad_token_is_fatal(coord, tmp_path):
    app = coord.app()
    a = Agent(Config(node_id="node-a", site_id="node-a", root=tmp_path / "agent"),
              TestClient(app, headers={"Authorization": "Bearer nope"}))
    with pytest.raises(Fatal, match="401"):
        a.register()


@pytest.mark.parametrize("bad", ["../../etc", "UPPER", "a/b", "x" * 65, ""])
def test_hostile_unit_id_never_names_a_directory(coord, tmp_path, bad):
    a = make_agent(coord, tmp_path)
    priv, _ = generate_keypair()
    lease = {"unit": {"unit_id": bad, "job_id": "j", "job_type": "image_tagging", "chunks": 3},
             "lease_id": "lease-1", "key_release": wire.key_to_json(priv)}
    with pytest.raises(ValueError):
        a.run_unit(lease)
    assert sorted(p.name for p in (tmp_path / "agent").iterdir()) == ["node-a"]
    assert not any((tmp_path / "agent" / "node-a").iterdir())


def test_unknown_job_type_is_rejected_not_executed(coord, tmp_path):
    a = make_agent(coord, tmp_path)
    priv, _ = generate_keypair()
    lease = {"unit": {"unit_id": "u-1", "job_id": "j", "job_type": "rm -rf", "chunks": 3},
             "lease_id": "lease-1", "key_release": wire.key_to_json(priv)}
    assert a.run_unit(lease) == "rejected"


def test_config_rejects_unavailable_backend(tmp_path):
    with pytest.raises(ValueError, match="mlx"):
        Config(node_id="n", site_id="n", backend="mlx", root=tmp_path)
