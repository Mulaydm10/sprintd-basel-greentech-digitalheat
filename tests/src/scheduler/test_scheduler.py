from scheduler.policy import decide


def test_pause_when_tank_full():
    assert decide(0.8, 35.0) == "pause"
