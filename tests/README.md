> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# tests

pytest, `uv run pytest`. One test module per package (`test_<pkg>.py`). Tests must not download data or models. Key invariant tests: demand total ~27,000 kWh and 206 heating days once weather is loaded; scheduler gives identical decisions in simulator and live runner.
