# DigitalHeat pitch deck — DRAFT v1 (design, 2026-11-21)

> 5 min incl. live demo + 3 min Q&A. Every number below comes from `research/PITCH_NUMBERS.md` (row #) or `runs/experiment_tracker.md` (EXP-####). **Never say a number that isn't in those files.** ASSUMED inputs are said as assumptions.
> Rubric: Transparency 25 · Feasibility 25 · Scheduling 20 · Creativity 20 · Design 10.

---

## Slide 1 — Key figures first (0:00–0:40)
**Title:** One machine, two products: heat for the house, compute for customers.
- Reference house, Basel 2025: **31,231 kWh** heat a year (row 1).
- With 4 servers our scheduler covers **57.9 %** of it (row 35), and **misses 0 % of paid deadlines** (row 38).
- The thermostat way covers 58.0 % but **misses 31 %** of the same paid work (rows 2, 5).
- **Honest line:** at today's assumed prices it does **not** pay off yet: paid work must sell for **≥ 0.53 CHF per server-hour** incl. hardware (row 44; capex CHF 8k / 5 y ASSUMED). The thermostat needs **0.74** (row 11).
*Say:* "It's 28 % cheaper to make this work our way, and we'll show you exactly when it doesn't."

## Slide 2 — The core problem (0:40–1:00)
- Heat is seasonal and peaky; compute is flat and has deadlines.
- Chart: load-duration curve (briefing): 12.5 servers are needed for only 29 h a year; summer needs ~0.6 of a server.
*Say:* "Follow the heat and you miss deadlines; follow the work and you dump heat."

## Slide 3 — Our scheduler in one picture (1:00–1:40)
- **Price-based dispatch:** every hour each house posts a cost per kWh, lower when its heat is used; work runs where its price clears it.
- **Patience is a battery:** jobs with spare time wait for cold hours (24 h slack ≈ −7 % dumped heat, 7 d ≈ −17 %; Run B + our replay).
- **Ballast:** cheap flexible work runs only when its heat is used, so winter capacity isn't wasted.
- **Admission:** a job is accepted only if it can finish in time; admitted jobs **never missed a deadline**, even at 2× load (#59).
- **Same code** drives the 8,760-h year and the live machines.

## Slide 4 — LIVE DEMO (1:40–3:40) — `python -m tools.demo`
1. **Dashboard:** the Mac (coordinator + node) and the Omen (node) heating "January" houses.
2. **Pull the plug:** a judge pulls the plug on the Omen mid-job → the Mac resumes from the checkpoint → **byte-identical result, every chunk exactly once** (E2E_TAILNET.md).
3. **July:** we switch the house to July → the job **pauses within ~2–5 s**; back to January → it resumes.
4. **Sovereignty:** a *certified* job runs only on the certified Mac; a tampered node is **refused its key**; the audit log verifies.
*Backup:* recorded video of the same run.

## Slide 5 — Measured, not invented (3:40–4:10)
- **EXP-0001:** Whisper-small on our Mac's GPU: **35× real time, 9.2 W, 0.26 Wh per audio-hour**, 95 % word recall.
- Scaled to the 1 kW reference server at equal efficiency per joule (ASSUMED).
- Robustness: 4 red-team rounds (incl. a live attack on the public coordinator), ~36 findings, **all fixed**; 959 automated tests.

## Slide 6 — Decision card (4:10–4:40)
- **It pays off when:** paid work ≥ 0.53 CHF/server-h at 4 servers, or capex ≈ CHF 5k, or load ≈ 80 % (sensitivity).
- **It does NOT pay off when:** capex CHF 15k / 3 y, or the paid price is at today's assumed 0.50.
- **Lowest required price:** 1 server per house (0.52 CHF/h, row 47), but it covers only ~20 % of the heat: the operator picks N by coverage vs hardware.
- **First pilot measurement:** will customers accept 24 h of slack?

## Slide 7 — Close (4:40–5:00)
"The thermostat steers the valve, not the GPU. We schedule compute by the value of its heat, prove it on real machines, and tell you exactly when it pays."

---

## Q&A prep (facts only)
- **Why not always on?** Same heat (58.0 %) but 9,910 kWh dumped, and it needs 0.69 CHF/h (rows 13–22).
- **Is the attestation real?** No, it's a mock and we say so; certification comes from the operator's registry, never from the node (red team A08).
- **Hot water at 60 °C?** The model is energy-only; a booster is needed for legionella (Run B CL-4).
- **Why trust the numbers?** `python -m tools.pitch` regenerates every number with its run, settings hash and code version.
- **What we did not do:** real thermostat input (simulated from the reference profile), a real hardware TEE, multi-site fleets beyond 2 nodes.

## Open for Dhruv
1. Exact pitch slot (COMPETITION.md TODO).
2. Publish as claude.ai slides? (The publish call needs your OK.) Design system: IGRIS is available.
3. Who speaks which slide.
