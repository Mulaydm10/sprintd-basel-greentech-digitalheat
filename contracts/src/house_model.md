# contract: src/house_model  (design-owned; workers read, never write)

Exposes `house_model.profile`:
- `load_reference_profile(path=None) -> pandas.DataFrame` indexed by hourly tz-aware timestamps (Europe/Zurich), 8,760 rows for 2025, columns:
  `temp_c`, `ghi_wm2`, `heating_day: bool`, `space_heat_kw`, `hot_water_kw` (=12/24), `demand_kw` (= space + hot water).
  Formula exactly as COMPETITION.md: `space_heat_kw = max(0, 10*(20-T)/25.6)` on heating days (local-day mean T < 12 °C).
  Source CSV: `data/raw/basel_2025_hourly.csv` (Open-Meteo archive; fetch script `python -m house_model.fetch`).
- `class Tank(capacity_kwh=35.0, level_kwh=0.0)`: `charge(kwh) -> accepted_kwh`, `draw(kwh) -> delivered_kwh`; lossless; never <0 or >capacity.
Invariants (tested): sum(space_heat) ≈ 26,851 kWh ±1%; 206 heating days; min temp −5.6 °C.
