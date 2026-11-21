"""Lossless heat tank (contracts/src/house_model.md). Never below 0, never above capacity."""
from __future__ import annotations

from common.config import load_assumptions


class Tank:
    def __init__(self, capacity_kwh: float | None = None, level_kwh: float = 0.0):
        """capacity_kwh defaults to house.tank_kwh in assumptions.yaml (no hard-coded 35)."""
        cap = load_assumptions()["house"]["tank_kwh"] if capacity_kwh is None else capacity_kwh
        if cap < 0:
            raise ValueError("capacity_kwh must be >= 0")
        if not 0.0 <= level_kwh <= cap:
            raise ValueError(f"level_kwh {level_kwh} outside [0, {cap}]")
        self.capacity_kwh = float(cap)
        self.level_kwh = float(level_kwh)

    @property
    def room_kwh(self) -> float:
        return self.capacity_kwh - self.level_kwh

    def charge(self, kwh: float) -> float:
        """Store up to `kwh`; return what was accepted (the rest is the caller's to dump)."""
        if kwh < 0:
            raise ValueError("charge kwh must be >= 0")
        accepted = min(kwh, self.room_kwh)
        self.level_kwh = min(self.capacity_kwh, self.level_kwh + accepted)
        return accepted

    def draw(self, kwh: float) -> float:
        """Deliver up to `kwh`; return what was delivered (the rest is unmet demand)."""
        if kwh < 0:
            raise ValueError("draw kwh must be >= 0")
        delivered = min(kwh, self.level_kwh)
        self.level_kwh = max(0.0, self.level_kwh - delivered)
        return delivered

    def __repr__(self) -> str:
        return f"Tank(capacity_kwh={self.capacity_kwh}, level_kwh={self.level_kwh})"
