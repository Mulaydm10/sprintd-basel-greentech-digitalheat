# contract: src/jobs

- `jobs.catalogue.JobType` (frozen dataclass): `name, runtime_h (on 1 kW ref server), energy_kwh, interruptible: bool, deadline_h (from arrival), access_class in {public, swiss-only, certified}, price_chf_per_h, source: str` (where each number comes from).
- `jobs.catalogue.CATALOGUE: list[JobType]` — ≥2 types; ≥1 has `measured=True` with a `measurements/` JSON (runtime, energy, device W, scaling method to 1 kW).
- `jobs.arrivals.daily_arrivals(day, rng) -> list[Job]` where `Job(id, type: JobType, arrival: datetime, remaining_h: float)`; the jobs/day number and its source are a module constant + docstring. Unlimited-backlog mode must be an explicit flag.
- `jobs.runner`: real workload entrypoint `python -m jobs.runner <type> --checkpoint <path>`: resumable; on SIGTERM writes checkpoint and exits 0; on restart resumes from checkpoint with no repeated work. Must also tolerate SIGSTOP/SIGCONT.
