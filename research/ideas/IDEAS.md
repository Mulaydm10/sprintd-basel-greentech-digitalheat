# IDEAS — every idea we have had so far (living register)

> Status as of **2026-11-21 02:20 CET**, written by the design session (Omen).
> Nothing here is decided or claimed yet. Building starts only after Dhruv reviews the task list.
> Full evidence for the Run B ideas: `research/playbook-B/FINDINGS.md` (+ `FINDINGS.pdf`), which has a Graveyard with ~90 IDs.
> Background numbers: `research/briefing/DigitalHeat_Technical_Briefing.pdf` and `numbers.json`.
>
> Status tags: **CHOSEN** (current plan) · **CANDIDATE** (open, needs a decision) · **SUPPORT** (lives inside a chosen idea) · **REJECTED** (with why and how it could come back).

---

## 0. The problem in one line

One machine sells two products whose demand doesn't match. Heat is seasonal and peaky: 12.5 servers are needed for only 29 h a year, and summer needs about 0.6 of a server. Compute is flat and deadline-driven.

Key numbers (reference house, Basel 2025):
- Total demand: 31,231 kWh/yr.
- Heat-following coverage vs. servers: 1→20%, 2→33%, 3→46%, 4→58%, 6→80%, 8→93%, 10→99%.
- Utilisation falls as coverage rises: 87% → 44%.
- Break-even under the case formula: heat-following 0.226 CHF/h for any N; always-on 0.24–0.30 CHF/h.
- Hardware cost flips the conclusion: always-on beats heat-following (N=4: 0.446 vs 0.509). Hardware is assumed at **CHF 8k/server over 5 years, ASSUMED**.
- Heat value is only about 32% of the electricity cost.

---

## 1. CHOSEN: the pitch structure (Run B verdict, about 4.2/5 combined)

