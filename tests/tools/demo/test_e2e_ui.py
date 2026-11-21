"""#117 wiring of the browser steps (no browser here): --ui adds them, unknown steps fail, missing Playwright SKIPs,
and the UI module keeps its safety rules (allowed origins, pause only when allowed, tokens never printed)."""
from __future__ import annotations

import builtins
import re
from pathlib import Path

import pytest

import tools.demo.e2e_cli as cli
from tools.demo import e2e_ui
from tools.demo.e2e import STEPS, UI_STEPS, E2E, Config, Skip

SRC = Path(e2e_ui.__file__).read_text(encoding="utf-8")


def _cfg(**kw):
    return Config("http://coord.test:8710", "https://site.test:8443", "c" * 32, "o" * 32, host_token="h" * 32, **kw)


def test_ui_steps_are_opt_in(monkeypatch, tmp_path):
    seen = {}

    class Fake:
        def __init__(self, cfg): seen["cfg"] = cfg
        def run(self, steps): seen["steps"] = steps; return True
    monkeypatch.setattr(cli, "E2E", Fake)
    for n in ("c", "o"):
        (tmp_path / n).write_text(n * 32)
    base = ["--coordinator", "http://x", "--site", "http://y", "--client-token-file", str(tmp_path / "c"),
            "--observer-token-file", str(tmp_path / "o")]
    assert cli.main(base) == 0 and not set(seen["steps"]) & set(UI_STEPS)
    assert cli.main(base + ["--ui", "--ui-allow-pause", "--ui-channel", "chrome", "--ui-out", "out"]) == 0
    assert seen["steps"] == list(STEPS) + list(UI_STEPS)
    assert (seen["cfg"].ui_allow_pause, seen["cfg"].ui_channel, seen["cfg"].ui_out) == (True, "chrome", "out")
    assert cli.main(base + ["--only", "ui08"]) == 0 and seen["steps"] == ["ui08"]
    with pytest.raises(SystemExit):
        cli.main(base + ["--only", "ui99"])


def test_missing_playwright_skips_every_ui_step(monkeypatch):
    real = builtins.__import__

    def no_pw(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError(name)
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_pw)
    out = []
    e = E2E(_cfg(), out=out.append)
    assert e.run(list(UI_STEPS)) is True  # SKIP is not a failure
    assert [r[1] for r in e.results] == ["SKIP"] * 4 and "playwright not installed" in e.results[0][2]


def test_only_the_site_and_coordinator_origins_are_allowed():
    ui = e2e_ui.UI(E2E(_cfg()))
    assert ui.allowed == {"http://coord.test:8710", "https://site.test:8443"}
    assert "external request" in SRC and '"data:", "blob:"' in SRC


def test_pause_is_only_clicked_when_allowed_and_resumed_in_cleanup():
    body = re.search(r"def page09\(self\).*?def page10", SRC, re.S).group(0)
    assert "if self.cfg.ui_allow_pause:" in body
    assert body.index("_paused_hosts.append") < body.index("Pause 2 h")  # registered for cleanup before clicking
    assert "_paused_hosts.remove" in body


def test_tokens_are_never_printed_or_saved():
    assert "print(" not in SRC
    for line in SRC.splitlines():
        if "token" in line and ("self.out(" in line or "probs.append" in line or "StepFail(" in line):
            assert not re.search(r"\{[^}]*token[^}]*\}", line), line  # never interpolate a token into a message


def test_job_from_the_ui_is_cancelled_in_cleanup_if_unfinished():
    assert "self.e._jobs.append(jid)" in SRC
