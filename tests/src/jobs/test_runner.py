"""jobs.runner: resumable stand-in workload, exactly-once under kills (#5 runner part, Run B C2).

Every test compares the final output log byte-for-byte with an uninterrupted run. No models,
no network: the workload is the CPU-only SHA-256 stand-in.
"""
from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jobs import checkpoint
from jobs.catalogue import load_catalogue

SRC = str(Path(__file__).resolve().parents[3] / "src")
JOB = load_catalogue()[0].name
CHUNKS = 60
ROUNDS = 400  # a few ms per chunk, so random kills land mid-run


def _cmd(ckpt: Path, chunks: int = CHUNKS) -> list[str]:
    return [sys.executable, "-m", "jobs.runner", JOB, "--checkpoint", str(ckpt),
            "--chunks", str(chunks), "--rounds", str(ROUNDS)]


def _env(**extra: str) -> dict[str, str]:
    env = {**os.environ, "PYTHONPATH": SRC + os.pathsep + os.environ.get("PYTHONPATH", "")}
    env.pop("JOBS_RUNNER_CRASH", None)
    env.update(extra)
    return env


def _run(ckpt: Path, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(_cmd(ckpt), env=_env(**env), capture_output=True, text=True, timeout=120)


def _out(ckpt: Path) -> bytes:
    return ckpt.with_name(ckpt.name + ".out").read_bytes()


@pytest.fixture(scope="module")
def reference(tmp_path_factory) -> bytes:
    ckpt = tmp_path_factory.mktemp("ref") / "job.ckpt"
    r = _run(ckpt)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["done"] is True
    return _out(ckpt)


def _ids(log: bytes) -> list[int]:
    return [int(line.split()[0]) for line in log.decode().splitlines()]


def test_reference_has_each_chunk_once(reference):
    assert _ids(reference) == list(range(CHUNKS))


def test_rerun_after_done_is_a_noop(tmp_path, reference):
    ckpt = tmp_path / "job.ckpt"
    assert _run(ckpt).returncode == 0
    assert _run(ckpt).returncode == 0
    assert _out(ckpt) == reference


@pytest.mark.parametrize("stage", ["after-append", "mid-checkpoint"])
@pytest.mark.parametrize("k", [0, 17, CHUNKS - 1])
def test_forced_crash_then_resume_is_exactly_once(tmp_path, reference, stage, k):
    ckpt = tmp_path / "job.ckpt"
    r = _run(ckpt, JOBS_RUNNER_CRASH=f"{stage}:{k}")
    assert r.returncode != 0  # died on purpose
    if stage == "mid-checkpoint":
        assert ckpt.with_name(ckpt.name + ".tmp").exists()  # the torn save really happened
    assert _run(ckpt).returncode == 0
    assert _out(ckpt) == reference


def test_random_kills_sigkill_and_sigterm(tmp_path, reference):
    """Kill N times at random points with SIGKILL or SIGTERM; final output must equal reference."""
    rng = random.Random(1234)
    ckpt = tmp_path / "job.ckpt"
    kills = 0
    for _ in range(40):
        p = subprocess.Popen(_cmd(ckpt), env=_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(rng.uniform(0.05, 0.6))
        sig = None
        if p.poll() is None:
            sig = rng.choice([signal.SIGKILL, signal.SIGTERM])
            p.send_signal(sig)
            kills += 1
        rc = p.wait(timeout=60)
        if sig == signal.SIGTERM:
            assert rc in (0, -signal.SIGTERM)  # graceful stop exits 0 (unless it landed before the handler)
        elif sig is None:
            assert rc == 0
        state = checkpoint.load(ckpt)
        if state and state["done"]:
            break
    else:
        pytest.fail("runner never finished")
    assert kills >= 3, "kills should land mid-run; raise ROUNDS if this machine is very fast"
    assert _out(ckpt) == reference


def test_sigterm_exits_zero_with_checkpoint(tmp_path):
    ckpt = tmp_path / "job.ckpt"
    p = subprocess.Popen(_cmd(ckpt, chunks=100_000), env=_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.time() + 30
    while checkpoint.load(ckpt) is None and time.time() < deadline:  # handler is installed by then
        time.sleep(0.02)
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=30) == 0
    state = checkpoint.load(ckpt)
    assert 0 < state["next_chunk"] < 100_000 and not state["done"]
    assert _ids(_out(ckpt)) == list(range(state["next_chunk"]))


def test_sigstop_sigcont(tmp_path, reference):
    ckpt = tmp_path / "job.ckpt"
    p = subprocess.Popen(_cmd(ckpt), env=_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(0.2)
    if p.poll() is None:
        p.send_signal(signal.SIGSTOP)
        time.sleep(0.3)
        p.send_signal(signal.SIGCONT)
    assert p.wait(timeout=60) == 0
    assert _out(ckpt) == reference


def test_checkpoint_mismatch_is_refused(tmp_path):
    ckpt = tmp_path / "job.ckpt"
    checkpoint.save(ckpt, {"job_type": "other", "chunks": CHUNKS, "next_chunk": 0, "out_bytes": 0, "done": False})
    r = _run(ckpt)
    assert r.returncode != 0 and "belongs to" in r.stderr


def test_unknown_type_rejected(tmp_path):
    r = subprocess.run([sys.executable, "-m", "jobs.runner", "nope", "--checkpoint", str(tmp_path / "c")],
                       env=_env(), capture_output=True, text=True)
    assert r.returncode == 2
