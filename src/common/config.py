"""Load data/assumptions.yaml (single source of truth for all numbers)."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_assumptions(path: Path | None = None) -> dict:
    with open(path or ROOT / "data" / "assumptions.yaml") as f:
        return yaml.safe_load(f)
