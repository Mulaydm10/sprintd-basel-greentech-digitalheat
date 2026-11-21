"""#64: a jobs.runner child must not outlive a kill -9'd agent; stale unit dirs are cleaned on start."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[3] / "src"


def _dead(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:  # reparented to a subreaper that has not reaped yet
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].startswith(("Z", "X"))
    except OSError:
        return False


@pytest.mark.skipif(sys.platform == "win32", reason="kill -9 / os.kill(pid, 0) semantics are POSIX")
def test_runner_exits_when_agent_is_killed(tmp_path):
    parent = textwrap.dedent(f"""
        import sys, time
        from pathlib import Path
        from live_agent.agent import launch_runner
        d = Path({str(tmp_path)!r})
        p = launch_runner(sys.executable, "whisper_transcription", d / "job.ckpt", d / "job.out", d / "job.stop",
                          100000, 200, d)
        print(p.pid, flush=True)
        time.sleep(600)
    """)
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    agent = subprocess.Popen([sys.executable, "-c", parent], env=env, stdout=subprocess.PIPE, text=True)
    try:
        pid = int(agent.stdout.readline())
        deadline = time.monotonic() + 20
        while not (tmp_path / "job.ckpt").exists():  # runner is really computing
            assert time.monotonic() < deadline, "runner never committed a chunk"
            time.sleep(0.05)
        agent.send_signal(signal.SIGKILL)
        agent.wait()
        deadline = time.monotonic() + 5
        while not _dead(pid):
            assert time.monotonic() < deadline, "orphaned runner still running 5 s after the agent died"
            time.sleep(0.05)
    finally:
        agent.kill()
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, UnboundLocalError, PermissionError):
            pass


def test_runner_watchdog_exits_nonzero_without_output(tmp_path):
    from jobs import runner
    out = tmp_path / "job.out"
    calls = iter([True, True, False])
    with _ExitCatcher() as ex:
        runner.run("whisper_transcription", tmp_path / "job.ckpt", out, 10, runner.HashWorkload("whisper_transcription", 1),
                   parent_alive=lambda: next(calls))
    assert ex.code == runner.PARENT_GONE_RC
    assert len(out.read_bytes().splitlines()) == 2


class _ExitCatcher:
    """Intercept os._exit for the in-process run."""
    def __enter__(self):
        self._orig, self.code = os._exit, None

        def fake(code):
            self.code = code
            raise _Exited
        os._exit = fake
        return self

    def __exit__(self, et, ev, tb):
        os._exit = self._orig
        return et is _Exited


class _Exited(BaseException):
    pass


def test_agent_start_removes_stale_unit_dirs(tmp_path):
    import httpx
    from live_agent.agent import Agent, Config
    wd = tmp_path / "agent" / "node-a"
    (wd / "u-old").mkdir(parents=True)
    (wd / "u-old" / "job.ckpt").write_text("{}")
    (wd / "watts.txt").write_text("12")
    Agent(Config(node_id="node-a", site_id="node-a", root=tmp_path / "agent"), httpx.Client())
    assert not (wd / "u-old").exists()
    assert (wd / "watts.txt").exists()
