"""#132 boundary check: transcribe a clip once (single pass) and as the phone does (4 s + 1.0 s overlap + closing
segment), stitch with live_agent.transcriber.stitch, and diff the words.

    python tools/demo/stitch_check.py src clip.wav [4.0] [1.0] [--backend mlx|faster]

mlx: mlx_whisper + mlx-community/whisper-small-mlx (Mac). faster: faster_whisper small.en on CPU (the Omen path).
Make a clip: say -o c.aiff "..." && afconvert -f WAVE -d LEI16@16000 -c 1 c.aiff c.wav  (or any 16 kHz mono WAV)
"""
import io, sys, wave, difflib
import numpy as np
sys.path.insert(0, sys.argv[1])
from live_agent.transcriber import stitch, _norm
BACKEND = "faster" if "--backend" in sys.argv and sys.argv[sys.argv.index("--backend") + 1] == "faster" else "mlx"
sys.argv = [a for k, a in enumerate(sys.argv) if a != "--backend" and (k == 0 or sys.argv[k - 1] != "--backend")]
if BACKEND == "mlx":
    import mlx_whisper
    REPO = "mlx-community/whisper-small-mlx"
else:
    from faster_whisper import WhisperModel
    FW = WhisperModel("small.en", device="cpu", compute_type="int8")
with wave.open(sys.argv[2], "rb") as w:
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
SR, SEG, OV = 16000, float(sys.argv[3]) if len(sys.argv) > 3 else 4.0, float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
def words_of(a, prompt=None):
    if BACKEND == "faster":
        segs, _ = FW.transcribe(a, language="en", word_timestamps=True, beam_size=1, vad_filter=False)
        return [{"w": w.word, "t0": float(w.start), "t1": float(w.end)} for s in segs for w in (s.words or [])]
    r = mlx_whisper.transcribe(a, path_or_hf_repo=REPO, word_timestamps=True, language="en", initial_prompt=prompt or None)
    return [{"w": w["word"], "t0": float(w["start"]), "t1": float(w["end"])} for s in r["segments"] for w in s.get("words", [])]
single = [_norm(w["w"]) for w in words_of(pcm) if _norm(w["w"])]
acc, n = [], 0
while n * SEG < len(pcm) / SR:
    a0 = max(0.0, n * SEG - (OV if n else 0)); a1 = min(len(pcm) / SR, (n + 1) * SEG)
    seg = pcm[int(a0 * SR):int(a1 * SR)]
    ctx = " ".join(acc)
    ws = words_of(seg, None)
    kept = stitch(ws, ctx, n, a1 - a0, OV if n else 0.0)
    acc += [w["w"].strip() for w in kept]
    n += 1
# the phone's closing segment on End (#132): the last overlap + 0.5 s silence, so the held-back tail is confirmed
tail = np.concatenate([pcm[max(0, len(pcm) - int(OV * SR)):], np.zeros(int(0.5 * SR), dtype=np.float32)])
ctx = " ".join(acc); ws = words_of(tail, None)
acc += [w["w"].strip() for w in stitch(ws, ctx, n, len(tail) / SR, OV, final=True)]
stitched = [_norm(x) for x in acc if _norm(x)]
print("segments", n, "| single", len(single), "words | stitched", len(stitched), "words | equal:", stitched == single)
for op in difflib.SequenceMatcher(a=single, b=stitched).get_opcodes():
    if op[0] != "equal": print(" ", op[0], "single:", single[op[1]:op[2]], "stitched:", stitched[op[3]:op[4]])