| # | Idea | Role | Key evidence |
|---|---|---|---|
| 1 | **Pilot decision card**: one card stating when it pays, when it doesn't, and what to measure first | Feasibility-led closer | Run B founders' seat #1 (3.85/5) |
| 2 | **"Patience is a battery — we measured how big"**: job slack acts as heat storage | Core idea | 24 h slack → −7% dumped heat; 7 days → −19.5%; summer dumping is untouched; simple greedy rule = hindsight optimum |
| 3 | **"The transcript catches up"**: a live Whisper job freezes when the house is warm, builds a backlog, then catches up; next, the year is replayed on the real process | Live proof (must-have #2) | Pause 0.66 ms, resume 0.06 ms; exactly-once over 135 interruptions; replay 7,570.0 vs 7,570.0003 run-h, 17/17 pauses |

Requirements carried forward from Run B:
- Use the **tank-band (hysteresis) policy** everywhere. `follow` causes 24 micro-pauses per July day, so no pause is visible.
- Make the exactly-once proof **hash chunk IDs, not Whisper text**, because Whisper output isn't bit-stable on Metal.
- Measure power with `sudo powermetrics`, run by a human. Never use `top`'s POWER column, which shows %CPU, not watts.
- Founder-review warnings to address on stage:
  - Buyer patience is unevidenced; make it the first pilot measurement.
  - The backup heater is the comfort guarantee; always show its share.
  - Hot water needs about 60 °C (Legionella).
  - Don't claim a demo on our own pitch "proves 20 kW".
  - Correct the IWB + Neutral-IT citation.

---

## 2. CANDIDATE: demonstration ideas that blow minds in the room (2026-11-21 chat)

Dhruv's brief: mind-bending **in the demonstration**, not just in the tech.

| ID | Idea | What the room experiences | Build | Risks / fallback |
|---|---|---|---|---|
| D1 ⭐ | **The jury becomes the data centre** | Judges scan a QR code, and their phones join as "houses" running in-browser AI jobs (transformers.js/ONNX, WebGPU/WASM) dispatched by the same `decide()` over WebSocket. Their phone warms in "January" and pauses in "July", while another phone takes over. A *confidential* job is refused by every phone, live ("not a certified site"). | ~4–6 h: web page + WebSocket bridge | Venue Wi-Fi (bring a hotspot), old phones, judges declining to scan → fall back to our own 3–4 phones. **Untested: how warm does a phone actually get in 60 s?** |
| D2 | **Laptop as an audible, touchable heater** | The Omen's fans roar in replayed January and go silent in July; a judge's hand over the vent. On-screen measured watts; state the scale honestly ("1/30th of a server"). | ~0 new code | Must not look like Run B's rejected "warm mug" prop; keep it honest-scale |
| D3 | **A judge pulls the plug** | A judge kills any machine (cable or lid). The job continues from its checkpoint on another machine; the dashboard shows "0 s lost, 0 repeated". | Checkpoint code exists (Run B C2) + ~2 s heartbeat | Re-adds migration, which Run B demoted (crowding 7/10, Qarnot 2021). Frame it as resilience, not novelty |
| D4 | **Tonight's real Basel weather** | Live forecast for Basel this morning: "the house down the street needs 7 kW now; here's what the scheduler is doing." | Small: Open-Meteo forecast API | Low risk; garnish |

**Proposed running order (5 min):**
1. D2 roar, "this is January" (10 s).
2. #3 transcript catches up (60 s).
3. D1 "now you're the fleet" (60 s).
4. #1 decision card, plus the "we're a compute company that heats" reframe.

**Open decision for Dhruv:** quick-check D1 (phone warmth test) first, or add it as a lane right away?

---

## 3. CANDIDATE: earlier team ideas (before the playbooks)

| ID | Idea | Status |
|---|---|---|
| T1 | Laptops as houses; Whisper transcribing our pitch, migrated mid-sentence; sovereignty refusal priced; fleet utilisation as headline | **Demoted** by Run B (S5): crowding 7/10 (Antal et al./Qarnot 2021); utilisation is not what the rubric ranks first. Its pieces survive in #3, D1 and D3 |
| T2 | Access classes `public / swiss-only / certified`; the scheduler never places a job on an ineligible site ("Sovereign AI") | **SUPPORT**: in the contracts; D1 shows it live. Don't claim regulation *requires* it (CL-9) |
| T3 | Summer: move work to year-round heat sites (hotels, spas, pools, greenhouses) | **SUPPORT / appendix**: Run B S4 "follow the cold" demoted (no effect on the reference house) |
| T4 | 3–6 servers per house + backup heater for peaks ("sweet spot") | **SUPPORT**: N is chosen by coverage and hardware, not by break-even (which is constant at 0.226) |
| T5 | Privacy angle: inference offloaded to home basements must not leak data | **SUPPORT**: access classes + certified sites |

---

## 4. REJECTED / DEMOTED ideas worth remembering (top picks from the Run B Graveyard)

Dhruv's rule: "record all because sometimes it rejects good ideas as well". The full list is in `research/playbook-B/FINDINGS.md` § Graveyard. These are the ones most worth reviving:

| ID | Idea | Why dropped | How to revive |
|---|---|---|---|
| S1-MENU | Slack price menu (Express / Day / Week) priced off the heat curve | Tier spread only 2.5–4.5% of break-even | Pricing appendix only |
| S1-SMART | Forecast-aware / smarter scheduler beats greedy | Greedy already equals the hindsight optimum | None needed; it's a *finding* ("simple is optimal") |
| S1-W | 90-day "Winter" slack tier (seasonal reservoir jobs) | No buyer evidence beyond 7 days of slack | If a pilot customer signs a seasonal job |
| S4 | Follow the cold, stay Swiss (fleet across climates) | No reference-house effect; needs alpine partners | Fleet appendix / Q&A |
| G1-13 / G2-11 / G6-11 | Sonified house ("Geiger ticks", "hear the house breathe", rubato) | Design-only garnish, venue noise | 10 s garnish; the rubato line as a spoken metaphor. **D2 is a cousin of this** |
| G1-14 / G3-12 | Warm mug / exhaust handover prop | Laptop air ≠ 50–70 °C water; experts see through it | Only with honest scale (→ D2) |
| G6-05 | Sourdough jar (resume cost grows with pause length) | Gimmick risk | Homeowner-facing metaphor |
| G6-10 | Building mass as extra storage | Changes the fixed case physics | Labelled sensitivity |
| G4-13 / G5-06 | Grid-operator curtail button / Power-Up sessions for IWB | Outside rubric metrics | Q&A answer if IWB is in the room |
| G5-10 / G1-10 | Judges choose slack live / a judge's sentence becomes the job | Merged into #3 | Audience-participation variant (fits D1) |
| CL-1…CL-11 | Pitch lines that are false or unevidenced (e.g. "nobody schedules compute against heat", "Swiss customers will wait", "0.226 is our discovery", CHF 8k as fact) | See the Graveyard | **Never say them**; the honest wording is listed in the Graveyard |

---

## 5. Task candidates (NOT claimed; review with Dhruv first)

1. Tank-band policy + `slack` parameter in `scheduler.decide` and `simulate_year`.
2. Decision card generator (from `balance.json`).
3. Exactly-once processing with per-chunk ID hashes in `live_agent`.
4. Transcriber demo (#3) on the Mac.
5. A second job type + a jobs/day source.
6. `sudo powermetrics` measurement → `EXP-####` row (human-run).
7. Migration made optional (needed only if D3 is chosen).
8. **D1 phone-fleet lane** (web page + WebSocket bridge) if chosen.
9. Label hardware cost ASSUMED (5k/8k/15k × 3/5 y table); fix the IWB citation.

## 6. Playbook run status
- **Run B (DIVERGE):** done → `research/playbook-B/`.
- **Run A (CONVERGE on our analysis):** blocked a third time by the Opus safety false positive (`[reasoning_extraction]`, 2026-11-21 ~02:00 CET). No findings produced. Options: rerun with Sonnet, or skip it.
