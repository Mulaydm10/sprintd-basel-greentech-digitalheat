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
    s1 = W(("the", 3.0, 3.3), ("heat", 3.3, 3.6), ("goes", 3.6, 4.0))  # 'goes' touches the end -> probably cut
    k1 = stitch(s1, "and", seq=1, dur=4.0, overlap_s=1.0)
    assert text(k1) == "the heat"
    s2 = W(("heat", 0.0, 0.3), ("goes", 0.3, 0.7), ("into", 0.7, 0.9), ("the", 0.9, 1.1))
    assert text(stitch(s2, "and the heat", seq=2, dur=5.0, overlap_s=1.0)) == "goes into the"


def test_a_final_word_ending_before_the_edge_is_kept_and_seg0_keeps_its_start():
    s = W(("Right", 0.0, 0.18), ("now,", 0.18, 0.52), ("Basel.", 4.2, 4.6))
    assert text(stitch(s, "", seq=0, dur=4.71, overlap_s=0.0)) == "Right now, Basel."


def test_alignment_ignores_case_and_punctuation():
    seg = W(("House", 0.0, 0.4), ("every", 0.5, 0.8), ("hour", 0.8, 1.2))
    assert text(stitch(seg, "the house.", seq=1, dur=5.0, overlap_s=1.0)) == "every hour"
