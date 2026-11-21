"""python -m tools.demo --coordinator URL --admin-token-file T --observer-token-file O
                     [--step all|migrate|pause|tamper|certified] [--dry-run] [--tamper-node N --tamper-token-file F]
                     [--omen-kill CMD] [--omen-start CMD] [--sitesim-stop CMD] [--sitesim-start CMD]

Run from the Mac (repo root). Tokens are read from files and never printed. Exit 0 only if every step PASSes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import STEPS, Api, Config, Ctx, run_steps


def _token(path: str) -> str:
    tok = Path(path).read_text().strip()
    if not tok or any(ch.isspace() for ch in tok):
        raise SystemExit(f"{path}: expected one token without whitespace")
    return tok


def main(argv: list[str] | None = None) -> int:
    d = Config()
    p = argparse.ArgumentParser(prog="python -m tools.demo")
    p.add_argument("--coordinator", required=True)
    p.add_argument("--admin-token-file", required=True)
    p.add_argument("--observer-token-file", required=True)
    p.add_argument("--step", default="all", choices=("all", *STEPS))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tamper-node", default=d.tamper_node)
    p.add_argument("--tamper-token-file", default=None)
    p.add_argument("--chunks", type=int, default=d.chunks)
    p.add_argument("--rounds", type=int, default=d.rounds)
    p.add_argument("--omen-kill", default=d.cmd_omen_kill)
    p.add_argument("--omen-start", default=d.cmd_omen_start)
    p.add_argument("--sitesim-stop", default=d.cmd_sitesim_stop)
    p.add_argument("--sitesim-start", default=d.cmd_sitesim_start)
    p.add_argument("--sitesim-url", default=d.sitesim_url)
    a = p.parse_args(argv)
    cfg = Config(tamper_node=a.tamper_node, tamper_token_file=a.tamper_token_file, chunks=a.chunks, rounds=a.rounds,
                 cmd_omen_kill=a.omen_kill, cmd_omen_start=a.omen_start, cmd_sitesim_stop=a.sitesim_stop,
                 cmd_sitesim_start=a.sitesim_start, sitesim_url=a.sitesim_url)
    api = Api(a.coordinator, _token(a.admin_token_file), _token(a.observer_token_file))
    steps = list(STEPS) if a.step == "all" else [a.step]
    res = run_steps(Ctx(api, cfg, dry_run=a.dry_run), steps)
    print("SUMMARY " + " ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in res.items()))
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
