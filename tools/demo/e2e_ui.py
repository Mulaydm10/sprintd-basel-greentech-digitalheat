"""Browser end-to-end of the website's live pages (#117): ``python -m tools.e2e ... --ui``.

Drives the deployed site like a human in headless Chromium (Playwright) and fails on anything a visitor would see:
  ui08  08 Client: sign in -> submit an S job -> admitted -> unit grid progresses over SSE -> done -> download result,
        sha256 matches the receipt -> sign out leaves sessionStorage empty and no token in the URL
  ui09  09 GPU Server: sign in -> site tiles, servers and the 24 h history render with live values; Pause/Resume is only
        clicked with --ui-allow-pause (never on the real demo site by default; resumed in cleanup if interrupted)
  ui10  10 Coordinator: observer token -> overview tiles equal GET /v1/ops/overview; every admin action is disabled
  ui07  07 Year: the 3D map renders (WebGL canvas not blank), Play at 8x advances the clock, the N slider changes the
        sizing card
Every page: no console error, no failed response outside the flow's expected codes, and no request to any origin
other than the site and the coordinator. Screenshots go to --ui-out (default runs/e2e/ui/). Tokens are typed into the
pages' password fields and never printed or saved. Without Playwright every ui step is SKIPped.
"""
from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .e2e import Skip, StepFail

PAGES = {"07": "DigitalHeat%2007%20Year.dc.html", "08": "DigitalHeat%2008%20Client.dc.html",
         "09": "DigitalHeat%2009%20GPU%20Server.dc.html", "10": "DigitalHeat%2010%20Coordinator.dc.html"}
BLANK_PNG_BYTES = 20_000  # a uniform 1000x700 PNG is a few kB; a rendered city is hundreds


def _origin(url: str) -> str:
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


