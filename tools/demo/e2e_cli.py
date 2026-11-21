"""CLI of tools.demo.e2e (#106): python -m tools.e2e --help. Tokens are read from files and never printed."""
from __future__ import annotations

import argparse
from pathlib import Path

from .e2e import STEPS, E2E, Config


def _token(path: str | None) -> str | None:
    if not path:
        return None
    tok = Path(path).read_text().strip()
    if not tok or any(ch.isspace() for ch in tok):
        raise SystemExit(f"{path}: expected one token without whitespace")
    return tok


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.e2e", description="live end-to-end check of the deployed system")
    p.add_argument("--coordinator", required=True)
    p.add_argument("--site", required=True, help="the website / dashboard base URL")
    p.add_argument("--client-token-file", required=True)
    p.add_argument("--observer-token-file", required=True)
    p.add_argument("--host-token-file", action="append", default=[],
                   help="repeatable: the first is used for the host flow; all are tried for the pause step's site")
    p.add_argument("--client2-token-file", help="a second client, for the foreign-job 404 check")
    p.add_argument("--admin-token-file", help="enables migrate/pause/certified/audit (run from the Mac)")
    p.add_argument("--only", default=",".join(STEPS), help=f"comma list of steps (default all: {','.join(STEPS)})")
    p.add_argument("--certified-nodes", default="node-mac")
    p.add_argument("--timeout", type=float, default=180.0)
    a = p.parse_args(argv)
    steps = [s for s in a.only.split(",") if s]
    unknown = set(steps) - set(STEPS)
    if unknown:
        raise SystemExit(f"unknown steps {sorted(unknown)}; choose from {list(STEPS)}")
    cfg = Config(a.coordinator, a.site, _token(a.client_token_file), _token(a.observer_token_file),
                 host_token=_token(a.host_token_file[0]) if a.host_token_file else None,
                 host_tokens=tuple(_token(f) for f in a.host_token_file), client2_token=_token(a.client2_token_file),
                 admin_token=_token(a.admin_token_file), timeout_s=a.timeout,
                 certified_nodes=tuple(x for x in a.certified_nodes.split(",") if x))
    return 0 if E2E(cfg).run(steps) else 1
