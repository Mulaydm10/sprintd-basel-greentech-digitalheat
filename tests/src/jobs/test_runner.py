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

from jobs import checkpoint, runner
from jobs.catalogue import load_catalogue

SRC = str(Path(__file__).resolve().parents[3] / "src")
JOB = load_catalogue()[0].name
WIN = sys.platform == "win32"
POSIX_ONLY = pytest.mark.skipif(WIN, reason="POSIX signals: Windows has no SIGSTOP/SIGCONT and SIGTERM is "
                                            "TerminateProcess (no handler); the stop file / SIGBREAK cover it (#49)")
CHUNKS = 60
ROUNDS = 400  # a few ms per chunk; kills are triggered by checkpoint progress, not time


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


def _wait_progress(p: subprocess.Popen, ckpt: Path, target: int, timeout: float = 60.0) -> bool:
    """Poll the checkpoint until next_chunk >= target. False if the process exited first."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            state = checkpoint.load(ckpt)
        except (ValueError, OSError):  # only the tmp file is ever partial, but be tolerant
            state = None
        if state and state["next_chunk"] >= target:
            return True
        if p.poll() is not None:
            return False
        time.sleep(0.001)
    raise AssertionError("runner made no progress")


def test_random_stops_and_kills(tmp_path, reference):
    """Stop at random *progress* points (not wall-clock, #32 review) with a hard kill, a stop-file request or (POSIX)
    SIGTERM; the final output must equal the reference. The hard kill is Popen.kill(): SIGKILL on POSIX,
    TerminateProcess on Windows, so this test runs on every OS (#49)."""
    rng = random.Random(1234)
    ckpt = tmp_path / "job.ckpt"
    stop_file = runner.default_stop_file(ckpt)
    methods = ["kill", "stopfile"] + ([] if WIN else ["sigterm"])
    used: list[str] = []
    for _ in range(60):
        state = checkpoint.load(ckpt)
        done_so_far = state["next_chunk"] if state else 0
        left = CHUNKS - done_so_far
        # small steps (<= a quarter of what is left) so every stop method gets used before the job finishes
        target = done_so_far + rng.randint(1, max(1, left // 4)) if len(used) < 8 and left > 1 else None
        p = subprocess.Popen(_cmd(ckpt), env=_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        how = None
        if target is not None and _wait_progress(p, ckpt, target) and p.poll() is None:
            how = methods[len(used) % len(methods)] if len(used) < len(methods) else rng.choice(methods)
            if how == "kill":
                p.kill()
            elif how == "stopfile":
                stop_file.touch()
            else:
                p.send_signal(signal.SIGTERM)
            used.append(how)
        rc = p.wait(timeout=60)
        if how in (None, "stopfile"):
            assert rc == 0, p.stderr.read()
        elif how == "sigterm":
            assert rc in (0, -signal.SIGTERM)  # graceful stop exits 0 (unless it landed before the handler)
        assert not stop_file.exists()  # a request is consumed once honoured (or the job finished first)
        state = checkpoint.load(ckpt)
        if state and state["done"]:
            break
    else:
        pytest.fail("runner never finished")
    assert set(used) == set(methods), used  # every stop path was exercised at least once
    assert _out(ckpt) == reference


@pytest.mark.parametrize("damage", ["deleted", "shortened"])
def test_resume_refuses_when_output_log_is_behind_checkpoint(tmp_path, damage):
    """If the log is lost or shorter than the committed out_bytes, truncate() would pad with NULs and the
    run would 'finish' with missing chunks. The runner must refuse instead (#32 review)."""
    ckpt = tmp_path / "job.ckpt"
    r = _run(ckpt, JOBS_RUNNER_CRASH="after-append:20")
    assert r.returncode == 97
    out = ckpt.with_name(ckpt.name + ".out")
    committed = checkpoint.load(ckpt)["out_bytes"]
    if damage == "deleted":
        out.unlink()
    else:
        with open(out, "r+b") as f:
            f.truncate(committed - 10)
    r = _run(ckpt)
    assert r.returncode != 0
    assert "refusing to resume" in r.stderr
    assert checkpoint.load(ckpt)["out_bytes"] == committed  # nothing advanced
    assert not out.exists() or b"\0" not in out.read_bytes()


@POSIX_ONLY
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


@POSIX_ONLY
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


# ------------------------------------------------------------------ #49 portable graceful stop
def _start_and_wait(ckpt: Path, k: int = 3, **kw) -> subprocess.Popen:
    p = subprocess.Popen(_cmd(ckpt, chunks=100_000) + kw.get("extra", []), env=_env(), stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, creationflags=kw.get("creationflags", 0))
    assert _wait_progress(p, ckpt, k)
    return p


@pytest.mark.parametrize("custom", [False, True], ids=["default-path", "--stop-file"])
def test_stop_file_is_a_graceful_stop_on_every_os(tmp_path, custom):
    ckpt = tmp_path / "job.ckpt"
    stop = tmp_path / "pause.request" if custom else runner.default_stop_file(ckpt)
    p = _start_and_wait(ckpt, extra=["--stop-file", str(stop)] if custom else [])
    stop.touch()
    assert p.wait(timeout=30) == 0
    state = checkpoint.load(ckpt)
    assert 3 <= state["next_chunk"] < 100_000 and not state["done"]
    assert _ids(_out(ckpt)) == list(range(state["next_chunk"]))  # committed exactly once, no gap
    assert not stop.exists()  # consumed, so a restart resumes instead of stopping again


def test_stop_file_then_resume_equals_reference(tmp_path, reference):
    ckpt = tmp_path / "job.ckpt"
    p = subprocess.Popen(_cmd(ckpt), env=_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert _wait_progress(p, ckpt, CHUNKS // 3)
    runner.default_stop_file(ckpt).touch()
    assert p.wait(timeout=30) == 0
    assert not checkpoint.load(ckpt)["done"] or p.poll() == 0
    assert _run(ckpt).returncode == 0
    assert _out(ckpt) == reference


def test_stop_file_present_at_start_does_no_work(tmp_path):
    """A pause requested before the process started: exit 0 at once, no chunk run, request consumed."""
    ckpt = tmp_path / "job.ckpt"
    stop = runner.default_stop_file(ckpt)
    stop.touch()
    r = _run(ckpt)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["next_chunk"] == 0 and not stop.exists()
    assert _run(ckpt).returncode == 0 and checkpoint.load(ckpt)["done"]


@pytest.mark.skipif(not WIN, reason="Windows only: CTRL_BREAK_EVENT needs a new process group")
def test_ctrl_break_is_a_graceful_stop_on_windows(tmp_path):  # pragma: no cover - runs on Windows CI/hosts
    ckpt = tmp_path / "job.ckpt"
    p = _start_and_wait(ckpt, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    p.send_signal(signal.CTRL_BREAK_EVENT)
    assert p.wait(timeout=30) == 0
    state = checkpoint.load(ckpt)
    assert _ids(_out(ckpt)) == list(range(state["next_chunk"]))
