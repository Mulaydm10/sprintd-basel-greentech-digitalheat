"""Job types. TODO: measured runtime/energy, deadlines, access class."""
from dataclasses import dataclass


@dataclass(frozen=True)
class JobType:
    name: str
    runtime_h: float
    energy_kwh: float
    interruptible: bool
    deadline_h: float
    access_class: str = "public"  # public | swiss-only | certified
