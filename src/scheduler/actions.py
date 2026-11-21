"""Scheduler outputs (contract v2). Frozen dataclasses; the caller (sim or live agent) executes them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class SetPower:
    site_id: str
    servers_on: float  # may be fractional (duty cycle / power cap)


@dataclass(frozen=True)
class Assign:
    unit_id: str
    site_id: str


@dataclass(frozen=True)
class Hold:
    unit_id: str
    reason: str


@dataclass(frozen=True)
class Route:
    site_id: str
    space_kwh: float
    dhw_kwh: float
    tank_kwh: float
    dump_kwh: float

    @property
    def total_kwh(self) -> float:
        return self.space_kwh + self.dhw_kwh + self.tank_kwh + self.dump_kwh


@dataclass(frozen=True)
class Refuse:
    unit_id: str
    site_id: str
    reason: str


Action = Union[SetPower, Assign, Hold, Route, Refuse]


@dataclass(frozen=True)
class Decision:
    actions: list[Action]
    next_mode: dict[str, bool]
    trace: list[str] = field(default_factory=list)

    def of(self, kind: type) -> list:
        return [a for a in self.actions if isinstance(a, kind)]
