"""Resumable real-workload entrypoint (contracts/src/jobs.md):

    python -m jobs.runner <type> --checkpoint <path> [--out <path>] [--stop-file <path>] [--chunks N] [--rounds R]

The work is a sequence of chunks with stable ids 0..N-1. Each finished chunk appends one line
`<chunk_id> <sha256>` to the output log. Exactly-once comes from the commit order:

1. compute chunk i;
2. append its line to the output log and fsync;
3. atomically write the checkpoint {next_chunk: i+1, out_bytes: <log size>}.

On start the runner loads the checkpoint (if any), truncates the output log to `out_bytes`
(dropping any line written after the last commit) and continues at `next_chunk`. A crash
anywhere, including halfway through writing the checkpoint, therefore repeats no committed chunk
and loses none: the final log is byte-identical to an uninterrupted run.

Graceful stop (finish and commit the current chunk, then exit 0), three ways:
- a **stop file** (`--stop-file`, default `<checkpoint>.stop`): checked before every chunk and consumed (deleted)
  when honoured. Portable, so it is the pause path the live agent uses on every OS (#49);
- SIGTERM (POSIX; on Windows SIGTERM is TerminateProcess, a hard kill with no handler);
- SIGBREAK (Windows: CTRL_BREAK_EVENT to a process started with CREATE_NEW_PROCESS_GROUP).
Parent watchdog (#64): with `--parent-pid P` the runner exits 3 (without writing another chunk) as soon as P
is gone, checked before every chunk; on Linux it also asks for PR_SET_PDEATHSIG=SIGKILL (best effort).
A hard kill anywhere (SIGKILL, TerminateProcess, power loss) is covered by the commit order above.
SIGSTOP/SIGCONT (POSIX only) need no handling: nothing depends on wall-clock time.

The default workload is a CPU-only stand-in (repeated SHA-256 over deterministic per-chunk data)
so CI needs no models. Real backends (Whisper, image tagging) plug in behind `Workload`.
The stand-in's sizes are test knobs, not pitch numbers; the catalogue numbers stay in
data/assumptions.yaml.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import Callable, Protocol

from jobs import checkpoint
from jobs.catalogue import load_catalogue

CHUNK_BYTES = 64 * 1024  # stand-in input per chunk (test knob)
DEFAULT_CHUNKS = 200  # stand-in work units per job (test knob)
DEFAULT_ROUNDS = 50  # SHA-256 passes per chunk; sets the stand-in's duration (test knob)
CRASH_ENV = "JOBS_RUNNER_CRASH"  # test-only: "mid-checkpoint:<k>" or "after-append:<k>"


class Workload(Protocol):
    def run_chunk(self, chunk_id: int) -> str: ...


class HashWorkload:
    """CPU stand-in: deterministic input per chunk id, `rounds` chained SHA-256 passes."""

    def __init__(self, job_type: str, rounds: int) -> None:
        self.seed = job_type.encode()
        self.rounds = rounds

    def run_chunk(self, chunk_id: int) -> str:
        block = hashlib.sha256(self.seed + chunk_id.to_bytes(8, "big")).digest()
        data = (block * (CHUNK_BYTES // len(block) + 1))[:CHUNK_BYTES]
        h = data
        for _ in range(self.rounds):
            h = hashlib.sha256(h + data).digest()
        return h.hex()


def _crash_hook(stage: str) -> Callable[[int], bool]:
    """Return f(chunk_id) -> True when the test asked to die at `stage` for this chunk."""
    spec = os.environ.get(CRASH_ENV, "")
    if not spec.startswith(stage + ":"):
        return lambda _cid: False
    k = int(spec.split(":", 1)[1])
    return lambda cid: cid == k


def default_stop_file(ckpt: Path) -> Path:
    return ckpt.with_name(ckpt.name + ".stop")


def _install_stop_handlers(stop: dict) -> None:
    def handler(*_):
        stop["flag"] = True
    signal.signal(signal.SIGTERM, handler)  # POSIX graceful stop; harmless on Windows (never delivered)
    if hasattr(signal, "SIGBREAK"):  # Windows only
        signal.signal(signal.SIGBREAK, handler)


PARENT_GONE_RC = 3


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def parent_watch(parent_pid: int | None) -> Callable[[], bool]:
    """Return f() -> True while the parent that launched us is still alive."""
    if not parent_pid:
        return lambda: True
    if sys.platform.startswith("linux"):
        try:
            import ctypes
            ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
        except Exception:
            pass
    if os.name == "posix":  # reparenting changes getppid(); also catches a recycled pid
        return lambda: os.getppid() == parent_pid
    return lambda: _pid_alive(parent_pid)


def run(job_type: str, ckpt: Path, out: Path, chunks: int, workload: Workload,
        stop_file: Path | None = None, parent_alive: Callable[[], bool] | None = None) -> dict:
    parent_alive = parent_alive or (lambda: True)
    stop = {"flag": False}
    _install_stop_handlers(stop)
    stop_file = stop_file or default_stop_file(ckpt)

    def stop_requested() -> bool:
        if stop["flag"]:
            return True
        if stop_file.exists():
            stop["flag"] = True
        return stop["flag"]

    state = checkpoint.load(ckpt)
    if state is None:
        state = {"job_type": job_type, "chunks": chunks, "next_chunk": 0, "out_bytes": 0, "done": False}
    elif state["job_type"] != job_type or state["chunks"] != chunks:
        raise SystemExit(f"checkpoint {ckpt} belongs to {state['job_type']}/{state['chunks']} chunks, "
                         f"not {job_type}/{chunks}")

    crash_after_append = _crash_hook("after-append")
    crash_mid_ckpt = _crash_hook("mid-checkpoint")

    have = out.stat().st_size if out.exists() else 0
    if have < state["out_bytes"]:  # log lost or rolled back: truncate() would pad with NULs (#32 review)
        raise SystemExit(f"output log {out} has {have} bytes but checkpoint {ckpt} committed "
                         f"{state['out_bytes']}; refusing to resume (restore the log or delete the checkpoint)")
    with open(out, "ab+") as f:
        f.truncate(state["out_bytes"])  # drop anything written after the last commit
        f.seek(0, os.SEEK_END)
        while state["next_chunk"] < chunks and not stop_requested():
            if not parent_alive():
                os._exit(PARENT_GONE_RC)  # orphaned: the lease is the parent's, stop burning power
            cid = state["next_chunk"]
            digest = workload.run_chunk(cid)
            f.write(f"{cid} {digest}\n".encode())
            f.flush()
            os.fsync(f.fileno())
            if crash_after_append(cid):
                os._exit(97)
            state = {**state, "next_chunk": cid + 1, "out_bytes": f.tell(), "done": cid + 1 == chunks}
            checkpoint.save(ckpt, state, before_rename=(lambda: os._exit(98)) if crash_mid_ckpt(cid) else None)
    if stop_file.exists():  # consume the request only after the last chunk is committed
        stop_file.unlink(missing_ok=True)
    return state


def main(argv: list[str] | None = None) -> int:
    names = [j.name for j in load_catalogue()]
    p = argparse.ArgumentParser(prog="python -m jobs.runner", description=__doc__.splitlines()[0])
    p.add_argument("type", choices=names, help="job type from the catalogue")
    p.add_argument("--checkpoint", required=True, type=Path)
    p.add_argument("--out", type=Path, help="output log (default: <checkpoint>.out)")
    p.add_argument("--chunks", type=int, default=DEFAULT_CHUNKS)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--stop-file", type=Path, help="graceful-stop request file (default: <checkpoint>.stop)")
    p.add_argument("--parent-pid", type=int, help="exit 3 once this process (the live agent) is gone")
    a = p.parse_args(argv)
    if a.chunks <= 0 or a.rounds <= 0:
        p.error("--chunks and --rounds must be positive")
    alive = parent_watch(a.parent_pid)
    if not alive():
        return PARENT_GONE_RC
    out = a.out or a.checkpoint.with_name(a.checkpoint.name + ".out")
    state = run(a.type, a.checkpoint, out, a.chunks, HashWorkload(a.type, a.rounds), stop_file=a.stop_file,
                parent_alive=alive)
    print(json.dumps({"job_type": a.type, "next_chunk": state["next_chunk"], "chunks": a.chunks,
                      "done": state["done"], "out": str(out), "workload": "stand-in sha256"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
