"""Pitch-number extraction (#47). Pure functions over run folders + the assumptions text, so tests can drive them.

A pitch number = (label, value, source file, key, run id, assumptions hash, code sha, ASSUMED inputs).
ASSUMED detection reads data/assumptions.yaml as TEXT, because the markers live in comments and `source`
strings: a key is ASSUMED if its own line says ASSUMED, if an enclosing section header says so, or (for list
entries such as `jobs:`) if any line of that entry says so. A number is ASSUMED if any input section it
depends on (DEPENDS below) contains an ASSUMED key.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ASSUMED_RE = re.compile(r"\bASSUMED\b")


def assumed_paths(yaml_text: str) -> set[str]:
    """Dotted paths ('hardware', 'ballast.bid_chf_per_server_h', 'jobs[1]') marked ASSUMED in the yaml text."""
    out: set[str] = set()
    stack: list[tuple[int, str]] = []  # (indent, path) of open mapping keys
    list_idx: dict[str, int] = {}
    entry_path: str | None = None
    entry_indent = -1
    for raw in yaml_text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") and not ASSUMED_RE.search(raw):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if entry_path is not None and indent <= entry_indent and not line.startswith("- "):
            entry_path = None
        while stack and stack[-1][0] >= indent and not (line.startswith("- ") and stack[-1][0] < indent):
            stack.pop()
        parent = stack[-1][1] if stack else ""
        if line.startswith("- "):
            i = list_idx.get(parent, -1) + 1
            list_idx[parent] = i
            entry_path, entry_indent = f"{parent}[{i}]", indent
            line = line[2:]
            indent += 2
        m = re.match(r"([A-Za-z_][\w-]*)\s*:", line)
        if m:
            base = entry_path if entry_path and indent > entry_indent else parent
            path = f"{base}.{m.group(1)}" if base else m.group(1)
            stack.append((indent, path))
            if ASSUMED_RE.search(raw):
                out.add(entry_path if entry_path and indent > entry_indent else path)
        elif ASSUMED_RE.search(raw) and entry_path:
            out.add(entry_path)
    return out


def section_assumed(paths: set[str], section: str) -> list[str]:
    return sorted(p for p in paths if p == section or p.startswith(section + ".") or p.startswith(section + "["))


# Which assumption sections each balance key depends on (physics: house/server/price/scheduler; the paid stream
# and its bids: jobs; filler: ballast; capex: hardware).
PHYSICS = ("location", "house", "server", "price", "scheduler")
STREAM_KEYS = {"missed_deadline_pct", "compute_income_chf", "paid_run_h", "jobs_total", "units_done",
               "admitted_units", "rejected_units"}


def depends(balance: dict, key: str) -> list[str]:
    deps = list(PHYSICS)
    if balance.get("policy") == "merit" or key in STREAM_KEYS:
        deps.append("jobs")
    # filler bid matters only when filler is sold (merit --ballast) or for its income; the baselines'
    # implicit ballast hours (run - paid) do not depend on it
    if balance.get("ballast") or key == "ballast_income_chf":
        deps.append("ballast")
    if "hardware" in key or key.startswith("pays_off"):
        deps.append("hardware")
    if key.startswith("pays_off") and "jobs" not in deps:
        deps.append("jobs")  # paid server-hours and the paid price come from the paid stream
    return deps


@dataclass
class PitchNumber:
    label: str
    value: object
    file: str
    key: str
    run_id: str
    assumptions_hash: str
    code_sha: str
    assumed_inputs: list[str] = field(default_factory=list)

    @property
    def assumed(self) -> bool:
        return bool(self.assumed_inputs)


# (label template, key, format) quoted per canonical run
RUN_KEYS = [
    ("heat covered", "share_covered", "pct"),
    ("backup heat", "backup_heat_kwh", "kwh"),
    ("heat dumped", "heat_dumped_kwh", "kwh"),
    ("paid deadlines missed", "missed_deadline_pct", "pct100"),
    ("server utilisation", "utilisation", "pct"),
    ("paid server-hours", "paid_run_h", "h"),
    ("ballast server-hours", "ballast_run_h", "h"),
    ("on/off transitions per day", "transitions_per_day", "num"),
    ("cost per server-hour run (case break-even formula)", "break_even_chf_per_server_h", "chf"),
    ("paid price needed to pay off incl. hardware", "pays_off_above_chf_per_server_h", "chf"),
    ("pays off at the paid price", "pays_off", "bool"),
]


def fmt(v, kind: str) -> str:
    if v is None:
        return "n/a"
    if kind == "pct":
        return f"{100 * v:.2f}%"
    if kind == "pct100":
        return f"{v:.2f}%"
    if kind == "kwh":
        return f"{v:,.0f} kWh"
    if kind == "h":
        return f"{v:,.0f} h"
    if kind == "bool":
        return "yes" if v else "no"
    if kind == "chf":
        return f"{v:.4f} CHF/server-h"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def numbers_for_run(run_dir: Path, title: str, assumed: set[str], code_sha: str,
                    house: bool = False) -> list[PitchNumber]:
    b = json.loads((run_dir / "balance.json").read_text())
    out = []
    if house:  # the reference house itself (case data, not a policy outcome)
        out.append(PitchNumber("reference house: annual heat demand (space + hot water)", b["heat_demand_kwh"],
                               "balance.json", "heat_demand_kwh", run_dir.name, b.get("assumptions_hash", ""),
                               code_sha, sorted(p for s in PHYSICS for p in section_assumed(assumed, s))))
    for label, key, _kind in RUN_KEYS:
        if key not in b:
            continue
        inputs = [p for s in depends(b, key) for p in section_assumed(assumed, s)]
        out.append(PitchNumber(f"{title}: {label}", b[key], "balance.json", key, run_dir.name,
                               b.get("assumptions_hash", ""), code_sha, sorted(set(inputs))))
    return out


# Decision card (#31): numbers quoted from decision_card.json; it depends on every input section.
CARD_KEYS = [("decision card: recommended servers per house", "recommended_n", "num"),
             ("decision card: paid price needed to pay off incl. hardware", "pays_off_above_chf_per_server_h", "chf")]


def numbers_for_card(card_path: Path, assumed: set[str], code_sha: str) -> list[PitchNumber]:
    c = json.loads(card_path.read_text())
    inputs = sorted(p for s in (*PHYSICS, "jobs", "ballast", "hardware") for p in section_assumed(assumed, s))
    return [PitchNumber(label, c[key], card_path.name, key, card_path.parent.name, c.get("assumptions_hash", ""),
                        code_sha, inputs) for label, key, _k in CARD_KEYS if key in c]


def kind_of(key: str) -> str:
    if key == "heat_demand_kwh":
        return "kwh"
    return next((k for _l, kk, k in RUN_KEYS + CARD_KEYS if kk == key), "num")


def render_markdown(nums: list[PitchNumber], header: dict) -> str:
    lines = ["# PITCH_NUMBERS (generated by `python -m tools.pitch`, do not edit by hand)", "",
             f"- code sha: `{header['code_sha']}`{' (dirty tree)' if header.get('dirty') else ''}",
             f"- assumptions sha256: `{header['assumptions_hash']}`",
             f"- runs folder: `{header['runs_root']}`",
             f"- ASSUMED inputs in data/assumptions.yaml: {', '.join(f'`{p}`' for p in header['assumed']) or 'none'}",
             "", "Every row: value · where it comes from (run id / file : key) · ASSUMED if any input it depends on is.",
             "", "| # | number | value | source | ASSUMED |", "|---|---|---|---|---|"]
    for i, n in enumerate(nums, 1):
        flag = "**ASSUMED** (" + ", ".join(f"`{p}`" for p in n.assumed_inputs) + ")" if n.assumed else "no"
        lines.append(f"| {i} | {n.label} | {fmt(n.value, kind_of(n.key))} | `{n.run_id}/{n.file}: {n.key}` | {flag} |")
    for note in header.get("notes", []):
        lines += ["", f"> {note}"]
    return "\n".join(lines) + "\n"
