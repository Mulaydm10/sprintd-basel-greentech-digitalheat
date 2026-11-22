"""Transcriber backends for live transcription (#127, contracts/src/live_transcribe.md, Node agent section).

One interface: `Transcriber.transcribe(wav_bytes, context, seq) -> {"text", "words"}`. Each segment carries a 0.5 s
overlap prefix from the previous one; words that END within that prefix (t1 <= OVERLAP_S) are dropped, so stitching
the accepted texts in seq order neither repeats nor loses words.

- echo           tests / demo without models: "seg <n>"
- whisper-local  faster-whisper on this machine (model small.en, CUDA if available, int8): imported lazily, so the
                 agent runs without it unless chosen
- elevenlabs     ElevenLabs Scribe REST (CLOUD: disclosed on the pages); key from ELEVENLABS_API_KEY or --key-file,
                 never logged
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

OVERLAP_S = 1.0  # the client's overlap prefix (#127 boundary fix: 1.0 s, was 0.5 s); alignment copes with either
HOLD_TAIL_S = 0.8  # words ending in the last 0.8 s are held back and confirmed by the next overlap (#132)
MAX_LEAD = 2  # the repeated run must start within the first 2 words of a segment (a partial word may precede it)
NAMES = ("echo", "whisper-local", "elevenlabs")


def _norm(w: str) -> str:
    return "".join(ch for ch in str(w).lower() if ch.isalnum() or ch == "'")


def stitch(words: list[dict[str, Any]], context: str = "", seq: int = 1, dur: float | None = None,
           overlap_s: float = OVERLAP_S, final: bool = False) -> list[dict[str, Any]]:
    """The words of this segment to accept (#127 / #132 boundary fix).
    1. Overlap, by TEXT ALIGNMENT only: drop the LONGEST run of the accepted text's last words that reappears at the
       very start of this segment (it may start at word 0..MAX_LEAD, after a partial word). Ties -> the earliest start.
       Never by time alone, and never the latest match: in 'in your basement heat your home' aligning on the second
       'your' would drop real speech (#132 glitch 1).
    2. Hold back the TAIL: every word STARTING in the last HOLD_TAIL_S of the audio is left out (a word that
       started earlier begins before the next overlap, so it must be kept here). Whisper guesses
       speech cut by the boundary ('without losing control of the', #132 glitch 2); the next segment's 1.0 s overlap
       hears those words whole, and since they are not in the context yet the alignment keeps them there.
       The final segment of a stream (`final`) holds nothing back: the client's closing segment (the last overlap +
       silence) carries the last words."""
    # word fragments cut by the boundary ('trans-', #134: ElevenLabs returns them) are never accepted as words
    ws = [w for w in words if _norm(w.get("w", "")) and not str(w.get("w", "")).strip().endswith(("-", "\u2014", "\u2013"))]
    if dur is not None and not final and dur > HOLD_TAIL_S + 0.5:
        ws = [w for w in ws if float(w.get("t0", 0.0)) < dur - HOLD_TAIL_S]
    if seq == 0 or not ws:
        return ws
    prev = [_norm(x) for x in context.split() if _norm(x) and not x.endswith(("-", "\u2014", "\u2013"))][-30:]
    cur = [_norm(w["w"]) for w in ws]
    best = (0, 0)  # (k, -i): longest run, then earliest start
    for i in range(0, min(MAX_LEAD, len(cur) - 1) + 1):
        for kk in range(min(len(prev), len(cur) - i), 0, -1):
            if cur[i:i + kk] == prev[-kk:]:
                if (kk, -i) > best:
                    best = (kk, -i)
                break
    k, i = best[0], -best[1]
    return ws[i + k:] if k else ws


def _wav_seconds(wav: bytes) -> float | None:
    try:
        import wave
        with wave.open(io.BytesIO(wav), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:  # noqa: BLE001
        return None


def _join(ws) -> str:
    return " ".join(str(w["w"]).strip() for w in ws if str(w["w"]).strip()).replace("...", "").replace("  ", " ").strip()


def _dedupe(words: list[dict[str, Any]], seq: int = 1, context: str = "", wav: bytes | None = None,
            final: bool = False) -> tuple[str, list[dict[str, Any]], str]:
    """-> (text to accept, its words, the held-back TAIL text). The agent flushes the tail of the stream's last
    segment after /end (#134): the last words are otherwise only confirmed by a next segment that never comes."""
    dur = _wav_seconds(wav) if wav else None
    kept = stitch(words, context, seq, dur, final=final)
    whole = stitch(words, context, seq, dur, final=True)
    tail = whole[len(kept):] if whole[:len(kept)] == kept else []
    return _join(kept), kept, _join(tail)


def _pcm16_wav_to_float(wav: bytes):
    """16 kHz mono PCM16 WAV -> float32 array (no PyAV: some av versions reject faster-whisper's open() kwargs)."""
    import wave

    import numpy as np
    with wave.open(io.BytesIO(wav), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError("segment must be mono PCM16")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        rate = w.getframerate()
    if rate != 16000:  # linear resample (segments are specified as 16 kHz; this is only a guard)
        n = int(len(pcm) * 16000 / rate)
        pcm = np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.float32)
    return pcm


class EchoTranscriber:
    name = "echo"

    def transcribe(self, wav: bytes, context: str = "", seq: int = 0, final: bool = False) -> dict[str, Any]:
        return {"text": f"seg {seq}", "words": None}


class WhisperLocal:
    name = "whisper-local"

    def __init__(self, model: str = "small.en") -> None:
        from faster_whisper import WhisperModel  # lazy: only nodes that run Whisper need it
        try:
            import ctranslate2
            cuda = ctranslate2.get_cuda_device_count() > 0
        except Exception:  # noqa: BLE001
            cuda = False
        dev = os.environ.get("DH_WHISPER_DEVICE") or ("cuda" if cuda else "cpu")  # cpu when CUDA 12 libs are absent
        self.model = WhisperModel(model, device=dev, compute_type="int8_float16" if dev == "cuda" else "int8",
                                  cpu_threads=int(os.environ.get("DH_WHISPER_THREADS", "0")) or 0)

    def transcribe(self, wav: bytes, context: str = "", seq: int = 0, final: bool = False) -> dict[str, Any]:
        segs, _ = self.model.transcribe(_pcm16_wav_to_float(wav), language="en", word_timestamps=True, beam_size=1,
                                        initial_prompt=None, vad_filter=False)
        # no initial_prompt (#127 boundary fix): prompted with the accepted text, Whisper skips words that continue
        # it, including NEW speech right after the overlap ('losing a single word' vanished). The overlap is
        # transcribed honestly and stitch() removes the repeats by text alignment.
        words = [{"w": w.word, "t0": float(w.start), "t1": float(w.end)} for s in segs for w in (s.words or [])]
        text, kept, tail = _dedupe(words, seq, context, wav, final)
        return {"text": text, "words": kept, "tail": tail}


class ElevenLabs:
    name = "elevenlabs"
    URL = "https://api.elevenlabs.io/v1/speech-to-text"

    def __init__(self, key_file: Path | None = None, model: str = "scribe_v1") -> None:
        key = os.environ.get("ELEVENLABS_API_KEY") or (key_file.read_text().strip() if key_file else "")
        if not key:
            raise SystemExit("elevenlabs backend needs ELEVENLABS_API_KEY or --key-file")
        self._key, self.model = key, model

    def transcribe(self, wav: bytes, context: str = "", seq: int = 0, final: bool = False) -> dict[str, Any]:
        import httpx
        r = httpx.post(self.URL, headers={"xi-api-key": self._key}, timeout=30.0,
                       data={"model_id": self.model, "timestamps_granularity": "word", "language_code": "en"},
                       files={"file": (f"seg{seq}.wav", wav, "audio/wav")})
        if r.status_code != 200:
            raise RuntimeError(f"elevenlabs HTTP {r.status_code}")  # never echo the body (may contain the key)
        d = r.json()
        words = [{"w": w.get("text", ""), "t0": float(w.get("start", 0)), "t1": float(w.get("end", 0))}
                 for w in d.get("words", []) if w.get("type", "word") == "word"]
        if not words:
            return {"text": str(d.get("text", "")).strip(), "words": None}
        text, kept, tail = _dedupe(words, seq, context, wav, final)
        return {"text": text, "words": kept, "tail": tail}


def make(name: str, model: str = "small.en", key_file: Path | None = None):
    if name == "echo":
        return EchoTranscriber()
    if name == "whisper-local":
        return WhisperLocal(model)
    if name == "elevenlabs":
        return ElevenLabs(key_file)
    raise ValueError(f"unknown transcriber {name!r}; one of {NAMES}")
