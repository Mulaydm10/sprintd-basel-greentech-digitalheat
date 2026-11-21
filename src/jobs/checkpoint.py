"""Crash-safe checkpoint files for resumable workloads (contracts/src/jobs.md, `jobs.runner`).

A checkpoint is a small JSON object. `save()` writes it to `<path>.tmp`, fsyncs, renames over
`<path>` (atomic on POSIX) and fsyncs the directory, so a reader sees either the previous
checkpoint or the new one, never a torn file, whatever moment the process dies at.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

# Test-only fault hook: called after the tmp file is durable and before the rename, i.e. the
# "mid-checkpoint" moment. The runner wires it to an env var so tests can crash exactly there.
_before_rename: Callable[[], None] | None = None


def _fsync_dir(d: Path) -> None:
    try:
        fd = os.open(d, os.O_RDONLY)
    except OSError:  # pragma: no cover - platforms without directory fds
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(path: str | Path, state: dict[str, Any]) -> None:
    """Atomically replace the checkpoint at `path` with `state`."""
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    data = json.dumps(state, sort_keys=True).encode()
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if _before_rename is not None:
        _before_rename()
    os.replace(tmp, p)
    _fsync_dir(p.parent)


def load(path: str | Path) -> dict[str, Any] | None:
    """Return the last committed checkpoint, or None if there is none yet.

    A leftover `<path>.tmp` from a crash mid-save is ignored (it was never committed).
    """
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text())
