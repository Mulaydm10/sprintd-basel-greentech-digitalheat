"""jobs.measure (#5 measurement harness): no model, no sudo, no network. A fake backend + synthetic
powermetrics text exercise run -> ingest -> scaling end to end."""
from __future__ import annotations

import json
import math
import shutil
import struct
import wave
from datetime import datetime, timezone

import pytest

from common.config import load_assumptions
from jobs.measure import (CLIP_TEXT, exp_row, ingest, make_clip, parse_powermetrics, plan, powermetrics_command,
                          run_measure, wav_seconds, word_recall)

A = load_assumptions()


def silent_wav(path, seconds=10.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))
    return path


def pm_text(start_epoch: float, watts: list[float]) -> str:
    """powermetrics-style text: one 1 s sample per entry, ending at start+1, start+2, ..."""
    out = []
    for i, w in enumerate(watts):
        ts = datetime.fromtimestamp(start_epoch + i + 1, tz=timezone.utc).astimezone()
        hdr = ts.strftime("%a %b %d %H:%M:%S %Y %z")
        cpu, gpu = int(w * 1000 * 0.25), int(w * 1000 * 0.75)
        out.append(f"*** Sampled system activity ({hdr}) (1000.00ms elapsed) ***\n\n**** Processor usage ****\n"
                   f"CPU Power: {cpu} mW\nGPU Power: {gpu} mW\nANE Power: 0 mW\n"
                   f"Combined Power (CPU + GPU + ANE): {cpu + gpu} mW\n\n**** GPU usage ****\nGPU Power: {gpu} mW\n")
    return "\n".join(out)


class FakeClock:
    def __init__(self, t0): self.t = t0
    def __call__(self): return self.t


def test_wav_seconds(tmp_path):
    assert wav_seconds(silent_wav(tmp_path / "a.wav", 7.5)) == pytest.approx(7.5)


def test_word_recall():
    assert word_recall("a b c d", "A, b... c") == pytest.approx(0.75)
    assert word_recall("", "x") == 0.0


def test_plan_command_has_samplers_interval_and_count(tmp_path):
    n, cmd = plan(silent_wav(tmp_path / "c.wav", 100), runs=3, est_rtf=0.2, log=tmp_path / "pm.txt")
    assert cmd == powermetrics_command(n, tmp_path / "pm.txt")
    assert cmd.startswith("sudo powermetrics --samplers cpu_power,gpu_power -i 1000 -n ")
    assert n >= 30 + 30 + 3 * 100 * 0.2


def test_parse_prefers_combined_and_ignores_repeated_gpu():
    s = parse_powermetrics(pm_text(1_700_000_000, [10.0, 20.0]))
    assert [x.watts for x in s] == [pytest.approx(10.0), pytest.approx(20.0)]
    assert s[1].end_epoch - s[0].end_epoch == pytest.approx(1.0)


def test_parse_without_combined_sums_cpu_gpu():
    txt = pm_text(1_700_000_000, [8.0]).replace("Combined Power (CPU + GPU + ANE)", "Other")
    assert parse_powermetrics(txt)[0].watts == pytest.approx(8.0)


def test_run_then_ingest_end_to_end(tmp_path):
    clip = silent_wav(tmp_path / "clip.wav", 60.0)
    (tmp_path / "clip.txt").write_text(CLIP_TEXT)
    t0 = 1_700_000_000.0
    clock = FakeClock(t0 + 30)  # 30 s idle first

    def fake_loader(model):
        clock.t += 5  # model load 5 s

        def run(_clip):
            clock.t += 12  # each transcription 12 s
            return CLIP_TEXT
        return run

    rec = run_measure(clip, "fake", "m", 3, tmp_path / "run.json", loaders={"fake": fake_loader}, clock=clock)
    assert rec["rtf_median"] == pytest.approx(12 / 60)
    assert all(w["word_recall"] == 1.0 for w in rec["runs"])
    # 30 s idle @ 4 W, 5 s load @ 15 W, 36 s busy @ 25 W, tail idle
    watts = [4.0] * 30 + [15.0] * 5 + [25.0] * 36 + [4.0] * 10
    m = ingest(json.loads((tmp_path / "run.json").read_text()), parse_powermetrics(pm_text(t0, watts)), A)
    assert m["measured"] is True and m["runs"] == 3
    assert m["idle_w_median"] == pytest.approx(4.0)
    assert m["mean_w_median"] == pytest.approx(25.0)
    e_kwh_audio_h = 25.0 * 12 / 3.6e6 / (60 / 3600)
    assert m["energy_kwh_per_audio_h"] == pytest.approx(e_kwh_audio_h)
    assert m["ref_runtime_h_per_audio_h"] == pytest.approx(e_kwh_audio_h / A["server"]["electric_kw"])
    assert m["per_run"][0]["net_energy_j"] == pytest.approx((25 - 4) * 12)
    assert "EXP-####" in exp_row(m) and "Wh/audio-h" in exp_row(m)


def test_ingest_refuses_uncovered_window(tmp_path):
    run = {"load_start_epoch": 100.0, "clip_audio_s": 60.0, "workload": "w", "backend": "b", "model": "m",
           "device": "arm64", "clip_sha256": "x",
           "runs": [{"run": 0, "start_epoch": 200.0, "end_epoch": 220.0, "wall_s": 20.0}]}
    with pytest.raises(SystemExit, match="covers only"):
        ingest(run, parse_powermetrics(pm_text(195.0, [10.0] * 5)), A)


@pytest.mark.skipif(not (shutil.which("say") and shutil.which("afconvert")), reason="macOS say/afconvert only")
def test_make_clip_is_real_audio(tmp_path):
    out = make_clip(tmp_path / "c.wav", seconds=8)
    assert wav_seconds(out) > 3 and (tmp_path / "c.txt").exists()
