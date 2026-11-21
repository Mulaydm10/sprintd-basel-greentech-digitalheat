"""Reference house: heat-demand formula and server heat. Constants come from data/assumptions.yaml."""
from __future__ import annotations

from common.config import load_assumptions


def house_params(a: dict | None = None) -> dict:
    """The `house:` block of assumptions.yaml (pass an already-loaded dict to avoid I/O)."""
    return (a or load_assumptions())["house"]


def heating_demand_kw(temp_c: float, heating_day: bool, house: dict | None = None) -> float:
    """COMPETITION.md: max(0, design_kw*(t_base - T)/span) on heating days, else 0."""
    h = house or house_params()
    if not heating_day:
        return 0.0
    return max(0.0, h["design_kw"] * (h["t_base_c"] - temp_c) / h["t_design_span_c"])


def server_heat_kw(electric_kw: float, a: dict | None = None) -> float:
    """Recoverable heat from a server drawing `electric_kw`."""
    return electric_kw * (a or load_assumptions())["server"]["heat_recovery_fraction"]
