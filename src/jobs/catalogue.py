"""Job catalogue (contracts/src/jobs.md). Every number comes from `jobs:` in data/assumptions.yaml.

Until the Mac measurement lands (EXP row, #5 runner part) the entries are placeholders whose
`source` says ASSUMED. `energy_kwh` is derived: runtime on the reference server x server.electric_kw.
"""
from __future__ import annotations

from dataclasses import dataclass

from common.config import load_assumptions

ACCESS_CLASSES = frozenset({"public", "swiss-only", "certified"})


@dataclass(frozen=True)
class JobType:
    name: str
    runtime_h: float  # on the 1 kW reference server
    energy_kwh: float
    interruptible: bool
    deadline_h: float  # from arrival
    access_class: str  # public | swiss-only | certified
    price_chf_per_h: float  # what the customer pays per server-hour (= scheduler bid)
    source: str
    jobs_per_day: float = 0.0  # mean arrivals/day used by jobs.arrivals
    measured: bool = False

    def __post_init__(self) -> None:
        if self.access_class not in ACCESS_CLASSES:
            raise ValueError(f"{self.name}: access_class {self.access_class!r} not in {sorted(ACCESS_CLASSES)}")
        if self.runtime_h <= 0 or self.energy_kwh < 0 or self.price_chf_per_h < 0 or self.jobs_per_day < 0:
            raise ValueError(f"{self.name}: runtime must be > 0; energy, price, jobs/day >= 0")
        if self.deadline_h < self.runtime_h:
            raise ValueError(f"{self.name}: deadline_h {self.deadline_h} < runtime_h {self.runtime_h}")
        if not self.source.strip():
            raise ValueError(f"{self.name}: every number needs a source")

    @property
    def slack_h(self) -> float:
        """How long the job can wait and still meet its deadline."""
        return self.deadline_h - self.runtime_h


def load_catalogue(a: dict | None = None) -> list[JobType]:
    """Build the catalogue from an assumptions dict (default: data/assumptions.yaml)."""
    a = a or load_assumptions()
    entries = a.get("jobs") or []
    if len(entries) < 2:
        raise ValueError("assumptions.yaml `jobs:` needs >= 2 job types (see PR for #5: proposed block)")
    kw = float(a["server"]["electric_kw"])
    out = []
    for e in entries:
        out.append(JobType(
            name=str(e["name"]),
            runtime_h=float(e["runtime_h"]),
            energy_kwh=float(e.get("energy_kwh", float(e["runtime_h"]) * kw)),
            interruptible=bool(e["interruptible"]),
            deadline_h=float(e["deadline_h"]),
            access_class=str(e["access_class"]),
            price_chf_per_h=float(e["price_chf_per_h"]),
            source=str(e["source"]),
            jobs_per_day=float(e.get("jobs_per_day", 0.0)),
            measured=bool(e.get("measured", False)),
        ))
    names = [j.name for j in out]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate job type names: {names}")
    return out


def by_name(catalogue: list[JobType]) -> dict[str, JobType]:
    return {j.name: j for j in catalogue}


def __getattr__(name: str):
    # CATALOGUE is resolved lazily so importing jobs never fails before assumptions.yaml has `jobs:`.
    if name == "CATALOGUE":
        return load_catalogue()
    raise AttributeError(name)
