"""Measure a real Whisper workload on this Mac and scale it to the 1 kW reference server (#5, measurement part).

    python -m jobs.measure clip   --out runs/measure/clip.wav [--seconds 120]
    python -m jobs.measure plan   --clip runs/measure/clip.wav [--runs 3] [--est-rtf 0.2]
    python -m jobs.measure run    --clip runs/measure/clip.wav --backend mlx|faster [--model M] [--runs 3]
                                  [--out runs/measure/run.json]
    python -m jobs.measure ingest --run runs/measure/run.json --powermetrics runs/measure/powermetrics.txt
                                  [--out src/jobs/measurements/whisper_m4.json]

Energy comes ONLY from a `powermetrics` log that the human runs with sudo alongside `run` (this module never
calls sudo). Scope: Apple-silicon package power (CPU + GPU + ANE), not DRAM/SSD/PSU; stated in the JSON.

Scaling to the reference server (method "energy-equivalence"): the same transcription work is assumed to cost
the same electrical energy on the reference server, so its runtime there is energy_kwh / server.electric_kw.
That number feeds `jobs:` runtime_h/energy_kwh. Design decides whether to adopt it (EXP row proposal printed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from common.config import ROOT, load_assumptions

DEFAULT_RUN = ROOT / "runs" / "measure" / "run.json"
DEFAULT_OUT = ROOT / "src" / "jobs" / "measurements" / "whisper_m4.json"
BACKENDS = {
    "mlx": "mlx-community/whisper-small-mlx",  # Metal (GPU) via mlx-whisper
    "faster": "small.en",  # CPU via faster-whisper / CTranslate2 (no Metal on macOS)
}
CLIP_TEXT = (
    "The district court of Basel considered the appeal on the twelfth of March. The applicant argued that the "
    "heating contract had been terminated without notice, and that the landlord owed a refund for the winter "
    "months. The court found that the notice period of three months applied, and that the refund was due for "
    "January and February only. Costs were divided equally between the parties. "
)


# ------------------------------------------------------------------ audio clip
def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_clip(out: Path, seconds: float = 120.0) -> Path:
    """Deterministic English speech via macOS `say`, 16 kHz mono WAV. Nothing is downloaded or committed."""
    if not shutil.which("say") or not shutil.which("afconvert"):
        raise SystemExit("make_clip needs macOS `say` and `afconvert`")
    out.parent.mkdir(parents=True, exist_ok=True)
    words_per_s = 2.6  # ~ say's default rate; only sizes the text, the real length is measured below
    reps = max(1, math.ceil(seconds * words_per_s / len(CLIP_TEXT.split())))
    txt = out.with_suffix(".txt")
    txt.write_text(CLIP_TEXT * reps)
    aiff = out.with_suffix(".aiff")
    subprocess.run(["say", "-o", str(aiff), "-f", str(txt)], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(out)], check=True)
    aiff.unlink(missing_ok=True)
    return out


# ------------------------------------------------------------------ transcription backends
def _mlx_backend(model: str) -> Callable[[Path], str]:
    import mlx_whisper  # type: ignore

    def run(clip: Path) -> str:
        return mlx_whisper.transcribe(str(clip), path_or_hf_repo=model)["text"]
    return run


def _faster_backend(model: str) -> Callable[[Path], str]:
    from faster_whisper import WhisperModel  # type: ignore

    m = WhisperModel(model, device="cpu", compute_type="int8")

    def run(clip: Path) -> str:
        segs, _ = m.transcribe(str(clip), beam_size=1)
        return " ".join(s.text for s in segs)
    return run


LOADERS: dict[str, Callable[[str], Callable[[Path], str]]] = {"mlx": _mlx_backend, "faster": _faster_backend}


def word_recall(reference: str, hypothesis: str) -> float:
    """Share of reference words (bag of words) found in the transcript: proves real work was done."""
    norm = lambda s: re.findall(r"[a-z]+", s.lower())  # noqa: E731
    ref, hyp = norm(reference), norm(hypothesis)
    if not ref:
        return 0.0
    pool: dict[str, int] = {}
    for w in hyp:
        pool[w] = pool.get(w, 0) + 1
    hit = 0
    for w in ref:
        if pool.get(w, 0) > 0:
            pool[w] -= 1
            hit += 1
    return hit / len(ref)


def _now() -> float:
    return time.time()


def run_measure(clip: Path, backend: str, model: str | None, runs: int, out: Path,
                loaders: dict = LOADERS, clock: Callable[[], float] = _now) -> dict:
    if backend not in loaders:
        raise SystemExit(f"backend {backend!r} not in {sorted(loaders)}")
    model = model or BACKENDS.get(backend, "")
    audio_s = wav_seconds(clip)
    ref_txt = clip.with_suffix(".txt").read_text() if clip.with_suffix(".txt").exists() else ""
    t0 = clock()
    fn = loaders[backend](model)
    t1 = clock()
    windows = []
    for i in range(runs):
        s = clock()
        text = fn(clip)
        e = clock()
        windows.append({"run": i, "start_epoch": s, "end_epoch": e, "wall_s": e - s,
                        "word_recall": round(word_recall(ref_txt, text), 4) if ref_txt else None,
                        "chars": len(text)})
    rec = {
        "workload": "whisper_transcription",
        "backend": backend, "model": model,
        "device": f"{platform.machine()} {platform.platform()}",
        "clip_sha256": sha256_file(clip), "clip_audio_s": round(audio_s, 3),
        "load_start_epoch": t0, "load_wall_s": t1 - t0,
        "runs": windows,
        "wall_s_median": statistics.median(w["wall_s"] for w in windows),
        "rtf_median": statistics.median(w["wall_s"] for w in windows) / audio_s,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2) + "\n")
    return rec


def powermetrics_command(n_samples: int, log: Path) -> str:
    return f"sudo powermetrics --samplers cpu_power,gpu_power -i 1000 -n {n_samples} -o {log}"


def plan(clip: Path, runs: int, est_rtf: float, log: Path) -> tuple[int, str]:
    """Samples needed: 30 s idle baseline + model load + runs x audio x rtf, with 50% margin."""
    audio_s = wav_seconds(clip)
    n = int(math.ceil(30 + 30 + 1.5 * runs * audio_s * est_rtf)) + 30
    return n, powermetrics_command(n, log)


# ------------------------------------------------------------------ powermetrics parsing
_HDR = re.compile(r"\*\*\* Sampled system activity \((?P<ts>[^)]*)\) \((?P<ms>[\d.]+)ms elapsed\) \*\*\*")
_PWR = re.compile(r"^(?P<k>CPU Power|GPU Power|ANE Power|Combined Power \(CPU \+ GPU \+ ANE\)):\s*(?P<v>[\d.]+)\s*mW",
                  re.M)


@dataclass(frozen=True)
class Sample:
    end_epoch: float
    elapsed_s: float
    watts: float  # package power: Combined if present, else CPU + GPU (+ ANE)


def parse_powermetrics(text: str) -> list[Sample]:
    heads = list(_HDR.finditer(text))
    out = []
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        vals: dict[str, float] = {}
        for m in _PWR.finditer(body):
            vals.setdefault(m["k"], float(m["v"]))  # first occurrence (GPU Power can repeat per sampler)
        if not vals:
            continue
        mw = vals.get("Combined Power (CPU + GPU + ANE)")
        if mw is None:
            mw = vals.get("CPU Power", 0.0) + vals.get("GPU Power", 0.0) + vals.get("ANE Power", 0.0)
        ts = datetime.strptime(h["ts"].strip(), "%a %b %d %H:%M:%S %Y %z").timestamp()
        out.append(Sample(ts, float(h["ms"]) / 1000.0, mw / 1000.0))
    return out


def _energy_in(samples: list[Sample], start: float, end: float) -> tuple[float, float]:
    """(joules, covered_seconds) of the samples' intervals overlapping [start, end] (pro-rata)."""
    j = cov = 0.0
    for s in samples:
        a, b = s.end_epoch - s.elapsed_s, s.end_epoch
        ov = min(b, end) - max(a, start)
        if ov > 0:
            j += s.watts * ov
            cov += ov
    return j, cov


