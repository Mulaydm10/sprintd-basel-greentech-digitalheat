"""Found live (design, 2026-11-22): a live job was leased to a batch node (cpu-hash), lapsing forever."""
from coordinator import transcribe as ts


def test_only_transcriber_backends_may_hold_live_jobs():
    assert "cpu-hash" not in ts.TRANSCRIBERS and None not in ts.TRANSCRIBERS
    assert {"whisper-local", "elevenlabs", "echo"} <= ts.TRANSCRIBERS
