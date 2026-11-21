> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# src/simulate_year

Runs scheduler against 2025 hourly weather; outputs the yearly balance table and break-even.

Conventions: type hints, no hard-coded assumptions (read `data/assumptions.yaml` via `common.config`), unit-test in `tests/`.

## Year view (#95, schema `yearview-v1`)
```
python -m simulate_year.yearview [--out runs/yearview] [--workers W] [--force] [--max-dump-share 0.10]
```
- **What it runs:** N = 1..8 servers on Basel 2025 and the reference house. *Ours* = merit + heat-backed ballast, slack 24 h, paid load 0.6 (the decision card's reference). *Baseline* = thermostat with the **same** slack and paid load (like-for-like).
- **What it writes:**
  - `runs/yearview/<key>/index.json`: settings, constants, per-N summaries, sizing.
  - `runs/yearview/<key>/n<N>.json`: 8760-hour columnar arrays for ours + baseline.
  - `runs/yearview/LATEST`: the newest complete key.
  - `balance.json`, `hourly.csv`, `sweep.csv` (merit/thermostat/always_on × N) for the existing dashboard panels.
- **Speed:** about 7 s on the M4 (32 runs in a process pool).
- **Cache key:** sha256 of schema, assumptions, weather file, settings, sizing rule and simulator/scheduler source. A complete key folder is reused unless `--force`.
- **Invariants (tests):** each hourly array sums to its summary total, and the last `net_chf_cum` equals `net_chf_excl_hardware`. Numbers are deterministic per key.
- **Sizing:** among N with 0 % missed and dumped ≤ `max_dump_share` × demand, the smallest N within 0.1 pp of the best coverage. Separately, the N with the lowest paid price to pay off incl. hardware. Both are printed with their reasoning.