def ingest(run: dict, samples: list[Sample], a: dict) -> dict:
    if not samples:
        raise SystemExit("no powermetrics samples parsed")
    first = min(w["start_epoch"] for w in run["runs"])
    idle = [s.watts for s in samples if s.end_epoch <= run["load_start_epoch"]]
    idle_w = statistics.median(idle) if idle else None
    per_run = []
    for w in run["runs"]:
        j, cov = _energy_in(samples, w["start_epoch"], w["end_epoch"])
        if cov < 0.8 * w["wall_s"]:
            raise SystemExit(f"run {w['run']}: powermetrics covers only {cov:.1f}s of {w['wall_s']:.1f}s; rerun with more -n")
        j *= w["wall_s"] / cov  # scale to the full window
        net = j - idle_w * w["wall_s"] if idle_w is not None else None
        per_run.append({"run": w["run"], "wall_s": w["wall_s"], "energy_j": j, "net_energy_j": net,
                        "mean_w": j / w["wall_s"]})
    audio_h = run["clip_audio_s"] / 3600.0
    e_j = statistics.median(r["energy_j"] for r in per_run)
    wall = statistics.median(r["wall_s"] for r in per_run)
    kwh_per_audio_h = e_j / 3.6e6 / audio_h
    kw_ref = float(a["server"]["electric_kw"])
    return {
        "measured": True,
        "workload": run["workload"], "backend": run["backend"], "model": run["model"], "device": run["device"],
        "clip_sha256": run["clip_sha256"], "clip_audio_s": run["clip_audio_s"], "runs": len(per_run),
        "per_run": per_run,
        "idle_w_median": idle_w,
        "wall_s_median": wall,
        "rtf_median": wall / run["clip_audio_s"],
        "mean_w_median": statistics.median(r["mean_w"] for r in per_run),
        "energy_kwh_per_audio_h": kwh_per_audio_h,
        "m4_wall_h_per_audio_h": wall / run["clip_audio_s"],
        "scaling_method": "energy-equivalence: ref runtime_h = energy_kwh / server.electric_kw",
        "ref_server_kw": kw_ref,
        "ref_runtime_h_per_audio_h": kwh_per_audio_h / kw_ref,
        "power_scope": "powermetrics package power (CPU+GPU+ANE); excludes DRAM, SSD, PSU losses",
        "source": "powermetrics --samplers cpu_power,gpu_power -i 1000 (run by Dhruv) + python -m jobs.measure",
        "first_run_epoch": first,
    }


