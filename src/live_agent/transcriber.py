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

OVERLAP_S = 0.5
NAMES = ("echo", "whisper-local", "elevenlabs")


def _dedupe(words: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    kept = [w for w in words if float(w.get("t1", 0.0)) > OVERLAP_S]
    return " ".join(str(w["w"]).strip() for w in kept if str(w["w"]).strip()), kept


class EchoTranscriber:
    name = "echo"

    def transcribe(self, wav: bytes, context: str = "", seq: int = 0) -> dict[str, Any]:
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
        self.model = WhisperModel(model, device="cuda" if cuda else "cpu", compute_type="int8_float16" if cuda else "int8")

    def transcribe(self, wav: bytes, context: str = "", seq: int = 0) -> dict[str, Any]:
        segs, _ = self.model.transcribe(io.BytesIO(wav), language="en", word_timestamps=True, beam_size=1,
                                        initial_prompt=context[-200:] or None, vad_filter=False)
        words = [{"w": w.word, "t0": float(w.start), "t1": float(w.end)} for s in segs for w in (s.words or [])]
        text, kept = _dedupe(words)
        return {"text": text, "words": kept}


class ElevenLabs:
    name = "elevenlabs"
    URL = "https://api.elevenlabs.io/v1/speech-to-text"

    def __init__(self, key_file: Path | None = None, model: str = "scribe_v1") -> None:
        key = os.environ.get("ELEVENLABS_API_KEY") or (key_file.read_text().strip() if key_file else "")
        if not key:
            raise SystemExit("elevenlabs backend needs ELEVENLABS_API_KEY or --key-file")
        self._key, self.model = key, model

    def transcribe(self, wav: bytes, context: str = "", seq: int = 0) -> dict[str, Any]:
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
        text, kept = _dedupe(words)
        return {"text": text, "words": kept}


def make(name: str, model: str = "small.en", key_file: Path | None = None):
    if name == "echo":
        return EchoTranscriber()
    if name == "whisper-local":
        return WhisperLocal(model)
    if name == "elevenlabs":
        return ElevenLabs(key_file)
    raise ValueError(f"unknown transcriber {name!r}; one of {NAMES}")
