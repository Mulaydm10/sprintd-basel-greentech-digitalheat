"""#127 segment-boundary fix: stitch() keeps every word exactly once across 4 s segments with an overlap prefix."""
from __future__ import annotations

from live_agent.transcriber import stitch


def W(*spec):
    return [{"w": w, "t0": a, "t1": b} for w, a, b in spec]


def text(ws):
    return " ".join(w["w"] for w in ws)


def test_repeated_overlap_words_are_dropped_by_alignment():
    seg = W(("the", 0.1, 0.3), ("house.", 0.3, 0.8), ("Every", 1.1, 1.4), ("hour", 1.4, 1.8))
    assert text(stitch(seg, "heating the house.", seq=1, dur=5.0, overlap_s=1.0)) == "Every hour"


def test_whisper_skipping_the_repeat_keeps_the_new_word_in_the_overlap():
    # prompted or not, Whisper may start at the first new word inside the overlap: it must be kept (the old time rule lost it)
    seg = W(("hour", 0.0, 0.84), ("the", 0.84, 1.08), ("scheduler", 1.08, 1.64))
    assert text(stitch(seg, "heating the house. Every", seq=1, dur=5.0, overlap_s=1.0)) == "hour the scheduler"


def test_a_cut_last_word_is_held_back_and_recovered_next_segment():
    s1 = W(("the", 3.0, 3.3), ("heat", 3.3, 3.6), ("goes", 3.6, 4.0))  # words starting in the last 0.8 s wait (#132)
    k1 = stitch(s1, "and", seq=1, dur=4.0, overlap_s=1.0)
    assert text(k1) == "the"
    s2 = W(("the", 0.0, 0.2), ("heat", 0.3, 0.6), ("goes", 0.6, 0.9), ("into", 0.9, 1.1), ("the", 1.1, 1.3))
    assert text(stitch(s2, "and the", seq=2, dur=5.0, overlap_s=1.0)) == "heat goes into the"


def test_a_final_word_ending_before_the_edge_is_kept_and_seg0_keeps_its_start():
    s = W(("Right", 0.0, 0.18), ("now,", 0.18, 0.52), ("Basel.", 4.2, 4.6))
    assert text(stitch(s, "", seq=0, dur=4.71, overlap_s=0.0, final=True)) == "Right now, Basel."
    assert text(stitch(s, "", seq=0, dur=4.71, overlap_s=0.0)) == "Right now,"  # not final: the tail waits


def test_alignment_ignores_case_and_punctuation():
    seg = W(("House", 0.0, 0.4), ("every", 0.5, 0.8), ("hour", 0.8, 1.2))
    assert text(stitch(seg, "the house.", seq=1, dur=5.0, overlap_s=1.0)) == "every hour"


def test_132_repeated_word_aligns_on_the_longest_early_run_not_the_latest():
    # 'Servers in your' accepted; the next segment hears 'your basement heat your home': aligning on the SECOND
    # 'your' would drop 'basement heat' (#132 glitch 1)
    seg = W(("your", 0.0, 0.2), ("basement", 0.2, 0.7), ("heat", 0.7, 0.95), ("your", 0.95, 1.1), ("home", 1.1, 1.5))
    assert text(stitch(seg, "Servers in your", seq=1, dur=5.0, overlap_s=1.0)) == "basement heat your home"


def test_132_tail_words_are_held_back_unless_final():
    seg = W(("the", 0.0, 0.2), ("machine", 3.0, 3.5), ("without", 4.3, 4.6), ("losing", 4.6, 4.95))  # tail may be guessed
    assert text(stitch(seg, "", seq=0, dur=5.0)) == "the machine"
    assert text(stitch(seg, "", seq=0, dur=5.0, final=True)) == "the machine without losing"


def _scribe(*items):  # the ElevenLabs Scribe JSON word shape: words + spacing items, punctuation attached
    out = []
    for w, t0, t1 in items:
        out += [{"text": w, "start": t0, "end": t1, "type": "word"}, {"text": " ", "start": t1, "end": t1, "type": "spacing"}]
    return {"text": " ".join(i[0] for i in items), "words": out}


def _el(monkeypatch, payload, dur=5.0):
    import io, wave
    from live_agent import transcriber as T
    class R:
        status_code = 200
        def json(self): return payload
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * int(16000 * dur))
    return T.ElevenLabs(), b.getvalue()


def test_134_scribe_overlap_with_casing_and_punctuation_is_removed(monkeypatch):
    el, wav = _el(monkeypatch, _scribe(("Basement", 0.0, 0.4), ("heat", 0.45, 0.7), ("your", 0.75, 0.95),
                                        ("home,", 1.0, 1.4), ("while", 1.5, 1.8)))
    out = el.transcribe(wav, "Servers in your basement heat your", seq=6)
    assert out["text"] == "home, while"


def test_134_scribe_hyphen_fragment_is_never_accepted_and_next_segment_aligns(monkeypatch):
    el, wav = _el(monkeypatch, _scribe(("Right", 2.0, 2.3), ("now,", 2.3, 2.6), ("this", 2.7, 3.0), ("trans-", 3.0, 3.4)))
    a = el.transcribe(wav, "", seq=0)
    assert "trans" not in a["text"]
    el2, wav2 = _el(monkeypatch, _scribe(("now", 0.0, 0.2), ("this", 0.25, 0.45), ("transcription", 0.5, 1.2),
                                          ("is", 1.3, 1.4), ("running", 1.5, 1.9)))
    assert el2.transcribe(wav2, "Right now, this trans-", seq=7)["text"] == "transcription is running"


def test_134_held_tail_is_returned_for_the_final_flush(monkeypatch):
    el, wav = _el(monkeypatch, _scribe(("we", 1.0, 1.2), ("keep", 4.3, 4.6), ("going.", 4.6, 4.9)))
    out = el.transcribe(wav, "", seq=0)
    assert out["text"] == "we" and out["tail"] == "keep going."
    assert el.transcribe(wav, "", seq=0, final=True)["text"] == "we keep going."
