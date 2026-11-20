"""Heat-aware scheduling policy. Pure: no I/O, no process control. TODO."""


def decide(heat_signal_kw: float, tank_kwh: float, tank_cap_kwh: float = 35.0) -> str:
    """Return 'run' or 'pause' for an interruptible job."""
    return "run" if tank_kwh < tank_cap_kwh and heat_signal_kw > 0 else "pause"
