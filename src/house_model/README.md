> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# src/house_model

Hourly heat demand (10 kW*(20-T)/25.6 on heating days), hot water 12 kWh/day, 35 kWh lossless tank, server heat 0.8 kW per 1 kW.

Conventions: type hints, no hard-coded assumptions (read `data/assumptions.yaml` via `common.config`), unit-test in `tests/`.
