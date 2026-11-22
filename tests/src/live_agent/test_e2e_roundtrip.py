from live_agent import e2e


def test_segment_and_text_roundtrip_and_non_recipient_cannot_open():
    a, b, phone = e2e.new_pair(), e2e.new_pair(), e2e.new_pair()
    blob = e2e.seal_segment(b"RIFF fake wav", {"omen": e2e.pub_b64(a)})
    assert e2e.open_segment(a, "omen", blob) == b"RIFF fake wav"
    try:
        e2e.open_segment(b, "laptop", blob)
        raise AssertionError("non-recipient opened the segment")
    except KeyError:
        pass
    enc = e2e.seal_text(e2e.pub_b64(phone), "good morning basel")
    assert "good morning" not in str(enc)