def exp_row(m: dict, sha: str = "<commit>") -> str:
    return (f"| EXP-#### | whisper {m['model']} ({m['backend']}) on {m['device'].split()[0]} M4 | "
            f"{m['clip_audio_s']:.0f} s clip x {m['runs']} | RTF {m['rtf_median']:.3f}, "
            f"{m['mean_w_median']:.1f} W, {m['energy_kwh_per_audio_h'] * 1000:.1f} Wh/audio-h -> "
            f"ref {m['ref_runtime_h_per_audio_h']:.4f} h/audio-h | {sha} | src/jobs/measurements/whisper_m4.json |")


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jobs.measure")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clip"); c.add_argument("--out", type=Path, default=ROOT / "runs/measure/clip.wav")
    c.add_argument("--seconds", type=float, default=120.0)
    p = sub.add_parser("plan"); p.add_argument("--clip", type=Path, required=True)
    p.add_argument("--runs", type=int, default=3); p.add_argument("--est-rtf", type=float, default=0.2)
    p.add_argument("--log", type=Path, default=ROOT / "runs/measure/powermetrics.txt")
    r = sub.add_parser("run"); r.add_argument("--clip", type=Path, required=True)
    r.add_argument("--backend", choices=sorted(LOADERS), default="mlx"); r.add_argument("--model", default=None)
    r.add_argument("--runs", type=int, default=3); r.add_argument("--out", type=Path, default=DEFAULT_RUN)
    g = sub.add_parser("ingest"); g.add_argument("--run", type=Path, default=DEFAULT_RUN)
    g.add_argument("--powermetrics", type=Path, required=True); g.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ns = ap.parse_args(argv)

    if ns.cmd == "clip":
        out = make_clip(ns.out, ns.seconds)
        print(f"wrote {out} ({wav_seconds(out):.1f} s audio, sha256 {sha256_file(out)[:12]})")
    elif ns.cmd == "plan":
        n, cmd = plan(ns.clip, ns.runs, ns.est_rtf, ns.log)
        print("1) In terminal A (Dhruv), start this and leave it running:\n   " + cmd)
        print("2) Wait ~30 s (idle baseline), then in terminal B:\n   "
              f"python -m jobs.measure run --clip {ns.clip} --runs {ns.runs}")
        print(f"3) After powermetrics exits ({n} s):\n   python -m jobs.measure ingest --powermetrics {ns.log}")
    elif ns.cmd == "run":
        rec = run_measure(ns.clip, ns.backend, ns.model, ns.runs, ns.out)
        print(json.dumps({k: rec[k] for k in ("backend", "model", "clip_audio_s", "load_wall_s", "wall_s_median",
                                               "rtf_median")}, indent=1))
        print(f"wrote {ns.out}")
    elif ns.cmd == "ingest":
        run = json.loads(ns.run.read_text())
        m = ingest(run, parse_powermetrics(ns.powermetrics.read_text(errors="replace")), load_assumptions())
        ns.out.parent.mkdir(parents=True, exist_ok=True)
        ns.out.write_text(json.dumps(m, indent=2) + "\n")
        print(f"wrote {ns.out}\nEXP row proposal:\n{exp_row(m)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
