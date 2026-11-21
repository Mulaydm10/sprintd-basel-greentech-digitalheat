"""Scheduler input types (contract v2, contracts/src/scheduler.md). Frozen, pure data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PolicyName = Literal["merit", "thermostat", "always_on"]
POLICIES: tuple[str, ...] = ("merit", "thermostat", "always_on")


class InvalidInput(ValueError):
    """decide() was given physically or logically invalid input (#21). Subclass of ValueError."""


@dataclass(frozen=True)
class SiteState:
    """One site at one tick. Energies in kWh, powers in kW, prices in CHF/kWh."""

    site_id: str
    hour_index: int
    demand_kw: float  # space-heat demand this hour
    tank_level_kwh: float
    tank_cap_kwh: float
    servers: int
    server_kw_el: float
    heat_recovery: float  # fraction of electric input recovered as useful heat
    p_el_chf_kwh: float
    heat_value_chf_kwh: float  # caller computes, see heat_value_chf_kwh() below
    eligible_classes: frozenset[str]
    night_cap_kw: float | None
    has_dump: bool
    band_low_kwh: float
    band_high_kwh: float
    mode_running: bool  # hysteresis state carried from the previous tick
    # Additive, not in contract v2: hot-water demand for Route (space -> dhw -> tank -> dump).
    # 0.0 means the caller folds hot water into demand_kw.
    dhw_demand_kw: float = 0.0

    @property
    def tank_room_kwh(self) -> float:
        return max(0.0, self.tank_cap_kwh - self.tank_level_kwh)

    def heat_room_kwh(self, step_h: float) -> float:
        """Heat (kWh) this site can use in one step: demand, then hot water, then tank room."""
        return max(0.0, self.demand_kw) * step_h + max(0.0, self.dhw_demand_kw) * step_h + self.tank_room_kwh


@dataclass(frozen=True)
class Unit:
    """~unit_minutes of work on the reference server."""

    unit_id: str
    job_id: str
    job_class: str
    access_class: str
    kwh_el: float
    bid_chf_per_server_h: float
    deadline_hour: int
    slack_h: float
    checkpointable: bool


@dataclass(frozen=True)
class Params:
    policy: PolicyName
    eta_heat_used: float
    slack_enabled: bool
    migration_margin_chf: float
    # Additive, not in contract v2: rule 4 "deadline - safety"; value from assumptions.yaml.
    deadline_safety_h: float

    def __post_init__(self) -> None:
        if self.policy not in POLICIES:
            raise ValueError(f"unknown policy {self.policy!r}; expected one of {POLICIES}")

    @classmethod
    def from_assumptions(cls, a: dict, policy: PolicyName = "merit", slack_enabled: bool = True) -> "Params":
        """Build from an already-loaded assumptions dict (no I/O here)."""
        s = a["scheduler"]
        return cls(
            policy=policy,
            eta_heat_used=float(s["eta_heat_used"]),
            slack_enabled=slack_enabled,
            migration_margin_chf=float(s["migration_margin_chf"]),
            deadline_safety_h=float(s["deadline_safety_h"]),
        )


def heat_value_chf_kwh(
    p_el_chf_kwh: float, heat_value_divisor: float, demand_kw: float, tank_level_kwh: float, band_high_kwh: float
) -> float:
    """Contract v2: p_el / divisor when heat is wanted (demand, or tank below band_high), else 0."""
    wanted = demand_kw > 0 or tank_level_kwh < band_high_kwh
    return p_el_chf_kwh / heat_value_divisor if wanted else 0.0
