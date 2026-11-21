"""Measured node power for heartbeats (contract live_agent v2, step 2). Never invented: no readable source → None.

Sources, first that works:
- ``powermetrics-file``: macOS. ``powermetrics`` needs root, so a human runs a sampler that writes the current
  watts (one float) to ``<workdir>/watts.txt``; it counts only if updated within the last 10 s.
- ``rapl``: Linux Intel/AMD RAPL, ``/sys/class/powercap/intel-rapl:0/energy_uj`` (energy counter, delta / dt).
- ``nvml``: NVIDIA GPUs via ``pynvml`` if it is installed and a GPU answers (sum over devices).
"""
from __future__ import annotations

import time
from pathlib import Path

RAPL = Path("/sys/class/powercap/intel-rapl:0")
FRESH_S = 10.0


class PowerMeter:
    def __init__(self, workdir: Path, rapl_dir: Path = RAPL, clock=time.monotonic, wall=time.time) -> None:
        self.sampler_file = workdir / "watts.txt"
        self.rapl_dir = rapl_dir
        self.clock, self.wall = clock, wall
        self._rapl_last: tuple[float, int] | None = None

    def read(self) -> tuple[float | None, str]:
        for name, fn in (("powermetrics-file", self._sampler), ("rapl", self._rapl), ("nvml", self._nvml)):
            try:
                w = fn()
            except Exception:  # an unreadable source is "no measurement", never a crash
                w = None
            if w is not None:
                return round(w, 2), name
        return None, "none"

    def _sampler(self) -> float | None:
        f = self.sampler_file
        if not f.exists() or self.wall() - f.stat().st_mtime > FRESH_S:
            return None
        w = float(f.read_text().strip())
        return w if 0 <= w < 100_000 else None

    def _rapl(self) -> float | None:
        energy = self.rapl_dir / "energy_uj"
        if not energy.exists():
            return None
        e, t = int(energy.read_text()), self.clock()
        last, self._rapl_last = self._rapl_last, (t, e)
        if last is None or t <= last[0]:
            return None  # first sample: need a delta
        de = e - last[1]
        if de < 0:  # counter wrapped
            de += int((self.rapl_dir / "max_energy_range_uj").read_text())
        return de / 1e6 / (t - last[0])

    @staticmethod
    def _nvml() -> float | None:
        import pynvml  # optional; not a project dependency
        pynvml.nvmlInit()
        try:
            n = pynvml.nvmlDeviceGetCount()
            if n == 0:
                return None
            return sum(pynvml.nvmlDeviceGetPowerUsage(pynvml.nvmlDeviceGetHandleByIndex(i)) for i in range(n)) / 1000
        finally:
            pynvml.nvmlShutdown()
