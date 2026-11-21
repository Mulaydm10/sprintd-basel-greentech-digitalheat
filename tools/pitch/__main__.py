"""python -m tools.pitch [--out research/PITCH_NUMBERS.md] [--runs runs/pitch] [--sweep] [--servers 4]

Runs the canonical runs (same paid stream for every policy: load = thermostat utilisation, slack 24 h):
thermostat, always_on, merit, merit + ballast at N (default 4); optionally the full sweep; the decision card
when #31's analysis is on main. Then writes PITCH_NUMBERS.md (proposed; design commits it).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from common.config import ROOT, load_assumptions

from .numbers import PitchNumber, assumed_paths, numbers_for_run, render_markdown

SLACK_H = 24.0  # the pitch's reference patience (Run B); stated in the output header
CANON = [  # (title, policy, ballast)
    ("thermostat", "thermostat", False),
    ("always_on", "always_on", False),
    ("merit", "merit", False),
    ("merit + ballast", "merit", True),
]


def code_sha() -> tuple[str, bool]:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                                    capture_output=True, text=True).stdout.strip())
        return sha, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


def run_canonical(runs_root: Path, servers: int, seed: int = 0) -> list[tuple[str, Path]]:
    from simulate_year.cli import run_one
    out = []
    for title, policy, ballast in CANON:
        d = runs_root / f"{policy}{'-ballast' if ballast else ''}-n{servers}-slack{SLACK_H!r}-loadthermostat-seed{seed}"
        if d.exists():
            shutil.rmtree(d)
        run_one(servers, policy, SLACK_H, "thermostat", seed, d, ballast=ballast)
        out.append((title, d))
    return out


def build(runs_root: Path, servers: int, with_sweep: bool) -> tuple[list[PitchNumber], dict]:
    sha, dirty = code_sha()
    text = (ROOT / "data" / "assumptions.yaml").read_text()
    assumed = assumed_paths(text)
    nums: list[PitchNumber] = []
    for i, (title, d) in enumerate(run_canonical(runs_root, servers)):
        nums += numbers_for_run(d, f"{title} (N={servers}, same paid work)", assumed, sha[:12], house=i == 0)
    notes = [f"Same paid stream for every policy: --load thermostat (paid work = the thermostat's utilisation), "
             f"slack {SLACK_H:g} h, seed 0. Ballast = unlimited filler at ballast.bid (#37)."]
    if with_sweep:
        from simulate_year.cli import sweep
        p = sweep(runs_root / "sweep", 0, None)
        notes.append(f"Sweep: `{p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}` ({sweep.failed} failed cells).")
    try:
        from simulate_year import analysis  # noqa: F401  (#31)
        notes.append("Decision card: run `python -m simulate_year --decision-card` (#31) and add its numbers here.")
    except ImportError:
        notes.append("Decision card: pending #31 (simulate_year.analysis not on main yet).")
    import hashlib
    header = {"code_sha": sha, "dirty": dirty, "assumptions_hash": hashlib.sha256(text.encode()).hexdigest(),
              "runs_root": str(runs_root.relative_to(ROOT) if runs_root.is_relative_to(ROOT) else runs_root),
              "assumed": sorted(assumed), "notes": notes}
    return nums, header


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.pitch")
    ap.add_argument("--out", type=Path, default=ROOT / "research" / "PITCH_NUMBERS.md")
    ap.add_argument("--runs", type=Path, default=ROOT / "runs" / "pitch")
    ap.add_argument("--servers", type=int, default=4)
    ap.add_argument("--sweep", action="store_true", help="also run the full sweep (~4 min)")
    ns = ap.parse_args(argv)
    load_assumptions()  # validates (ConfigError) before any run
    nums, header = build(ns.runs, ns.servers, ns.sweep)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(render_markdown(nums, header))
    n_assumed = sum(n.assumed for n in nums)
    print(f"wrote {ns.out}: {len(nums)} numbers, {n_assumed} ASSUMED, code {header['code_sha'][:12]}"
          f"{' (dirty)' if header['dirty'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
