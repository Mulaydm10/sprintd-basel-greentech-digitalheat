"""Reference house. TODO: implement hourly demand, tank, server heat."""


def heating_demand_kw(temp_c: float, heating_day: bool) -> float:
    return max(0.0, 10.0 * (20.0 - temp_c) / 25.6) if heating_day else 0.0
