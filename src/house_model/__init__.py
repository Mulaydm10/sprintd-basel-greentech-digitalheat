"""house_model: reference house — hourly demand profile (Open-Meteo Basel 2025), lossless tank, server heat."""
from .model import heating_demand_kw, server_heat_kw
from .profile import load_reference_profile
from .tank import Tank

__all__ = ["heating_demand_kw", "server_heat_kw", "load_reference_profile", "Tank"]