class UI:
    """One headless browser for all ui steps; a fresh context (empty storage) per page."""

    def __init__(self, e2e: Any):
        self.e, self.cfg = e2e, e2e.cfg
        self.out = Path(self.cfg.ui_out)
        self.allowed = {_origin(self.cfg.site), _origin(self.cfg.coordinator)}
        self._pw = self._browser = None

    # ------------------------------------------------------------------ browser plumbing
    def browser(self):
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise Skip("playwright not installed (pip install playwright && playwright install chromium)") from None
            self._pw = sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch(headless=True, channel=self.cfg.ui_channel or None)
            except Exception as e:  # noqa: BLE001 - no browser binary: skip, do not fail the live run
                self._pw.stop(); self._pw = None
                raise Skip(f"no Chromium for Playwright ({type(e).__name__}); run `playwright install chromium` "
                           "or pass --ui-channel chrome") from None
        return self._browser

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001 - best effort
            pass
        self._browser = self._pw = None

    def open(self, num: str, expect_http: set[int] = frozenset()):
        ctx = self.browser().new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(30_000)
        probs: list[str] = []
        page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource")
                and probs.append(f"console: {m.text[:160]}"))
        page.on("pageerror", lambda e: probs.append(f"page error: {str(e)[:160]}"))

        def req(r):
            o = _origin(r.url)
            if not r.url.startswith(("data:", "blob:")) and o not in self.allowed:
                probs.append(f"external request: {o}")
        page.on("request", req)
        page.on("response", lambda r: r.status >= 400 and r.status not in expect_http
                and probs.append(f"HTTP {r.status} {urlsplit(r.url).path}"))
        page.goto(self.cfg.site.rstrip("/") + "/" + PAGES[num], wait_until="load")
        return ctx, page, probs

    def shot(self, page, name: str) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(self.out / f"{name}.png"), full_page=True)

    @staticmethod
    def finish(ctx, probs: list[str], what: str) -> str:
        ctx.close()
        if probs:
            raise StepFail(f"{what}, but: " + "; ".join(dict.fromkeys(probs))[:600])
        return what

    def sign_in(self, page, token: str | None, role: str) -> None:
        if not token:
            raise Skip(f"no {role} token (--{role}-token-file)")
        page.wait_for_selector("form[data-dh-signin] input[name=token]")
        page.fill("form[data-dh-signin] input[name=url]", self.cfg.coordinator)
        page.fill("form[data-dh-signin] input[name=token]", token)
        page.click("form[data-dh-signin] button[type=submit]")
        try:
            page.wait_for_selector("[data-dh-signout]", timeout=20_000)
        except Exception:  # noqa: BLE001
            msg = page.inner_text("[data-dh-msg]") if page.query_selector("[data-dh-msg]") else "no message"
            raise StepFail(f"sign-in as {role} failed: {msg[:200]}") from None

    @staticmethod
    def signed_out_clean(page) -> dict:
        page.click("[data-dh-signout]")
        page.wait_for_selector("form[data-dh-signin]")
        st = page.evaluate("() => ({ ss: Object.keys(sessionStorage), ls: Object.keys(localStorage), url: location.href })")
        if st["ss"] or st["ls"] or re.search(r"[?&#](token|access_token)=", st["url"]):
            raise StepFail(f"sign-out left state behind: {json.dumps(st)[:200]}")
        return st

    # ------------------------------------------------------------------ pages
    def page08(self) -> str:
        ctx, page, probs = self.open("08")
        self.sign_in(page, self.cfg.client_token, "client")
        page.wait_for_selector("[data-dh-submit] button >> text=/^S · /")
        self.shot(page, "08_signed_in")
        page.click("[data-dh-submit] button >> text=/^S · /")
        page.click("[data-dh-submit-btn]")
        page.wait_for_selector("[data-dh-admission]:has-text('admitted')")
        adm = page.inner_text("[data-dh-admission]")
        m = re.search(r"job-[0-9a-f]+", adm)
        if not m:
            raise StepFail(f"admission line has no job id: {adm[:160]}")
        jid = m.group(0)
        self.e._jobs.append(jid)  # cancelled in cleanup if the run stops early
        seen, t0 = set(), time.monotonic()
        while True:  # the unit grid must move (counts like 7/20) and the job must finish, all via SSE/poll
            txt = page.inner_text("[data-dh-detail]")
            seen |= {int(x) for x in re.findall(r"\b(\d+)/\d+\b", txt)}
            if re.search(r"\bdone\b", txt.split("\n")[1] if "\n" in txt else txt):
                break
            if time.monotonic() - t0 > self.cfg.timeout_s:
                raise StepFail(f"{jid} not done in {self.cfg.timeout_s:.0f} s (unit counts seen {sorted(seen)[:8]})")
            time.sleep(1.0)
        if not any(0 < s for s in seen):
            probs.append("unit grid never showed progress before done")
        self.shot(page, "08_done")
        page.wait_for_selector("[data-dh-receipt] >> text=/result sha256/i", timeout=20_000)
        page.click("text=Download result")
        page.wait_for_selector("[data-dh-receipt] >> text=/sha256 (matches the receipt|MISMATCH)|✗/i", timeout=30_000)
        label = page.inner_text("[data-dh-receipt]").split("\n")[1]
        if "matches the receipt" not in label.lower():
            raise StepFail(f"{jid}: result check says {label!r}")
        self.shot(page, "08_result_verified")
        self.signed_out_clean(page)
        return self.finish(ctx, probs, f"{jid}: admitted, grid moved {sorted(seen)[:3]}…, done, sha256 matches the "
                                       "receipt, sign-out clean")

    def page09(self) -> str:
        ctx, page, probs = self.open("09")
        self.sign_in(page, self.cfg.host_token, "host")
        page.wait_for_selector("[data-dh-node]")
        t0 = time.monotonic()
        while "LIVE" not in page.inner_text("[data-dh-src]") and time.monotonic() - t0 < 15:
            time.sleep(0.5)
        tiles = page.inner_text("section")
        demand = re.search(r"heat demand now kW\s*\n\s*([\d.–-]+)", tiles, re.I)
        if not demand or demand.group(1) in ("–", "-"):
            probs.append("heat demand tile has no live value")
        nodes = page.eval_on_selector_all("[data-dh-node]", "els => els.map(e => e.innerText.split('\\n')[0])")
        if not page.query_selector("canvas[data-dh-history]"):
            probs.append("no history canvas")
        msg = f"site {demand.group(1) if demand else '?'} kW demand, servers {nodes}"
        self.shot(page, "09_signed_in")
        if self.cfg.ui_allow_pause:
            self.e._paused_hosts.append(self.e.host)  # resumed in cleanup if anything below fails
            page.click("[data-dh-override] button >> text=Pause 2 h")
            page.wait_for_selector("[data-dh-override] >> text=/^Paused/")
            self.shot(page, "09_paused")
            page.click("[data-dh-override] button >> text=Resume now")
            page.wait_for_selector("[data-dh-override] >> text=/too warm/")
            self.e._paused_hosts.remove(self.e.host)
            msg += ", pause 2 h -> resume via the page"
        else:
            msg += ", pause not clicked (pass --ui-allow-pause)"
        self.signed_out_clean(page)
        return self.finish(ctx, probs, msg)

    def page10(self) -> str:
        ctx, page, probs = self.open("10", expect_http={403})  # the side-effect-free role probe answers 403 to observers
        self.sign_in(page, self.cfg.observer_token, "observer")
        page.wait_for_selector("text=/OBSERVER/")
        page.wait_for_selector("[data-dh-node]")
        ok, last = False, ""
        for _ in range(5):  # live numbers move: compare a fresh pair until they agree
            ov = self.e.obs.get("/v1/ops/overview").json()
            want = {"nodes online / suspect / off": f"{ov['nodes']['online']} / {ov['nodes']['suspect']} / {ov['nodes']['offline']}",
                    "leases active": str(ov["leases_active"])}
            txt = page.inner_text("section")
            got = {k: (re.search(re.escape(k) + r"\s*\n\s*([^\n]+)", txt, re.I) or [None, None])[1] for k in want}
            last = json.dumps({"page": got, "api": want})
            if all((got[k] or "").strip() == v for k, v in want.items()):
                ok = True
                break
            time.sleep(2.0)
        if not ok:
            probs.append(f"tiles differ from /v1/ops/overview: {last[:300]}")
        enabled = page.eval_on_selector_all("[data-dh-node] button", "bs => bs.filter(b => !b.disabled).map(b => b.innerText)")
        if enabled:
            probs.append(f"admin actions enabled for an observer: {enabled[:5]}")
        n = len(page.query_selector_all("[data-dh-node] button"))
        self.shot(page, "10_observer")
        self.signed_out_clean(page)
        return self.finish(ctx, probs, f"observer: tiles match /v1/ops/overview, {n} admin buttons all disabled")

    def page07(self) -> str:
        ctx, page, probs = self.open("07")
        page.wait_for_selector("[data-dh-controls] input[type=range]")
        page.wait_for_selector("#dh-basel-host canvas", timeout=45_000)
        time.sleep(3.0)  # let the city stream in and a few frames render
        png = page.locator("#dh-basel-host canvas").first.screenshot()
        blank = len(png) < BLANK_PNG_BYTES
        try:  # stronger check when Pillow is there: pixel spread of the frame
            from PIL import Image, ImageStat
            blank = max(ImageStat.Stat(Image.open(io.BytesIO(png)).convert("L")).stddev) < 4.0
        except ImportError:
            pass
        if blank:
            probs.append(f"3D map canvas looks blank ({len(png)} B png)")
        self.shot(page, "07_map")
        scrub = page.locator("[data-dh-controls] input[type=range]").first
        h0 = int(scrub.get_attribute("value") or 0)
        page.click("[data-dh-controls] button >> text=8x")
        page.click("[data-dh-controls] button >> text=/Play/")
        time.sleep(3.0)
        h1 = int(scrub.get_attribute("value") or 0)
        page.click("[data-dh-controls] button >> text=/Pause/")
        if h1 <= h0:
            probs.append(f"play at 8x did not advance the clock (hour {h0} -> {h1})")
        n_el = page.locator("[data-dh-controls] input[type=range]").nth(1)
        n0 = int(n_el.get_attribute("value") or 4)
        n1 = 8 if n0 != 8 else 1
        n_el.evaluate("(el, v) => { const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
                      " s.call(el, String(v)); el.dispatchEvent(new Event('input', { bubbles: true })); }", n1)
        try:  # the sizing card's comparison rows follow the slider ("at N = n1"); the recommended N stays as is
            page.wait_for_selector(f"text=/at N = {n1}\b/", timeout=30_000)
        except Exception:  # noqa: BLE001
            probs.append(f"moving the N slider to {n1} did not update the sizing card")
        self.shot(page, "07_after_play_and_n")
        return self.finish(ctx, probs, f"map rendered ({len(png) // 1000} kB frame), 8x play hour {h0} -> {h1}, "
                                       f"N {n0} -> {n1} updates the sizing card")
