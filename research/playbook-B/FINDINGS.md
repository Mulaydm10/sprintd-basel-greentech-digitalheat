# Playbook run B — DIVERGE then CONVERGE: strongest "wow" idea + pitch angle (DigitalHeat case)

Central document of run B. Written continuously; every stage is appended with a CET timestamp. Worker reports live in
`workers/`, charts in `figures/`, scripts in `scripts/`, shared model in `lib/refhouse.py`. Nothing in the team repo was modified.

**Status line (final, 2026-11-21 00:32 CET):** ALL STAGES COMPLETE — DIVERGE (90 ideas) → CONVERGE (3 survivors) → board (no CRITICAL; 5 HIGH fixed or handed over) → gate STOP → VERDICT at the end of the Final section. Survivors, presented as one pitch: #1 Pilot decision card · #2 Patience is a battery, measured · #3 The transcript catches up + the year on a real process.

---

## Stage 0 — Intake, contest profile, triage, commitment  *(2026-11-20 22:47 CET)*

### 0.1 Intake (the brief is the intake; no questions asked — inferred answers recorded)
| Intake item | Answer (source) |
|---|---|
| Problem statement | DigitalHeat "Useful Load => Useful Heat": one machine sells heat (seasonal, peaky) and compute (flat, deadline-driven). Case verbs: slow down · pause and resume · distribute to another *eligible* site respecting access and deadlines. Deck title "Server heat and Sovereign AI". (brief; repo COMPETITION.md; briefing §1–2) |
| Supplied materials | Reference house (Open-Meteo Basel 2025, demand formula, 35 kWh lossless tank, 1 kW→0.8 kW server, 0.3325 CHF/kWh, heat = price/2.5). (COMPETITION.md, data/assumptions.yaml) |
| Deliverable | 5-min pitch incl. live demo + 3-min Q&A; submission on the sprintd platform; a real process driven by the scheduler (simulation/slides alone invalid). |
| Judges | DigitalHeat founders (Virtual Culture GmbH, Basel), judging their own case; experts in the economics and in prior art. Inferred reflexive probes: "could we pilot on this?", "where does it break?", "is this just Qarnot/Heata/the IWB Basel pilot again?" *[the partner name "Neutral-IT" from the team briefing is UNVERIFIED — Stage 4 T5]*, flow temperature, data trust. |
| Rubric | Verbatim below (0.3). |
| Field | ~200 builders, teams ≤4, two case partners (briefing §1). Number of DigitalHeat teams unknown — ASSUMED ~10–25. The crowded centre (inferred): heat-following greedy + SIGSTOP/SIGCONT + N-sweep chart + dashboard; many will also do migration + access classes because the case slide names them. |
| User's position | Repo scaffolded, packages are stubs; technical briefing done (`numbers.json` reproduced here exactly). Bottleneck: shipping a credible, defensible demo + numbers. |
| Current candidate to beat | Laptops as "houses"; real Whisper transcription of our own pitch checkpointed and migrated mid-sentence on the heat signal; access-class refusal priced on the dashboard; fleet-level utilisation. **Recorded here as the baseline; deliberately NOT shown to generators** (anti-anchoring). |
| Ambition | Win the case (be DigitalHeat's finalist) → select by the verbatim rubric; memorable *and* credible. |
| Off the table | District heating grid; special hardware; spreadsheet/slide/simulation-only answers; network downloads on stage. |
| Clock | Not asked and not used for scoping (playbook rule). Event dates exist in the repo; they did not prune anything here. |

### 0.2 Contest profile (four questions)
1. **What a judge physically receives:** a 5-minute live pitch with demo, then 3 minutes of Q&A; afterwards possibly the repo/submission (transparency is 25%, so the repo is read).
2. **Who judges against what:** domain-expert founders of the case company, against a weighted rubric where 70% is transparency + feasibility + scheduling-on-the-reference-house, 20% creativity, 10% one-minute clarity.
3. **What separates the top few here:** a result DigitalHeat could take into a pilot decision, with traceable numbers and honest limits — *plus* one practical idea they have not already seen. A wow that does not strengthen a scored must-have is decoration.
4. **The human's bottleneck:** shipping. So every idea is reported with what must be built and a fallback; build difficulty is a *note*, never a filter (playbook rule 2c).

**Mix:** idea + demo + numbers. This run serves the *idea and pitch-angle selection and its defensibility*; building the demo and delivering the pitch are handed back.

### 0.3 Rubric — committed VERBATIM before generating (selection is against this, never against novelty)
- **Transparency & reproducibility 25%** — measurements and calculations can be traced and repeated; every assumption visible.
- **Feasibility 25%** — could DigitalHeat use this as a basis for a pilot decision? knows where its assumptions stop holding; says when the model does not pay off.
- **Scheduling quality & impact 20%** — on the reference house: first share of heat demand covered at least heat dumped, then utilisation and missed deadlines.
- **Creativity & innovation 20%** — fresh, practical idea for matching computing to heat.
- **Design & usability 10%** — homeowner or utility understands the result in one minute.
- **Must-haves (gate, not scored):** ≥2 job types (≥1 measured on own machine, scaled to 1 kW); one scheduler driving both the 8,760-h simulation and a real paused/resumed process; yearly balance incl. break-even CHF/server-h = (elec cost − value of heat used)/server-h sold; "does not pay off" stated.

**Selection order:** rubric fit → impact evidence → crowding. Never novelty first.

### 0.4 Triage — should this run at all?
*Could a competent single expert plausibly miss this in one careful pass?* **Yes.** Why it is subtle:
(a) the current candidate was produced in one pass and the strongest risk is anchoring on it;
(b) the case slide literally lists "distribute to another eligible site", so the candidate's centrepiece is likely the *crowded centre* of this field — a single pass would not test that;
(c) there is a structural trap in the rubric: Scheduling quality is scored **on the reference house**, where fleet migration does not change coverage or dump at all — a wow can impress and still score nothing on the 20% it seems to target;
(d) the case-formula break-even is a constant (0.2261 CHF/server-h at zero dump, for every N): scheduling cannot beat it, only lose it — ideas that "improve break-even" must be checked against this;
(e) the judges know the prior art first-hand (an IWB Basel pilot heated a building with servers in 2020; the team briefing names the partner "Neutral-IT", which this run could NOT verify — Stage 4 T5), so crowding is judged by experts.
**Mode: DIVERGE then CONVERGE** (explicitly requested; never blended in one pass).

### 0.5 Constraints (TESTED = checked in this run; ASSUMED = not checked)
| Constraint | Status | Evidence |
|---|---|---|
| Reference model reproduces the team briefing | **TESTED** | `lib/refhouse.py` vs `brief/numbers_briefing.json`: max relative deviation 0.0 over N=1..13 × 2 policies; 31,230 kWh, 206 heating days, −5.6 °C |
| Weather data available offline | **TESTED** | `data/basel_2025_hourly.json`, 8,760 rows, Open-Meteo archive, Europe/Zurich |
| Mac mini M4 16 GB, 10 cores | **TESTED** | `system_profiler` |
| Power telemetry on Mac mini without sudo | **TESTED: not available** | `powermetrics must be invoked as the superuser`; no battery (`Amperage = 0`) |
| powermetrics with sudo (human-run) | ASSUMED | — |
| Omen laptop (Linux, NVIDIA) on stage; RAPL readable | ASSUMED | RAPL `energy_uj` is root-only on recent kernels — must be tested before it prunes anything |
| Teammates' laptops; remote PCs abroad over VPN | ASSUMED | — |
| Whisper / sentence-transformers runnable offline | ASSUMED | not installed in this run (no heavy installs) |
| Venue network for multi-machine demo | ASSUMED | phone hotspot / wired switch fallback |
| No special hardware; no on-stage downloads | given | brief |

No ASSUMED constraint is allowed to prune a branch; any that would must first be tested (Stage 5).

### 0.6 Config note (recording → acting)
Prior pilots: DIVERGE beats single-pass on originality (3.2–3.8 vs 2.7–3.0) but **loses on usefulness (2.8 vs 3.4)**. Here 70% of the score is usefulness-like (transparency, feasibility, reference-house scheduling) and 20% is creativity. **Decision:** run the full six-altitude DIVERGE (it is the only arm that escapes the crowded centre the slide pushes everyone into), but (1) every idea carries a rubric tag at generation (rationale, not a filter), (2) selection is rubric-first, and (3) a hard CONVERGE pass with real computation and prototyping follows. The current candidate is scored on the same sheet as every new idea.

### 0.7 Diversity target and frame composition (chosen for this task)
Target: **≥ 8 genuinely different directions** surviving cross-pollination, covering both *(A) approaches to matching compute to heat* and *(B) live-demo moments*. Six blind Sonnet generators, one altitude each (composition earned in pilots 03→05; distant-analogy is the highest-yield frame on record; the free generator is never dropped):

| Gen | Frame (altitude) | Hard constraint given | Why for this task |
|---|---|---|---|
| G1 | **Free** | none | preserves the moves constraints suppress |
| G2 | **In-solution mechanism** | must change *when / how much* heat a unit of work makes, or *how* work moves in time/space; may compute with `refhouse.py` to discover, never to discard | the case's three verbs are mechanisms; throttling, tank, checkpoint shape, forecasting live here |
| G3 | **Question the goal** | each idea names the brief assumption it rejects, yet still delivers the must-haves | the brief's framing (house = unit, heat = product, deadlines fixed, 1 kW on/off) may be the wrong optimisation target |
| G4 | **Narrow scope / extreme user** | design for exactly one extreme user or one extreme hour of the year | the coldest 29 h, a July day, a hospital with swiss-only data, the founder deciding on a pilot |
| G5 | **Behavioural / informational** | no change to hardware or scheduling algorithm — only who knows, chooses or pays for what | Design 10% + transparency 25% + demo theatre live here |
| G6 | **Distant analogy** | every idea imports a real mechanism from a domain outside computing and heat reuse, with a fetched source; search ingredients, never answers | highest-yield frame on record |

All generators get only `brief/FACTSHEET.md` (facts, no solution ideas), are told not to read the team repo or each other's files, emit a structured rationale (why / what was discarded and why), and close with "Searches run / sources fetched / tools used".

### 0.8 Pre-registered CONVERGE failure-mode map (refined in Stage 5)
| Live risk | Owner (angle) |
|---|---|
| Idea does not move the reference-house metrics (coverage at least dump → utilisation → missed deadlines) | C1 quantitative grounding |
| Fleet/portfolio numbers presented as reference-house numbers (overclaim) | C1 + board correctness |
| Idea adds unsourced numbers (compute prices, sovereignty value, summer-sink capacity) → hurts transparency 25% | C1 + board reproducibility |
| Demo fragility: network, timing, checkpoint correctness, reset time, model download | C2 demo-mechanism prototype |
| Energy measurement impossible without sudo on the Mac mini | C2 |
| Crowding: the slide's own verbs are what every team builds | prior-art adversary |
| Founder skepticism: prior art, flow temperature, business model, pilot-readiness | C3 founder red-team |
| Judge cannot see the point in 60 s | C3 + board goal-fit |
| Concurrent novelty (other teams this weekend) | unmeasurable — stated, never claimed away |

![Context: load-duration and seasonal mismatch](figures/fig0_context.png)

---

## Stage 1 — DIVERGE generation  *(launched 2026-11-20 22:50 CET)*
Six blind Sonnet generators launched in parallel (G1 free · G2 in-solution mechanism · G3 question-the-goal · G4 narrow-scope/extreme ·
G5 behavioural/informational · G6 distant analogy). Each writes `workers/gen-G<n>-<frame>.md`. Results are appended below as they arrive.

### G1 — FREE  *(returned 22:52 CET; report `workers/gen-G1-free.md`)*
**15 ideas** (8 approach, 6 demo, 1 both). **Evidence quality: thin** — 1 page fetched (Wikipedia, thermal energy storage), 1 search (CRIU, snippets only), no computation; ungrounded claims are honestly labelled "unsourced intuition".

| ID | Name | Kind | Rubric | One-line (worker's words) |
|---|---|---|---|---|
| G1-01 | Heat order book | A | Scheduling | Heat demand is published as a bid curve; jobs "clear" against it |
| G1-02 | Slack-for-discount tier | A | Feasibility | Compute buyers sell deadline slack; price falls with slack hours |
| G1-03 | Escalation ladder | A | Scheduling | slow down → pause → distribute, picked by size of heat shortfall |
| G1-04 | Burst-and-soak | A | Creativity | Full-clock bursts fill the tank, idle between, instead of throttling |
| G1-05 | Forecast pre-charge | A | Scheduling | Use the forecast to run ahead of cold snaps and fill the tank |
| G1-06 | Follow-the-cold (inside CH) | A | Creativity | Summer jobs migrate to eligible Swiss sites that still need heat (altitude) |
| G1-07 | Summer = shower-synced batch | A | Scheduling | In July, jobs run only on hot-water draw windows, long-deadline jobs only |
| G1-08 | Heat-provenance label | A | Transparency | Each finished job carries a signed "kWh of heat reused" record |
| G1-09 | The "does not pay" map | both | Feasibility | N servers vs compute price map with a loud red region |
| G1-10 | Speak-a-sentence Whisper | B | Creativity/Design | Judge speaks; transcript arrives only when the house wants heat |
| G1-11 | Open the window | B | Scheduling | Judge toggles demand; real process freezes and resumes at the same step |
| G1-12 | Year in 3 seconds, then real | B | Transparency | Same scheduler function drives the 8,760-h replay then the live process; call stack shown |
| G1-13 | Geiger-tick house | B | Design | Work rate sonified; January is a roar, July a few ticks |
| G1-14 | Warm mug | B | Feasibility | Cup on the laptop exhaust + honest "this is 0.1 kW, you need 100" |
| G1-15 | Break-it-yourself | B | Transparency/Feasibility | Judge picks any day/parameter; numbers change live; red "not paying" state |

**Worker's top 3:** (1) G1-10 + G1-11 — the judge's own spoken sentence becomes the real Whisper job; an "open the window" toggle freezes it and it resumes at the same step; on a July hour it waits for the hot-water window ("single most memorable and credible moment"). (2) G1-12 — same function visibly drives the 8,760-h replay and the live process. (3) G1-09 — the "does not pay" map (Feasibility 25%).
**Orchestrator flags for CONVERGE (not verdicts):** G1-05 — with a *lossless* tank, greedy heat-following already fills the tank whenever capacity is free, so look-ahead may add no coverage; test in C1. G1-01 — worker itself notes it may be relabelled heat-following. G1-14 — honest-scale prop; founders will note air vs 50–70 °C liquid.
**Worker discards (10)** → Graveyard W-G1.

### G3 — QUESTION THE GOAL  *(returned 22:53 CET; report `workers/gen-G3-goal.md`)*
**15 ideas** (8 approach, 5 demo, 2 both). **Evidence quality: moderate** — computed with a copy of `refhouse.py` (`workers/scratch-g3/a.py`); 1 source opened (Kuster et al., *Field performance of domestic heat pumps … Switzerland*, IRACC, docs.lib.purdue.edu/iracc/2084: Swiss field SPF ≈ 3.6 for air/water with floor heating + hot water — abstract page only); 1 fetch failed (403, core.ac.uk).
**Computed facts the worker surfaced [calc]:** at N=4, **79% of heat-following server-hours fall in Nov–Mar, 8% in Jun–Aug** (Jan 3,720 vs Jul 581 server-h); capex-loaded break-even 0.436 / 0.509 / 0.579 CHF/server-h for N = 1 / 4 / 8 (team capex assumption) while the case formula is 0.2261 for every N; break-even at COP 3.6 instead of 2.5 = 0.2586; tank = 43.75 server-hours of heat.

| ID | Name | Kind | Assumption rejected | Rubric | One-line (worker's words) |
|---|---|---|---|---|---|
| G3-01 | The N-blind dial | both | "Choose N to optimise cost" | Transparency | Break-even is 0.2261 for every N; show it, optimise what varies (coverage vs utilisation vs capex) |
| G3-02 | Compute is the product, heat a 32% rebate | A | "Heat is the product" | Feasibility | A compute seller earning a heat rebate; state the sell-price floor and who pays it |
| G3-03 | Backlog is the battery | A | "The tank stores heat" | Scheduling | A queue of checkpointed jobs is a 100–1000× bigger thermal store than the 44 server-h tank |
| G3-04 | Seasonal compute SKU | A | "Compute demand is flat" | Creativity | Sell "winter compute": 79% of N=4 server-hours are Nov–Mar; price and contract it that way |
| G3-05 | Deadline slack as currency | A | "Deadlines are fixed" | Scheduling | Buyer picks the deadline; quote falls with slack; slack becomes heat coverage |
| G3-06 | Jobs bid, house posts a heat price | A | "The scheduler decides when to run" | Creativity | House publishes hourly heat value; jobs self-select |
| G3-07 | Conservative-by-construction heat value | A | "Heat is worth price/2.5" | Feasibility | Run at COP 2.5 (case) and 3.6 (Swiss field SPF); show whether the pilot decision flips |
| G3-08 | Portfolio of houses, not the house | A | "The house is the unit" | Feasibility | Fix the jobs, choose which heat profiles host them; reference house is one row |
| G3-09 | Open on the "no" (July refusal) | B | "A demo shows the system working" | Feasibility | Scheduler refuses a July job live and prints the CHF loss |
| G3-10 | Hash receipt for the paused job | B | "Pause/resume is a visual trick" | Transparency | Interrupted and uninterrupted runs give the identical SHA-256 |
| G3-11 | The judges hold N | B | "Audience watches a fixed config" | Design | Judge drags N; coverage/utilisation move, 0.2261 never does |
| G3-12 | Warm exhaust handover | B | "The demo lives on a screen" | Design | Hand over the vent when the scheduler says "heat needed" |
| G3-13 | One bar: tank and queue | both | "Tank and queue are different things" | Design | One bar, stored heat vs deferred compute, across a January day |
| G3-14 | Break-even as a sellable receipt | B | "Cost is an appendix table" | Design | Itemised receipt of one server-hour handed to the founders |
| G3-15 | Joule-hungry jobs | A | "Less energy per job is better" | Creativity | In heat-led operation, metric = CHF per useful kWh |

**Worker's top 3:** (1) G3-01 — the N-blind identity is "the most surprising property of the case's own formula". (2) G3-10 — hash receipt makes "no repeated work" falsifiable in seconds. (3) G3-09 — the machine itself says "does not pay off" live.
**Orchestrator flags (not verdicts):** G3-01/G3-11 restate the judges' own formula — the value is the *consequence* (N must be chosen by coverage promise and capex, not by the case break-even); C1 should check how a founder hears it. G3-03 "backlog is the battery" is a candidate *core reframe* (deferred compute as storage, in server-hours); its size depends entirely on buyers' real slack — needs an impact source. G3-04 seasonal SKU depends on demand evidence for winter-only compute → impact validator.
**Worker discards (9)** → Graveyard W-G3.

### G4 — NARROW SCOPE / EXTREME USER  *(returned 22:55 CET; report `workers/gen-G4-extreme.md`)*
**15 ideas** (7 approach, 4 demo, 4 both — the worker's own count; see its table for per-idea kinds). **Evidence quality: good on data, moderate on sources** — located extremes in the hourly data (`workers/scratch-g4/x.py`, `y.py`); 2 pages fetched: FDPIC/EDÖB (edoeb.admin.ch/en/patient-data-disclosure: for patient data "the use of a cloud provider abroad should be avoided in all cases"; IT providers are bound as assistants under Art. 321 SCC) and Swissgrid blog 2025-08-19 ("in eight of the last ten winters, domestic production did not cover electricity needs"). A CHF 2,000/MWh cold-snap figure seen only in a search summary was **not used** (good discipline).
**Data facts the worker surfaced [calc]:** coldest 29-h window starts **2025-11-22 05:00** (mean −3.3 °C, 278.9 kWh, 9.6 kW mean): heat-following covers 8.3% (N=1), 33.3% (N=4), ~67% (N=8), 100% (N=13). Peak hour 10.5 kW at 2025-12-31 23:00. **"Cliff days"**: the day-mean gate switches space heat off abruptly — e.g. 2025-10-04 → 114.1 kWh then 12.0 kWh/day; **26 heating on/off flips** in the year. 3,818 h/yr with demand ≤ 0.5 kW. July: 12 kWh/day = 15 server-h of heat. *(Orchestrator correction: G4 says there is "no morning/evening peak" — accurate only in the sense that the case model has no occupancy peak; hourly demand does follow hourly outdoor temperature, coldest before dawn.)*

| ID | Name | Kind | Extreme | Rubric | One-line (worker's words) |
|---|---|---|---|---|---|
| G4-01 | The 29-hour siege | A+B | Coldest 29 h, 22 Nov 05:00 | Feasibility | Show honestly that 4 servers cover 33% here; define the "give-up ladder"; pre-charge the tank |
| G4-02 | Cliff-day pre-dump | A | 2025-10-04: 114 → 12 kWh/day | Scheduling | Forecast-aware "last chance" run: don't charge a tank the next day cannot use |
| G4-03 | Hot-water-only July | A+B | July, 15 server-h/day | Scheduling/Design | Batch the day's 15 server-h into a tank-timed block; "tank days left" gauge |
| G4-04 | The Hospital Wing | A | Patient data, Art. 321 SCC | Creativity | Eligibility as a hard constraint; job refuses the VPN node abroad, reason printed |
| G4-05 | Founder's verdict card | B | Founder deciding a pilot | Feasibility/Design | One card: "pilot if …, not worth it if …", three assumptions a pilot would measure first |
| G4-06 | Uninterruptible job vs the tank | A | A job that cannot pause | Scheduling | Choose the *start time* so tank + forecast absorb a 14-h job's heat |
| G4-07 | Kill -STOP on a January day | B | 2025-01-10 cold front | Transparency | Day compressed to ~40 s; tank bar; process RUN/STOP flips row by row from the same scheduler |
| G4-08 | Off-switch ledger | A+B | Owner who distrusts the box | Design | Daily receipt + a big OFF the scheduler must obey; backup cost ticks |
| G4-09 | Shower-event prior | A | Irregular hot-water family | Scheduling | Bursty 12 kWh/day profile; how much tank headroom to hold |
| G4-10 | Spring-collapse hand-off | A | 2025-03-22 after a 92 kWh day | Creativity | On collapse days, distribute the next batch to a still-cold site |
| G4-11 | 2-hour-deadline buyer | A+B | Urgent job on a warm afternoon | Scheduling | Price the urgency: deadline overrides heat; show the CHF premium |
| G4-12 | Two-heartbeat split screen | B | Jan 10 vs a July day | Design | Same code, two heartbeats, one clock |
| G4-13 | Grid-operator button | A+B | Winter evening, imports short | Creativity | Full-tank houses shed load on a utility signal; tank = flexibility reservoir |
| G4-14 | Where it stops paying | B | The marginal server | Transparency | Per-N chart; shade where a server buys compute but no extra heat |
| G4-15 | One-server house | A+B | N=1 | Feasibility | Honest 1-server product: a hot-water appliance, not a heater |

**Worker's top 3:** (1) G4-07 — the January day, compressed, with the real process paused/resumed row by row by the same scheduler. (2) G4-01 — the 29-hour siege, honest about where heat is the limit. (3) G4-02 — cliff-day rule, gain unmeasured (worker notes heat-following never dumps by construction, so any gain is in backlog utilisation, not dump).
**Orchestrator flags:** G4-04 brings the first *cited* impact evidence for sovereignty (FDPIC). G4-13's Swissgrid fact cuts both ways (winter load) — keep for the utility framing, check in C3. G4-06 (atomic jobs: choose start time) is a genuinely different scheduling primitive from pause/resume.
**Worker discards (10)** → Graveyard W-G4.

### G5 — BEHAVIOURAL / INFORMATIONAL  *(returned 22:55 CET; report `workers/gen-G5-behaviour.md`)*
**16 ideas** (7 approach, 7 demo, 2 both). **Evidence quality: moderate** — 2 pages opened: Octopus Saving Sessions FAQ (baseline = average of the same half-hours over the previous 10 weekdays; invitations 2–6 h ahead; opt-in) and AWS EC2 Spot docs (two-minute interruption notice; "be prepared for interruptions"); UK BIT energy-label PDF failed to extract (A–G claim rests on a snippet only); computed with `workers/scratch-g5/c.py` (reproduced N=4 58% / 64.7% / 0.226; capex-loaded 0.509 N=4, 0.579 N=8). Worker flags its own G5-08 CHF 3,293 as an upper bound, not a FACTSHEET number.

| ID | Name | Kind | Actor | Rubric | One-line (worker's words) |
|---|---|---|---|---|---|
| G5-01 | Slack price list ("Heat-Flex tiers") | A | compute buyer | Creativity/Feasibility | Same server-hour at 4 prices by deadline slack & interruptibility, anchored to 0.2261 |
| G5-02 | Heat-hour tariff | A+B | buyer, homeowner | Creativity | Agile-style 24-h compute price curve, cheap when the house is cold |
| G5-03 | Deadline-credit contract | A | buyer, operator | Scheduling | Missed deadline pays a credit back; "% missed" becomes CHF |
| G5-04 | Backup-heater receipt | A | homeowner | Feasibility/Design | Statement shows server share vs backup share (58% / 42% at N=4) |
| G5-05 | Winter-block subscription | A | compute buyer | Creativity | Compute sold as a seasonal block; Oct–Mar ≈ 83% of heat demand |
| G5-06 | Power-Up/Down sessions for IWB | A | utility | Creativity | Opt-in utility "sessions" with a published baseline (Octopus mechanism) |
| G5-07 | Eligibility class labels | A | compute buyer | Feasibility | Access class is a visible tag that sets price and eligible sites |
| G5-08 | Dump levy (shadow price) | A | operator | Scheduling/Transparency | Every dumped kWh charged to a visible account |
| G5-09 | A–G "Heat Label" | A+B | homeowner, judges | Design | Energy-label-style grade per house/N; red band = does not pay |
| G5-10 | Slack-slider cards | B | judges | Creativity | Each judge picks a slack tier; price and coverage move live |
| G5-11 | Click-any-number trace | B | judges | Transparency | Judge names a figure → formula, CSV row, code line, measurement in < 15 s |
| G5-12 | Verdict stamp slider | B | judges | Feasibility | Judge shouts a price; PAYS / DOES NOT PAY stamp flips live |
| G5-13 | Bet before the reveal | B | judges | Creativity | Judges guess coverage and dump before the reveal |
| G5-14 | One-minute homeowner card | B | homeowner | Design | One screen: January day, tank bar, bill, comfort |
| G5-15 | Pre-mortem card | B | judges | Feasibility | Judges circle the assumption they'd test first in a pilot |
| G5-16 | Interruption receipt | B | judges, buyer | Transparency | On pause: work saved, work repeated (0), reason, resume time |

**Worker's top 3:** (1) G5-11 — click-any-number trace (Transparency 25%). (2) G5-12 — verdict stamp slider ("does not pay" in the room; closed-form, safe live). (3) G5-01 — slack price list, paired with G5-10.
**Orchestrator flags:** G5-01 / G3-05 / G1-02 / G4-11 independently converge on *pricing deadline slack* — a convergence signal across three frames (to be checked for crowding: cloud spot/batch tiers already do this in general computing). G5-16 needs measured Wh, which needs sudo on the Mac mini (TESTED constraint) — C2 must find a path.
**Worker discards (12)** → Graveyard W-G5.

### G2 — IN-SOLUTION MECHANISM  *(returned 22:57 CET; report `workers/gen-G2-mechanism.md`)*
**15 ideas** (8 approach, 6 demo, 1 both — the worker's own count; its table marks some kinds differently). **Evidence quality: strongest so far — four computed experiments** (`workers/scratch-g2/exp.py`, `threads.py`, `threads2.py`) plus fetched pages (Wikipedia: dynamic frequency scaling, dynamic voltage scaling, model predictive control; arXiv 1310.8456 abstract). Two Wikipedia URLs 404'd; Young/Daly checkpoint-interval sources were snippets only (flagged by the worker).

**Computed findings (worker's numbers, re-verification assigned to C1):**
- **E3 — "slack buys heat" (finite arrivals, EDF, N=4, laxity-zero jobs forced to run and dump):** at 2.0 server-h/h of arrivals (50% utilisation), deadline slack 1 h → 24 h → 168 h → 720 h → 2,160 h moves **dumped heat 3,786 → 3,529 → 3,041 → 2,158 → 0 kWh** and **coverage 32.8 → 33.6 → 35.1 → 38.0 → 44.9%**, with **0 missed deadlines in every row** *(corrected in Stage 5: an artefact of deterministic arrivals — with Poisson arrivals λ=2 misses 1.6–4.9%; T8)*. At 1.0 server-h/h: dump 903 → 0 kWh, coverage 19.5 → 22.4%. *Caveats (worker): no checkpoint cost, one pool, perfect knowledge.*
- **E1 — clock modulation (ASSUMED power curve P = 0.2 + 0.8 f³):** work per kWh peaks at 1.67× at half clock, but **for equal compute delivered, an eco clock gives LESS heat coverage** — the clock is a dial *between* the two products, not a free win.
- **E2 — hysteresis band on tank level (N=4 as one block):** start/stops 831 → 107 per year for ~1 pt of coverage (57.9 → 56.8%); continuous following runs at partial load 3,680 h/yr at N=4.
- **E0 — Mac mini M4 measured scaling:** numpy matmul aggregate throughput saturates at 2.24× by 6 processes; pure-Python loop reaches 5.58× at 10 processes. Watts unreadable without sudo.

| ID | Name | Kind | Rubric | One-line (worker's words) |
|---|---|---|---|---|
| G2-01 | Fractional-server power dial | A | Scheduling | Heat-following is a continuous power cap: 3,680 h/yr at partial load (N=4) |
| G2-02 | Seasonal gearbox (clock by season) | A | Creativity | Winter full clock (heat is the product); summer eco clock (maximise work/kWh) |
| G2-03 | Slack buys heat | both | Scheduling | Deadline slack converts dumped heat into covered heat (computed curve) |
| G2-04 | Winter-only reservoir jobs | A | Feasibility | Month-scale-slack jobs park as checkpoints in summer, drain in winter: dump 3,786 → 0 |
| G2-05 | Checkpoint-priced duty band | A | Feasibility | Tank hysteresis from checkpoint cost: 831 → 107 start/stops for ~1 pt coverage |
| G2-06 | Heat-window admission control | A | Scheduling | Admit a non-interruptible job only if forecast demand over its runtime absorbs its heat |
| G2-07 | Tank-cycle burst mode (summer) | A | Creativity | July: one server flat out ~44 h fills the tank, sleeps ~2.9 days |
| G2-08 | Marginal-heat router | A | Creativity | Sites publish "heat wanted next 6 h"; checkpoints migrate to the house with headroom |
| G2-09 | Heat dial on a real process | B | Transparency | Thread-count dial on the Mac mini; measured throughput-vs-threads is the "kW" axis |
| G2-10 | Freeze, prove, thaw | B | Transparency | Judge presses "window open"; pause < 1 s; resume; output hash identical |
| G2-11 | Hear the house breathe | B | Design | Sonified control loop: pitch = heat power, silence = tank full |
| G2-12 | Jan day + Jul day, time-compressed | B | Scheduling | Same scheduler drives a real process through both days; job shape changes visibly |
| G2-13 | Forecast betrayal | B | Feasibility | Inject a wrong forecast live; receding-horizon re-plan; show dump/backup from the error |
| G2-14 | Break-even ticker | B | Transparency | Live CHF/server-h meter at 0.2261, rising with each dumped kWh |
| G2-15 | Slack slider | B | Design | Judge drags slack 1 h → 90 days; dumped kWh 3,786 → 0 (precomputed) |

**Worker's top 3:** (1) G2-03/G2-15 slack buys heat (computed curve + one-interaction demo; "turns the heat-vs-compute tension into a tariff"). (2) G2-10 freeze-prove-thaw (hash-checked interrupt). (3) G2-02 seasonal gearbox (least familiar; 1.67× rests on an assumed curve — measure first).
**Orchestrator flags:** **E3 is the first result that ties a compute-side product parameter (deadline slack) to the rubric's primary scheduling metric on the reference house (coverage at least dump), with missed deadlines tracked.** It converges with G1-02, G3-03, G3-05, G4-11, G5-01 from five other frames. C1 must re-derive it independently (arrival model, slack distribution, checkpoint cost) before it is quoted. E1 is a useful *negative*: slowing down is not free heat.
**Worker discards (9)** → Graveyard W-G2.

### G6 — DISTANT ANALOGY  *(returned 22:58 CET; report `workers/gen-G6-analogy.md`)*
**14 ideas** (7 approach, 3 demo, 4 both) from **13 source domains, 13 pages opened** (arXiv 2508.04854 hydro water values; Wikipedia Littlewood's rule; OSTI 5097559 ice-storage control; Wikipedia honey bee; blood.ca inventory; King Arthur sourdough; practical.engineering canal locks; gov.uk GIM8060 reinsurance layers; Wikipedia memory T cell; Iowa State crop rotation; Wikipedia hibernation; ShipStation hub-and-spoke; Wikipedia tempo rubato). Blocked: PMC/PubMed (reCAPTCHA), Springer (auth redirect), RMIT (403), eLife (404) — claims resting on those are marked snippet-only. **Evidence quality: good for ingredients; no computation.**

| ID | Name | Kind | Source domain | Rubric | One-line (worker's words) |
|---|---|---|---|---|---|
| G6-01 | Water value of a server-hour | A | Hydro reservoir dispatch | Scheduling | Run a job only if its price beats the shadow price of tank heat, a curve of tank level × week |
| G6-02 | Heat fare classes (Littlewood) | both | Airline revenue mgmt | Scheduling/Creativity | Protect server-hours for urgent jobs; sell leftover "seats" to flexible jobs heat wants |
| G6-03 | Storage-priority day plan | A | Ice-storage A/C | Scheduling/Feasibility | Discharge tank first, empty by end of day; server only tops up |
| G6-04 | Shiver swarm | both | Honeybee thermoregulation | Creativity/Design | Servers with spread thresholds recruited as the heat deficit grows |
| G6-05 | Sourdough jar | both | Sourdough feeding | Transparency/Design | Pause = fridge; resume cost grows with pause length; a real jar on stage |
| G6-06 | Summer torpor and arousal | A | Mammal hibernation | Scheduling/Feasibility | July = torpor with arousal bursts that fill the tank |
| G6-07 | Never fallow, rotate the crop | A | Crop rotation | Creativity | Seasonal job portfolio: cash crops in winter, cover crops in summer |
| G6-08 | Excess-of-loss heat layers | A | Reinsurance | Feasibility/Transparency | Size N like a reinsurance tower; backup heater = top layer |
| G6-09 | Checkpoint cross-dock | A | Freight hub-and-spoke | Feasibility | A Swiss hub sorts saved job states to the home that needs heat |
| G6-10 | Side-pond cascade | A | Canal locks | Creativity/Scheduling | Building mass as a side pond beside the tank (sensitivity) |
| G6-11 | Rubato on a January day | B | Musical rubato | Design/Creativity | Hear the day: heat = melody, jobs = metronome that borrows and repays time |
| G6-12 | Blood-bank expiry board | both | Blood-bank inventory | Scheduling/Design | Jobs as bags with days-to-expiry; missed deadline = outdate |
| G6-13 | Reservoir needle | B | Hydro gauge | Design | Dam level = tank; needle = marginal heat value; read in 5 s |
| G6-14 | Call-a-tower | B | Reinsurance | Transparency/Feasibility | Judge shouts N; exceedance layers light up with backup-heater hours |

**Worker's top 3:** (1) G6-08/G6-14 reinsurance tower + call-a-tower (exceedance hours already in the FACTSHEET; shows "does not pay"). (2) G6-01 water value (one curve explains every decision; same table drives the real pause/resume). (3) G6-05 sourdough jar (most memorable 60 s; resume-overhead parameter keeps it honest).
**Orchestrator flags:** G6-01's own caveat — with a small *lossless* tank the water-value curve may collapse to a step function; its natural reservoir is the **job backlog**, not the tank (see Stage 2 merge M1). G6-03 and G6-06 have no effect inside lossless-tank physics (worker notes it). G6-12 gives the slack idea its UI.
**Worker discards (13)** → Graveyard W-G6.

### Stage 1 summary  *(2026-11-20 23:00 CET)*
*(The "returned" times in the G1–G6 headers are when the orchestrator logged each result, 1–4 minutes after the report files were written — B2.)*
**90 ideas** generated (G1 15 · G2 15 · G3 15 · G4 15 · G5 16 · G6 14) + **63 worker-level discards** recorded. Sources actually opened: G1 1 · G2 4 · G3 1 · G4 2 · G5 2 · G6 13. Computed evidence: G2 (4 experiments), G3, G4, G5 (reference-house runs). No worker read the repo or another worker's file (all state so).

**Convergence across blind frames (a signal, not proof):**
| Theme | Frames that produced it independently | Evidence attached |
|---|---|---|
| **Deadline slack / patience as the coupling between heat and compute** (price it, store it, sell it) | **6/6** — G1-02 · G2-03/04/15 · G3-03/04/05 · G4-11 · G5-01/03/05/10 · G6-02/07/12 | **G2-E3 computed curve** on the reference house |
| Verifiable pause/resume of a real process (the must-have, made checkable) | 6/6 — G1-11/12 · G2-10/12 · G3-10 · G4-07/12 · G5-16 · G6-05 | none yet (C2) |
| Honest limits / N-sizing / "does not pay" made interactive | 6/6 — G1-09/15 · G2-13/14 · G3-01/07/09/11 · G4-01/05/14/15 · G5-12/15 · G6-08/14 | G3/G4/G5 computed |
| Fleet / distribute / geography / sovereignty | 6/6 — G1-06 · G2-08 · G3-08 · G4-04/10 · G5-07 · G6-04/09 | FDPIC quote (G4) only; nothing computed |
| Summer as bursts / torpor | 5/6 — G1-04/07 · G2-05/07 · G4-03 · G6-06 | G2-E2 (start/stop counts); no metric change in lossless physics |
| Shadow price / market for heat | 4/6 — G1-01 · G3-06 · G5-02/08 · G6-01/13 | none |
| Sonification | 3/6 — G1-13 · G2-11 · G6-11 | none |
| Utility / grid flexibility | 2/6 — G4-13 · G5-06 | Swissgrid, Octopus pages |

Six-way convergence on a theme means it is *reachable* — so it may also be what other teams reach (crowding is checked in Stage 4). Distinctness target (≥ 8 directions) is met: see Stage 2.

---

## Stage 2 — Cross-pollination (combine, don't reconcile)  *(2026-11-20 ~23:00 CET, orchestrator)*
The merge reasoning is recorded as a first-class output. "×" = combined with. Every one of the 90 ideas has a recorded fate (merged-and-alive or pruned) in the Graveyard tables G-M and G-P.

### M1 — "Patience is the battery" (core approach)
**Combines:** G3-03 *backlog is the battery* (the reframe) × G2-03/E3 *slack buys heat* (the computed evidence) × G5-01 / G1-02 / G3-05 *slack price list* (the commercial object) × G4-11 *price the urgency* (the quote) × G6-02 *Littlewood protection* (how much capacity to hold for express jobs) × G6-01 *water value* (the policy — applied to the **backlog**, not the tank) × G6-12 *expiry board* (the UI) × G3-04 / G5-05 / G6-07 / G2-04 *seasonal "winter" tier* (the long-slack product) × G2-06 / G4-06 *heat-window admission* (the fate of non-interruptible jobs) × G5-03 *deadline credits* (missed deadlines become CHF).
**Merge reasoning.** The 35 kWh tank stores 44 server-hours of heat; that is the only storage the case gives. Every frame independently found a second, much larger store that the case does *not* name: **the compute customers' patience**. A job with slack *S* can be run at any hour inside its window, so a backlog of patient jobs is heat that can be made *later, exactly when the house needs it*. G2's experiment puts a number on it on the reference house: at a fixed workload of 2 server-h/h, raising slack from 1 h to 90 days moves dumped heat 3,786 → 0 kWh and coverage 32.8 → 44.9% with 0 missed deadlines *(Stage 5: reproduced exactly by C1, but "0 missed" holds only for deterministic arrivals, and only ≤ 7 days of slack is evidenced — at 7 days dump falls just 19.5%; T2, T7, T8)*. Two consequences make it more than a tariff:
1. **The briefing's two policies are the two ends of one dial.** Slack ≈ 0 behaves like always-on (E3 at 1 h slack dumps 3,786 kWh = always-on N=2's 3,785.6 kWh); unlimited slack is heat-following. *Where a fleet sits on that dial is set by its customers' patience, not by the scheduler.* (argued from E3; C1 must verify.) *(Stage 5: verified exact at both ends, but the dial spans 0–4,000 h and evidenced slack covers only 5–20% of it; T9)*
2. **It is the rubric's own metric order.** The slack curve reports coverage → dump → utilisation → missed deadlines on the reference house, as one function of one sellable parameter.
The commercial object is a slack menu (Express / By tomorrow / This week / Winter) whose prices are *read off the reference-house curve*, so the price list itself is reproducible. *(REFUTED in Stage 5: heat-derived tier prices differ by only 2.5–4.5% — heat cannot fund a slack discount; G-S5 S1-MENU)* G6-01's water value finds its real reservoir here: the shadow price is the value of *holding* a patient job vs running it now.

### M2 — "The transcript catches up" (the live demo of M1, rebuilt from the current candidate)
**Combines:** the current candidate's *transcribe our own pitch* × G1-10 *the judge's spoken sentence as the job* × G3-03 *backlog visible* × G1-11 *open the window* × G4-07 / G2-12 *January and July days compressed* × G3-10 / G2-10 / G5-16 *hash + interruption receipt* × G6-12 *deadline countdown*.
**Merge reasoning.** The current candidate makes the transcription *move* (migration). Cross-pollinated with M1, the transcription instead *waits*: a recorder process (never paused — it is the sensor) writes the room's audio in chunks; the transcription job (the compute product) is paused and resumed by the same `decide()`; **its deadline is the end of the pitch**. When the dashboard replays a July hour, the job pauses — the on-screen transcript of *our own pitch* freezes mid-sentence and a "backlog: 47 s of untranscribed speech" bar grows: *that backlog is the battery*. When January returns, the job resumes, the transcript catches up faster than real time, the backlog drains, and the deadline is met. The judges watch the core idea, must-have #2 and the missed-deadline metric happen to their own words, on one machine, with no network dependency.

### M3 — "Same code, proven: the weather-replay bench"
**Combines:** G1-12 *year then real* × G4-07 / G2-12 / G4-12 *compressed days on a real process* × G2-10 / G3-10 / G5-16 *hash-checked interruptions* × G6-05 *resume overhead grows with pause length* × G2-05 *checkpoint-priced duty band* × G5-11 *click-any-number trace*.
**Merge reasoning.** Six frames tried to *prove* must-have #2. The strongest proof is not one paused process but the real process living through the real weather: the same `decide()` drives a real job pool through Basel 2025 at compressed time, and a reconciliation table shows simulated vs real run-hours, pause count, resume overhead and output hash (bit-identical to an uninterrupted run). Reframed for the founders it is a **pre-pilot test bench**: replay any weather year against real jobs before touching a home.

### M4 — "The pilot decision card" (honest limits as a product)
**Combines:** G4-05 *founder's verdict card* × G3-01 *the N-blind identity* × G6-08 / G6-14 *reinsurance tower + call-a-tower* × G5-12 *verdict stamp* × G3-07 *COP 2.5 vs 3.6* × G3-02 *heat is a 32% rebate* × G4-01 *29-hour siege* × G4-14 / G4-15 / G1-09 *marginal server, 1-server house, does-not-pay map* × G5-15 *pre-mortem* × G2-13 *forecast betrayal* × G2-14 *break-even ticker* × G1-15 / G3-11 / G5-13 *judges steer the numbers* × G4-09 *bursty hot water* × G4-02 *cliff-day artefact* × G5-08 *dump levy line*.
**Merge reasoning.** Feasibility (25%) asks three things verbatim: pilot basis, where assumptions stop holding, when it does not pay. Fifteen ideas answer pieces. Merged: one card, generated by the simulator, with (a) the N-blind identity — the case break-even is 0.2261 CHF/server-h for every N, so N must be chosen by the coverage promise and hardware cost, sized like a reinsurance tower with the backup heater as the top layer; (b) go/no-go thresholds derived, not asserted; (c) the three things a pilot must measure first; (d) a stamp the judges can flip by shouting a price.

### M5 — "Follow the cold, stay Swiss" (fleet)
**Combines:** G1-06 *altitude* × G2-08 *marginal-heat router* × G4-10 *spring-collapse hand-off* × G6-09 *cross-dock hub* × G3-08 *portfolio of houses* × G4-04 *hospital job refuses the node abroad* × G5-07 *eligibility labels* × G6-04 *shiver-swarm visual*.
**Merge reasoning.** Patience moves work in *time*; this moves it in *space* — but only inside Switzerland, using climate diversity (Basel vs alpine sites) so summer work still lands where heat is wanted, and a genuinely foreign node refuses swiss-only jobs. Premise untested: whether alpine reference houses have meaningful summer demand under the case formula.

### M6 — "Slow down, honestly" (supporting module)
G2-01 / G2-02 / G2-09 / G3-15 / G1-03. G2-E1: an eco clock gives more work per kWh but **less heat coverage for equal compute** — the slide's first verb is a dial *between* the two products, not free heat. Kept as a supporting module (it needs sudo watts to measure); not shortlisted as a direction.

### M7 — "Trace layer" (cross-cutting, every survivor uses it)
G5-11 / G1-08 / G5-09 / G5-14 / G5-04 / G3-13 / G3-14 / G4-08: every figure clickable to formula → CSV row → code line → measurement; per-job heat provenance; one-minute homeowner card; backup-heater share shown, not hidden. This is the Transparency (25%) instrument, not a "wow"; it is attached to every shortlisted direction.

### Merged as parameters / pruned as directions
M8 utility flexibility (G4-13, G5-06) → Q&A extension only (district grid out of scope). M9 summer bursts (G6-06, G2-07, G1-04, G1-07, G4-03) → a parameter inside M1/M3 (no metric change in lossless physics; matters only via start/stop cost, G2-E2). M10 posted heat price (G1-01, G3-06, G5-02) → folded into M1's quote. M11 sonification (G1-13, G2-11, G6-11) → optional garnish. Tactile props (G1-14, G3-12, G6-05 jar) → pruned. Details in Graveyard G-P.

---

## Stage 3 — TRANSFORM (3–5 reframings per survivor; the strongest is carried)  *(~23:00 CET)*
Prompts used: PAIR · BOUND · USE · SHIP · LOOP. ★ = carried forward.

| Survivor | Reframings | Carried version |
|---|---|---|
| **M1 Patience is the battery** | PAIR: + water value of the backlog (G6-01) → principled hold/run rule. BOUND: slack 0 → always-on; slack ∞ → heat-following; the two briefing policies become the ends of one dial ★. USE: DigitalHeat sales quotes a job at submission ("give us until Friday: 0.23 instead of 0.33 CHF/server-h, and the heat is used"). SHIP: one slack parameter in the sim + one curve + a 4-row price list read off the curve. LOOP: real customers' chosen slack updates the price list each month. | ★ **"Patience is the battery": a slack menu whose prices are read off the reference-house curve; the curve unifies always-on and heat-following as two ends of one dial.** *(Stage 5: menu refuted; dial verified at both ends; effect sized in tanks — 5.2)* |
| **M2 The transcript catches up** | PAIR: + the judge's own sentence (G1-10) as a second, short job. BOUND: deadline = end of the pitch (5 min) ★. USE: the audience sees backlog = battery with their own words. SHIP: pre-recorded rehearsal audio played as the "live" input (no mic risk). LOOP: the final transcript + its hash become the submission artifact. | ★ **Our pitch is the job; its deadline is the end of the pitch; the transcript freezes on a July hour and catches up on a January hour; backlog bar = battery.** |
| **M3 Weather-replay bench** | BOUND: the whole 2025 year on the real process at compressed time (pre-run), January + July days live ★. PAIR: + measured energy per chunk → interruption receipts in Wh. USE: DigitalHeat's ops team regression-tests a pilot scheduler on real nodes before deployment ★. SHIP: one compressed day + hash. LOOP: every replay is a regression test. | ★ **A real job pool lived through Basel 2025 under `decide()`; sim-vs-real reconciliation + identical hash; pitched as DigitalHeat's pre-pilot test bench.** |
| **M4 Pilot decision card** | PAIR: + M1's curve → "pays only if customers give ≥ X h of slack". BOUND: the founders type in *their* server spec and price ★. USE: the founders next month; the homeowner reading the coverage promise. SHIP: one generated page, 4 thresholds, 3 measurements. LOOP: each pilot measurement replaces an assumption row. | ★ **A generated go/no-go card: N-blind identity, reinsurance-tower sizing, derived thresholds incl. customer slack, the three measurements a pilot must make first; parametric in the founders' own numbers.** |
| **M5 Follow the cold, stay Swiss** | PAIR: + M1 → "two batteries: patience (time) and geography (space)" ★. BOUND: 100 Swiss houses across climate zones. USE: summer sinks without leaving Switzerland. SHIP: two weather files + one migration between laptops. | ★ **Time and space as the two batteries; space stays inside Switzerland.** (premise to verify) |
| **Current candidate (baseline)** | PAIR with M1 → the migration decision shown as a quote. BOUND: show a whole January day across 2 houses. SHIP: 2 laptops + Mac mini, mid-sentence migration. USE: fleet operator. | Carried unchanged as the **baseline to beat**; its strongest element (our own pitch as the live job) is reused in M2. |

**Shortlist sent to Stage 4 (prior art + demand, impact):** S1 = M1 (+ M2 as its demo) · S2 = M3 · S3 = M4 · S4 = M5 · S5 = current candidate (baseline). M6 and M7 are supporting modules (not vetted as directions).

### Orchestrator pre-score against the verbatim rubric (ARGUED, not measured — Stage 4–5 will move it)
| Criterion (weight) | S1 Patience battery + transcript demo | S2 Replay bench | S3 Pilot decision card | S4 Follow the cold | S5 Baseline (migrate mid-sentence) |
|---|---|---|---|---|---|
| Transparency & reproducibility (25) | High — one parameter → one curve; price list derived from it *(menu later refuted, G-S5)* | Very high — sim↔real reconciliation, hash | High — every threshold derived | Medium — adds sites & weather files | Medium |
| Feasibility (25) | High — sellable tier; "does not pay when slack < X" | Medium-high — a pilot tool | **Very high** — literally the pilot decision | Medium — alpine premise untested | Medium — residential uplinks, data movement |
| Scheduling quality on the reference house (20) | **Very high** — moves coverage and dump, tracks missed deadlines | Medium — proves the code, moves no metric | Medium — N trade-off | Low — fleet-level | Low — fleet-level |
| Creativity (20) | High — patience as storage; one dial unifies both policies | Medium — rigour, not a new idea | Medium | Medium-high | Medium — the slide's own verb, fresh theatre |
| Design (10) | High — "the more patient the job, the warmer the house and the cheaper the compute" | Medium | High | Medium | Medium-high |
| **Must-have it strengthens** | #2 (real process, deadline), #3 (balance incl. missed deadlines) | #2 (same code), transparency | #3 (break-even, does-not-pay) | case "distribute" verb | #2 + "distribute" |

---

## Stage 4 — Prior art (crowding + demand) and problem validation  *(launched ~23:01 CET)*
Three workers launched in parallel: **PA-1** (prior-art adversary on S1 + S3), **PA-2** (prior-art adversary on S5 baseline + S4 + S2), **IV** (impact validator on the problems behind S1, S5/S4, S2/S3).
**Interruption log:** all three were terminated mid-run at ~23:02 CET (host clock read 23:02:07 right after the first failure notice) by an account usage limit (HTTP 429, "5-hour limit"); no report had been written. Resumed at 23:08 CET on the restored session by **resuming each worker from its saved transcript** (SendMessage), so searches already done are not repeated; reports still go to `workers/pa-1.md`, `workers/pa-2.md`, `workers/iv.md`. *(Correction note: the Stage 2/3/4 headers originally carried estimated times 23:08/23:12/23:14; they were replaced with host-clock times. From here on every header is stamped from `date`.)*

### PA-1 — prior art on S1 (patience battery + transcript demo) and S3 (pilot decision card)  *(returned 23:09 CET; `workers/pa-1.md`)*
| Candidate | CROWDING | DEMAND | Closest prior art (closeness /10) | Crowded sub-parts | No prior published work found |
|---|---|---|---|---|---|
| S1 approach | **6** | **6** | Wiesner et al., *Let's Wait Awhile*, Middleware 2021 (7, fetched: wider flexibility windows → larger savings; carbon not heat) · Antal et al. (Qarnot), *Heating Homes with Servers*, Sensors 2021 (6, body **blocked** for PA-1) · OpenAI Batch API (6, fetched: 50% off, 24 h window) · Data Furnace 2011 (4, abstract only; slides snippet lists "delay-tolerant jobs") | deadline-tolerant scheduling against an external signal; selling latency for price; heat-demand-aware scheduling for heat reuse | slack *S* as the single measured knob moving a reference house from always-on (S=0) to heat-following (S→∞); a priced slack menu read off that curve; backlog sized in tank-equivalents |
| S1 demo | **3** | — | none found | — | live transcription frozen/resumed by a replayed heat signal with a backlog bar |
| S3 card | **4** | **4** | Data Furnace TCO (5) · load-duration sizing (6, snippets) | LDC/tower sizing; generic threshold analysis | the 0.2261 N-blind identity (obvious once stated); reinsurance framing; live PAYS stamp |

Calibration: the deep pass downgraded **2 of 6** shallow "nothing found" sub-parts. Founder reaction (PA-1): *"Qarnot's heat-aware scheduling plus carbon-aware 'wait awhile' with a battery metaphor"* — what may land is **the quantified dial on their own reference house and a priced menu**; the weak point is whether Swiss-data AI buyers are interruptible.

### PA-2 — prior art on S5 (baseline), S4 (follow the cold), S2 (replay bench)  *(returned 23:10 CET; `workers/pa-2.md`)*
| Candidate | CROWDING | DEMAND | Closest prior art | No prior published work found |
|---|---|---|---|---|
| S5 baseline "migrate mid-sentence" | **7** | **6** | **Antal et al. 2021 (fetched, PMC8073740)**: constraint-satisfaction scheduler that places *delay-tolerant tasks with deadlines* so room setpoints are met; treats migration as a cost to minimise · Qarnot Q.ware routing by heat (snippet only; DCD 403) | the live Whisper demo between laptop "houses"; a dashboard **cost-of-sovereignty** figure |
| S4 follow the cold | **3** | **4** | temperature-aware geo-distributed scheduling (Xu et al. ICAC 2013, snippet; follows cold for *cooling*) | intra-Swiss climate diversity as a summer heat sink under a residency rule |
| S2 replay bench | **3** (combination; each part established) | **4** (unverified) | CoolAir ASPLOS 2015 (sim validated then run a full year; snippet) · NVIDIA "bitwise checkpoint resume" practice (snippet) | HIL compressed-time replay of a full weather year with the *same* scheduler code + sim↔real reconciliation, pitched as a pre-pilot bench |

Also fetched by PA-2: **digitalheat.ch** — Swiss-located CPU/GPU/AI capacity, one pilot site, a planned "distributed Swiss compute and heat network", *Datenhoheit*; **no scheduling or migration claim** (a scheduler demo lands on their roadmap without colliding with anything they publish). **DeepSquare + IWB Basel** (hackernoon): ~5 kW to a three-storey Basel townhouse, roughly halving fossil use. **The briefing's "IWB + Neutral-IT (Basel 2020)" could not be confirmed** — three searches found no Neutral-IT/IWB link. Calibration: deep pass downgraded **2 of 3** candidates.

### IV — problem validation  *(returned 23:09 CET; `workers/iv.md`)*
| Problem (behind) | Verdict | Strongest anchor (fetched unless noted) |
|---|---|---|
| P1a seasonal utilisation loss (S1) | **REAL & COSTLY** (cost unsized) | Qarnot, TechCrunch 9 Jan 2023: *"the main issue with this system is that you don't need a heater all year round."* Heata rep on The Register: *"Think of it like solar thermal, you get the heat when produced."* Qarnot's answer was product choice: *"We want to tackle the baseload."* **Nerdalize's bankruptcy is NOT attributable to seasonality** (no source says so; "unsustainable losses", snippet). |
| P1b buyers trade deadline slack for price (S1) | **REAL — but only at hours to 7 days** | OpenAI Batch: *"50% cost discount compared to synchronous APIs"*, window *"can only be set to 24h"*; Anthropic Message Batches: 50%, *"most batches finishing in less than 1 hour"*; GCP flex-start: up to 25–53%, *"up to a maximum of seven days"*; Spot up to 91% off. **Weeks of slack: unevidenced.** Share of AI work that is deadline-tolerant: unsized. |
| P2a Swiss data location (S5, S4) | **REAL BUT NARROW** | privatim (Swiss DPAs), bs.ch 25 Nov 2025: *"warnt eindringlich vor der Auslagerung besonders schützenswerter Personendaten in internationale Cloud-Lösungen."* FINMA Swiss-location mandate: UNVERIFIED. Buyer premium and operator cost: unsized. |
| P2b alpine summer heat demand (S4) | **UNSIZED** by IV → **tested by orchestrator (below)** | — |
| P3 pilots decided on untrustworthy economics (S2, S3) | **NICE-TO-HAVE** (no stated pain) | Cloud&Heat: *"the business model associated with this innovation ultimately proved unsuccessful"* — not about sizing. Value rests on the case brief itself demanding transparency, which is legitimate here but must not be pitched as "industry pain". |

### Orchestrator ground-truth check — S4 premise (PA-2 "marginal" vs data)  *(23:11 CET; `scripts/s4_alpine_check.py`)*
Same case-formula house, 2025 Open-Meteo hourly weather at three sites (assumption: identical building, different climate):
| Site | grid elevation m | annual demand kWh | space heat kWh | **Jun–Aug space heat kWh** | heating days Jun/Jul/Aug | Jun–Aug mean T °C |
|---|---|---|---|---|---|---|
| Basel (reference) | 247 | 31,231 | 26,851 | **0** | 0 / 0 / 0 | 20.4 |
| Davos | 1,546 | 52,175 | 47,795 | **2,967** | 6 / 14 / 11 | 13.6 |
| Samedan (St. Moritz) | 1,704 | 60,094 | 55,714 | **6,370** | 14 / 26 / 19 | 10.4 |

**Resolution:** PA-2 judged the premise marginal from monthly means sitting near 12 °C; under the case's *daily* heating-day rule, colder summer days at altitude trigger material demand — Davos absorbs ~3,700 server-h of summer heat (≈1.7 servers continuously), Samedan ~8,000 (≈3.6). **Premise TESTED positive inside the case model.** It does not change S4's rubric fit (no effect on the reference house).

### Reconciliation — tensions found and what they turned out to mean
| # | Tension | Resolution |
|---|---|---|
| T1 | PA-1 could not read Qarnot's 2021 scheduler paper; PA-2 did | **S1's mechanism is crowded**: deadline-aware, heat-driven placement of delay-tolerant tasks is published (Antal et al. 2021) and temporal shifting is mature (Let's Wait Awhile). What survives is the **measurement and the product**: how much heat a given slack buys on the reference house, the one-dial unification, and a price list read off the curve. The pitch must name Qarnot 2021 and *Let's Wait Awhile* itself. Residual risk: the last ~24k characters of Antal et al. were unread. |
| T2 | G2-E3's headline gains (dump 3,786 → 0) need 30–90 days of slack; buyers are evidenced only at ≤ 24 h (50% off) and ≤ 7 days (GCP flex-start) | **S1 is re-scoped to evidenced windows.** Prediction for C1: 24 h–7 d slack removes *intra-week* mismatch but cannot bridge the *season*; summer dump remains → that part moves honestly onto the pilot decision card (S3). The 90-day "Winter" tier is demoted to a hypothesis (Graveyard G-S4). |
| T3 | PA-2: alpine premise marginal; orchestrator calc: 3.0–6.4 MWh Jun–Aug | Daily heating-day rule; premise holds in-model (table above). S4 stays out of the top 3 on rubric fit, but becomes a cited Q&A/roadmap line and a summer row on the card. |
| T4 | Baseline S5 is the most "demanded" (the slide's own verbs) and the most crowded (7) | Its distinctive parts are the live demo and the cost-of-sovereignty figure, not migration. M2 keeps "our own pitch as the live job"; migration becomes an optional segment. |
| T5 | Briefing/FACTSHEET says "IWB + Neutral-IT (Basel 2020)"; PA-2 found no source naming Neutral-IT as IWB's partner | **The partner name is UNVERIFIED.** Supported: an IWB Basel pilot with oil-bath servers in a 1932 multi-family building with gas backup (IV, green.ch, *snippet only*; consistent with the team briefing's description) and a DeepSquare + IWB Basel pilot (~5 kW, three-storey townhouse; hackernoon, fetched). Whether these are the same pilot is unknown. The "18 June 2020 IWB press release" is listed in the team briefing's sources (not opened in this run): re-read it before naming any partner on stage. |
| T6 | P3 has no stated industry pain, yet S2/S3 score high on rubric fit | Both are justified by the judges' own rubric (Transparency 25%, Feasibility 25%), not by market pain; pitch them as "what you asked for, made checkable", never as "the industry is hurt by bad spreadsheets". |

### Filter hit/miss log (what any "no prior published work found" is worth here)
PA-1 deep pass downgraded **2/6** shallow "nothing found" sub-parts; PA-2 downgraded **2/3** candidates; IV returned 1 REAL & COSTLY, 1 REAL (bounded), 1 REAL BUT NARROW, 1 UNSIZED, 1 NICE-TO-HAVE out of 5 problems; the orchestrator's data check **reversed** one adversary physics verdict (S4). **Working error bar: about half of shallow "not found" claims did not survive a deep pass**, so every remaining "not found" is provisional. Blocked sources: MDPI (403), PMC (wall for PA-1, open for PA-2), DCD (403), Firecrawl scrape (permission denied in this session; not retried).

### Selection — rubric fit → impact evidence → crowding (never novelty first)  *(23:12 CET)*
| Candidate | Rubric fit (verbatim weights) | Impact evidence | Crowding / demand | Decision |
|---|---|---|---|---|
| **S1′ Patience is the battery — measured** (M1 re-scoped to evidenced windows) **+ M2 "the transcript catches up"** | Highest: the only candidate that moves the reference-house metrics in the rubric's order (coverage at least dump → utilisation → missed deadlines) as a function of a sellable parameter; strengthens must-have #2 (a real process with a deadline) and #3 (missed deadlines in the balance) | P1a REAL & COSTLY (Qarnot, Heata quotes) · P1b REAL at 24 h–7 d (OpenAI/Anthropic 50%, GCP ≤ 7 d) | 6 / 6 (mechanism crowded; measurement + menu not found); demo 3 | **SELECTED #1** |
| **S3 Pilot decision card** (absorbs the seasonal truth, slack thresholds, alpine line, sovereignty cost) | Very high on Feasibility 25% (verbatim: pilot basis, where assumptions stop, when it doesn't pay) + Transparency | Demanded by the brief itself; founders "have no public number for these" (PA-1) | 4 / 4 | **SELECTED #2** |
| **S2 Same code, proven** (replay bench as the proof layer) | High on Transparency 25% + must-have #2; no metric change | P3 NICE-TO-HAVE as industry pain; rubric-driven | 3 / 4 | **SELECTED #3** (as the proof spine of the demo, not as a standalone wow) |
| S5 baseline (migrate mid-sentence) | Low on reference-house scheduling (fleet-level); creativity medium | P2a REAL BUT NARROW | 7 / 6 | Not selected — best parts reused in M2 and on the card (G-S4) |
| S4 follow the cold | Low on the reference house; fleet feasibility needs alpine partners | premise TESTED positive in-model; P2b otherwise unsized | 3 / 4 | Not selected — becomes a cited Q&A line + card row (G-S4) |

**The three survivors are complementary, not rivals:** S1′ is the idea, S2 its proof, S3 its honest limits. Each must still stand on its own in Stage 5.

---

## Stage 5 — CONVERGE on the three survivors  *(launched 23:13 CET)*

### 5.0 Failure-mode map (the specific ways each survivor could be subtly wrong) → owning angle
| # | Live risk | Survivor | Angle |
|---|---|---|---|
| F1 | Within *evidenced* slack (≤ 24 h, ≤ 7 d) the effect on the reference house is negligible → headline collapses | S1′ | C1 |
| F2 | G2-E3 is an artefact of its arrival model (flat arrivals, uniform slack, no checkpoint cost) | S1′ | C1 |
| F3 | The "one dial" claim (S=0 ≡ always-on, S→∞ ≡ heat-following) fails in detail | S1′ | C1 |
| F4 | The online heuristic is far from the hindsight optimum (unknown scheduling quality) | S1′ | C1 (LP bound) |
| F5 | The price menu is ill-defined (case break-even is constant at zero dump; tier differences come only from dumped share) | S1′ | C1 |
| F6 | Live transcription cannot catch up (real-time factor on M4), mic/noise, recorder accidentally paused | M2 | C2 |
| F7 | Checkpoint correctness: repeated or lost work across many interruptions; torn writes | M2, S2 | C2 |
| F8 | Energy measurement (must-have #1) impossible without sudo on the Mac mini | all | C2 |
| F9 | Founders: "Qarnot already did this"; Swiss AI buyers are not interruptible | S1′ | C3 |
| F10 | Transcribing our own pitch reads as a gimmick | M2 | C3 |
| F11 | Card thresholds asserted, not derived; capex (CHF 8,000) is unsourced | S3 | C1 + C3 |
| F12 | The N-blind identity is heard as "you restated our formula" | S3 | C3 |
| F13 | The seasonal truth (summer dump under evidenced slack) is not computed | S3 | C1 |
| F14 | Real-world breakers missing (flow temperature / legionella, fibre, noise, heat-as-a-service obligation) | S3 | C3 |
| F15 | Sim↔real reconciliation is true by construction ("of course it matches"); compressed time hides real lag | S2 | C2 + C3 |
| F16 | Real pause/resume overhead differs from the simulator's assumptions | S2 | C2 |
| F17 | Hash identity is meaningless for non-deterministic ML output | S2, M2 | C2 |
| F18 | Numbers in FINDINGS drift from the scripts that produced them | all | Stage 6 board |
| F19 | Concurrent novelty (other teams this weekend) | all | unmeasurable — stated, never claimed away |

### 5.1 Angles launched (three blind Sonnet workers, parallel, read-only on shared files)
- **C1 Quantitative grounding** — independent re-derivation of the slack curve (Poisson arrivals, several loads and seeds), the one-dial test, the evidenced-window slice, a hindsight **LP bound** (optimality gap), a look-ahead test, the price menu read off the curve, every pilot-card threshold, and interventions (tank 0/35/70 kWh, checkpoint overhead, job size). One command regenerates all numbers and figures.
- **C2 Demo mechanism** — a working stand-in prototype on the Mac mini of "the transcript catches up" (recorder never paused, job paused/resumed by a heat-replay controller) and the full-year replay; measured latencies, catch-up rates, the real-time factor a live transcriber needs, ≥ 20 random interruptions + a torn checkpoint write with hash verification, no-sudo energy options, reset time, build list and fallbacks.
- **C3 Founder red-team** — 60-second judge-view scripts and critique, the 8 hardest Q&A questions per survivor with evidence-backed answers and exposures, the specific probes (F9–F14), a founders'-seat ranking, and every claim that would cost trust on stage.

**Interruption log 2:** C1 and C2 were killed when the orchestrating session ended (~23:30 CET) before writing reports. Recovered on disk: C1 — `scripts/c1/core.py`, `scripts/c1/run_all.py` (unrun, no results); C2 — `workers/scratch-c2/` prototype (recorder, job, controller, correctness and measurement scripts), `measure_result.json` (pause latency median 0.66 ms over 40 trials; resume 0.06 ms; SIGTERM-to-exit 7 ms; checkpoint 108 bytes), five correctness runs, M2 runs, and an orphaned `runyears.sh` still executing the three year-replay variants (left to finish because its output is the S2 reconciliation data). Both workers were **re-run in the foreground at 23:32 CET with instructions to reuse these partial outputs**; no subagent or shell is left running at the end of the run.

### C3 — Founder red-team  *(returned ~23:16 CET, logged 23:17; `workers/c3-redteam.md`)*
Sources: digitalheat.ch + legal notice (fetched: heat as a service — *"Der Wärmeabnehmer kauft keine Serverhardware"*; compute customers incl. *"KI-, Daten- und Hosting-Arbeitslasten"* and *"sensitive applications"*; storage and backup/hybrid concepts mentioned; one pilot, later a distributed network; **no founders named, nothing public on scheduling, summer, prices or customers**); pa-1/pa-2/iv; legionella standards via snippets only.
| Sev. | Finding (C3) | Evidence |
|---|---|---|
| CRITICAL | **C-1 Buyer patience is unevidenced for *their* customers.** Only hyperscalers sell latency-for-price (OpenAI 24 h/50%, GCP ≤ 7 d); no Swiss provider batch/async tier found (snippets); DigitalHeat's own page lists hosting and sensitive apps (latency-bound). → show the curve only at 24 h and 7 d; make "what share of our customers' load tolerates 24 h?" **the first pilot measurement**; never say "Swiss customers will wait". | IV, PA-1, digitalheat.ch |
| CRITICAL | **C-2 Heat-as-a-service obligation.** In a cold week with a thin queue, who pays the backup heat? Comfort must never be conditioned on compute demand: *the backup heater is the comfort floor; slack only shapes compute.* Not answered anywhere yet → a line on the card. | digitalheat.ch business model |
| CRITICAL | **C-3 "Transcribe our own pitch" can read as a gimmick** that proves the opposite of a 5–20 kW product. Serious version: the job class DigitalHeat would actually sell (batch transcription/embedding of a stored corpus with a deadline), with measured kWh/job scaled to 1 kW; the self-transcript is a 10-second hook only, with a recorded fallback. | inferred from their product |
| HIGH | H-1 Name Qarnot first: *"Antal et al. (Qarnot) showed in 2021 that delay-tolerant tasks can be scheduled against heat demand with deadlines; we measure how much heat a given patience buys on your reference house, and price it."* (Claim the "next step" only after the full paper is read.) | PA-2 |
| HIGH | H-2 0.2261 lands badly as an "insight", well as **"your formula implies"** + the pivot to what the formula leaves out (hardware, coverage promise, dumping). | PA-1 |
| HIGH | H-3 Legionella/flow temperature: hot water needs ~60 °C at storage / 55 °C in circulation (BAG, SVGW/SIA 385/1, snippets); 50–70 °C flow straddles it; the case model is energy-only → say where the numbers stop holding (booster needed). | snippets |
| HIGH | H-4 Baseline S5: migration is exactly what Antal et al. minimise; one pilot site; utilisation is the wrong headline (rubric ranks heat covered first). | PA-2 |
| HIGH | H-5 S2: "you proved your code, not our hardware"; compressed time hides thermal lag; a hash is an engineer's trust point, weak for heat sales. | PA-2 |
| HIGH | H-6 The Davos figure must be stated as **"under the case's own formula"** (it is a model output, not a measured building); no alpine 5–20 kW sink evidenced. | PA-2, orchestrator calc |
| MED | M-1 Commercial tariffs differ from H4; buyers compare with Spot (up to 91% off). M-2 CHF 8,000/server is the largest swing factor and unsourced → label ASSUMED. M-3–M-6: unverified Neutral-IT name; Qarnot 25% summer figure snippet-only; no seasonality cause for Nerdalize/Cloud&Heat; privatim favours Swiss providers generally, not home-sited servers. | various |

**C3's founders'-seat ranking** — (i) *winning the case:* **S3 card** > **S1′ + M2** > S2 > S5; (ii) *use in their pilot:* S3 > S2 > S1′ > S5. Most dangerous questions: "Which of our customers will wait 24 h or 7 d?" · "In a cold week with no jobs, who pays for backup heat?" · "Didn't Qarnot already do this?" **15 trust-costing claims** are listed with rephrasings (§6 of the report); they feed the central fixes in Stage 6.

### C1 — Quantitative grounding  *(re-run in the foreground; returned ~23:50 CET; `workers/c1-quant.md`; one command: `.venv/bin/python scripts/c1/run_all.py` → `scripts/c1/results.json` + 5 figures, 186 s)*
Model: N=4, 35 kWh tank, 1-server-hour jobs, Poisson arrivals at λ server-h/h (5 seeds), deadline = arrival + size + S, online EDF ("run when the house wants heat; force at laxity 0"), heat balance = `refhouse.step` exactly. The killed run's `core.py` was reviewed, found correct and reused.
**G2's experiment reproduced exactly** (3,786 / 3,529 / 3,041 / 2,158 / 0 kWh) — but its "0 missed deadlines" is an artefact of deterministic arrivals; with Poisson bursts λ=2 misses 1.6–4.9%.

**S1′ at the evidenced windows** (N=4, 5-seed means; orchestrator spot-checked against `results.json`):
| λ (server-h/h) | S | dump kWh/yr | dump removed vs S=0 | coverage gain | missed % | Jun–Aug share of remaining dump | **tank-equivalents** | value of the extra heat |
|---|---|---|---|---|---|---|---|---|
| 1 | 24 h | 821 | 6.2% | +0.17 pp | 0.11 | 78% | 0.6 | — |
| 1 | 168 h | 678 | 22.5% | +0.63 pp | 0.10 | 78% | 2.2 | CHF 26/yr |
| **2** | **24 h** | **3,533** | **7.0%** | **+0.85 pp** | 1.83 | 68% | **1.1** | **CHF 35/yr** |
| **2** | **168 h** | **3,057** | **19.5%** | **+2.37 pp** | 1.64 | 79% | **3.0** | **CHF 98/yr** |
| 3 | 168 h | 5,750 | 15.8% | +3.45 pp | 8.33 | 73% | 3.3 | CHF 143/yr |
*Tank-equivalent = dump removed by slack S ÷ dump removed by adding a second 35 kWh tank at S=0.* Dump only reaches zero at S ≈ 2,000 h (three months) — no market evidence. **Winter dump is zero at every point; at λ=2 a week of slack removes the April (154 kWh) and October (89 kWh) dump and cuts May from 539 to 64 kWh, but leaves June–September unchanged (785 / 807 / 832 / 591 → 793 / 810 / 822 / 569 kWh).** Slack substitutes for the tank: **at λ=2, 168 h of slack with no tank (3,148 kWh dump) dumps less than a 35 kWh tank with no slack (3,797 kWh)** — that week still misses 1.6% of deadlines, and slack plus tank together dump 3,057 kWh.

**Other results:**
- **Hindsight LP bound** (two-stage `linprog`/HiGHS, full-year perfect knowledge): **optimality gap 0.000 pp coverage, 0.0 kWh dump** at S = 0/24/168 h, λ = 1 and 2 → *within this model* (fluid LP of the same physics, N=4, λ 1–2, S ≤ 168 h, objective = heat covered then heat dumped) the simple run-when-heat-is-wanted rule matched the hindsight optimum; it does not bound missed deadlines or anything outside the model; a perfect 24-h look-ahead does *no better* (coverage −0.1 to −0.4 pp, dump +9 to +106 kWh; only missed deadlines improve, 1.62 → 0.74% at λ=2, S=168).
- **One-dial claim:** exact at both ends — deterministic S=0 ≡ `sim(N=λ,'always')` (0.0 deviation; N=4: 9,903 kWh), unlimited backlog + S=∞ ≡ `sim(N,'follow')` (0.0 deviation). But the dial spans 0 to ~4,000 h; the evidenced region (≤ 168 h) covers ~5% (λ=4) to ~20% (λ=2) of it. With finite supply, S=∞ is supply-capped (λ=2: 44.6% coverage, not 58%).
- **Price menu: NOT real on heat economics.** Tier break-evens 0.255 / 0.252 / 0.248 CHF/server-h (Express / Day / Week, λ=2) — a 2.5% spread (≤ 4.5% at λ=1) against 25–53% market slack discounts. Heat cannot fund a slack discount; tiers could only be demand-side segmentation.
- **Pilot-card numbers:** N-blind identity verified (0.2261 for N=1..11; 0.2262 at N=12–13 from the year-end tank residual). Electricity ±30% → 0.158 / 0.294; heat valued at COP 3.6 → 0.2586. **With hardware the house needs 0.51 CHF/server-h (N=4 heat-following, 65% util, CHF 8,000 / 5 y), 0.62 at 50% util (λ=2) and 0.97 at 25% util** — hardware and utilisation, not heat, decide whether it pays. Marginal 4th server: 3,906 kWh/yr of heat = **CHF 520/yr vs CHF 1,600/yr of annualised hardware**. Coldest 29 h: supply-limited, 33% at N=4 (13 servers for 100%); with finite job supply only 8–24%.
- **Interventions:** tank 0 → 35 → 70 kWh matters most at S=0 (−710 kWh / +2.3 pp from 0 → 35); 2 min lost per resume is negligible (0.01% of server-hours); 4-h jobs roughly double-to-triple missed deadlines with heat metrics unchanged.

![C1 slack curve: dump and coverage vs slack](figures/c1_slack_curve.png)
![C1 monthly dump at S = 0 / 24 / 168 h](figures/c1_monthly_dump.png)
![C1 one dial: always-on and heat-following as the two ends](figures/c1_one_dial.png)
![C1 menu: heat fate and break-even per tier](figures/c1_menu.png)
![C1 pilot card: marginal server and threshold prices](figures/c1_card.png)

### C2 — Demo mechanism  *(re-run in the foreground; returned ~23:50 CET; `workers/c2-demo.md`; code `workers/scratch-c2/`)*
| Measured on the Mac mini (stand-in job; no real transcriber installed) | Result |
|---|---|
| Pause latency (SIGSTOP → CPU plateau) / resume latency | **0.66 ms** median (p95 0.88) / **0.057 ms** |
| SIGTERM → exit with checkpoint / restart → first committed chunk | 7.0 ms / 62 ms (p95 101 ms) |
| Checkpoint write (fsync, 108 bytes) | 0.13 ms median |
| **Exactly-once under abuse** | **135 interventions over 5 runs (50 stop/cont, 50 SIGTERM, 15 kill -9, 20 kill -9 *inside* a checkpoint write): final hash equal to the uninterrupted control 5/5, no chunk committed twice** |
| **Year replay (S2), `follow` policy, duty mapping** | **real 7,631.24 run-h vs simulated 7,631.25 (−0.0001%); 3,012 / 3,012 pause transitions; output hash equal to control**; 8,760 h replayed in 87.6 s |
| **Year replay, tank-band (`batch`) policy — the policy the visible demo needs** | simulated 7,570.0 vs real 7,570.0003 run-h; **17 / 17 pauses** (each 70 h); output hash equal to control |
| Caveat on "run-hours" (B1) | real RUN-hours are controller state time; the job's CPU time is 0.6–0.8% lower and chunks processed 1.3–1.4% fewer than run-time × median chunk time (≈ 1.1 points explained by mean vs median chunk time) |
| Catch-up rule | speed X ≥ 1 + P/R (P = pause, R = time left); worst case P=90 s, R=60 s needs 2.5× real time; measured k=0.5 drained an 87.5 s pause in ~87 s; k=0.8 never caught up |
| Published Whisper speed on M4 (opened pages) | small ≈ 7×, base ≈ 18× real time (dev.to M4 benchmark, the most pessimistic); whisper.cpp Metal on M4 Max far faster → catch-up feasible with margin, **but no transcriber runs on this Mac today** (install + rehearsal needed) |
| Energy without sudo | **not available**: `top`'s POWER column equals %CPU, not watts; real joules need a one-time human-run `sudo powermetrics --samplers cpu_power,gpu_power,ane_power -i 1000 -n 60` (idle and loaded); fallback = runtime × 1 kW, labelled "scaled, not measured" |
| Demo reset | 0.5 s (`reset.sh`) |

**C2 findings:** HIGH-1 — under the reference `follow` policy a July day is 24 micro-pauses (62% duty), January never pauses: **the visible "transcript freezes" moment exists only under a tank-band (hysteresis) policy** (17 pauses/yr of 70 h at N=1; 7,570 vs 7,631 run-h), so the yearly balance must use the *same* policy, and the demo must say so. HIGH-2 — no real transcriber installed. HIGH-3 — a whole-transcript hash is not reliable for Whisper (Metal float-rounding, temperature fallback; whisper.cpp issue #1941, GDELT): hash chunk IDs + audio bytes + per-chunk outputs (greedy, temperature 0) instead. MED — the "on/off" mapping never pauses at N=1 (+14.8% run-h: don't use it); the deadline can land in a second pause (25 s backlog at the deadline in one run: script the window). Process cleanup verified: nothing left running.

### 5.2 Reconciliation — tensions and what they turned out to mean  *(23:52 CET)*
| # | Tension | Resolution |
|---|---|---|
| T7 | S1′ was selected #1 for moving the reference-house metrics; C1 shows the move is real but **small** inside evidenced windows (−7% / −19.5% dump, +0.85 / +2.37 pp, CHF 35 / 98 per house-year) | "Patience is the battery" is TRUE and *now sized*: **24 h ≈ one extra tank, a week ≈ three tanks, a season ≈ 2,000 h that nobody sells**. It stops being the headline mechanism and becomes the creative *insight* inside the card + the story of the demo. Graveyard: the price menu (G-S5). |
| T8 | G2 reported 0 missed deadlines; C1 finds 1.6–4.9% | Deterministic vs Poisson arrivals; misses are capacity bursts, not slack. Report misses with the arrival model stated. |
| T9 | Orchestrator's one-dial framing vs C1 | Exact at both ends (good for the explanation slide), but the dial is thousands of hours long: never imply evidenced slack moves you far along it. |
| T10 | M2's visible pause vs the reference policy (C2 HIGH-1) | Use **one** policy for both the yearly balance and the demo: a tank band (start below a low level, stop when full). G2-E2 measured what that costs at N=4: coverage 57.9 → 56.8% (−1 pp) for **831 → 107 stop/starts a year** — a defensible engineering trade (checkpoint-friendly), disclosed on stage. *(B3: that trade-off is from N=4 with unlimited backlog; on the N=1 demo process the band costs 0.8% run-hours, 7,570 vs 7,631, with 17 pauses a year — quote the figures that match the setup shown.)* Never show `follow` numbers next to a `batch` demo. |
| T11 | "Same hash = proven" (S2) vs C2 HIGH-3 and C3 | The claim that survives is measured: *every chunk processed exactly once, in order, across 135 interruptions incl. 20 kills inside checkpoint writes*. For the real transcriber, hash chunk IDs + audio bytes; claim output identity only if verified on the stage machine. |
| T12 | Stage-4 ranking (S1′ #1) vs C3 founders'-seat ranking (S3 #1) | **C1's magnitudes settle it for S3.** Scheduling quality: the online rule equals the hindsight LP optimum, so the remaining waste is a *product* problem (summer volume, customer patience, hardware), which is exactly what the card makes decidable. Re-ranked below. |
| T13 | Orchestrator's Davos number vs C3 "weak claim" | Both right: it is a model output under the case formula (Davos 2,967 kWh Jun–Aug space heat with 2025 weather), not a measured building, and no alpine 5–20 kW sink is evidenced → Q&A only, phrased "under your formula". |
| T14 | Must-have #1 needs *measured* energy; the Mac mini exposes no watts without sudo (C2) | A one-time human-run `sudo powermetrics` before the pitch, stored and cited; otherwise "1 kW × measured runtime, scaled, not measured". |
| T15 | C3's CRITICAL C-2 (heat-as-a-service: in a cold week with few jobs, who pays the backup heat?) was not closed (B2 HIGH-1) | **Comfort is never conditioned on compute: the backup heater is the comfort floor and the top layer of the tower; customer patience only decides how much of the heat comes from servers.** The card shows the backup energy so the operator can price it: N=4 heat-following leaves **13,102 kWh/yr** to the backup (CHF 1,743/yr if valued like the case's COP-2.5 heat pump); with finite job supply at λ=2 it is 20,344–21,084 kWh/yr (CHF 2,706–2,804). Who pays it is a contract term only DigitalHeat can set — a pilot decision item. |
| T16 | The energy-only case model vs hot-water hygiene (C3 H-3: ~60 °C at storage / 55 °C in circulation, snippets; units deliver 50–70 °C) | Stated on the card as a place where the numbers stop holding: a 50 °C server loop needs a booster for legionella-safe storage; the model does not price that. |

### 5.3 Re-ranking after CONVERGE (against the verbatim rubric)  *(23:53 CET)*
| Rank | Survivor | Why (rubric first) |
|---|---|---|
| **1** | **S3 — The pilot decision card** | Feasibility 25% verbatim (pilot basis; where assumptions stop; when it doesn't pay) + Transparency 25%; now carries C1's measured truths: the N-blind identity ("your formula implies") → hardware and utilisation decide (0.51–0.97 CHF/server-h at an **ASSUMED** CHF 8,000/server over 5 y); the 4th server's heat is worth CHF 520/yr vs CHF 1,600/yr of hardware (same assumption); summer dump is not removable by evidenced patience; winter coverage is limited by job supply; the simple rule matched the hindsight optimum *in our model*; patience is sized in tanks; **the backup heater is the comfort floor and its kWh are shown so DigitalHeat can price who pays (T15)**; hot-water hygiene is stated as where the energy-only model stops (T16). Founders'-seat #1 (C3). |
| **2** | **S1′ — "Patience is a battery — we measured how big"** | Creativity 20% + Scheduling 20%: the run's one quantified insight for which **no prior published work was found** in our searches (caveat: about half of shallow "not found" calls failed a deeper pass, and the end of Antal et al. 2021 is unread — we may have missed one). At 2 server-h/h on 4 servers, one day of customer patience removes about as much dumped heat as a second 35 kWh tank and a week about three (0.6–1.1 and 2.2–3.3 across λ = 1–3); in our model no evidenced patience (≤ 7 days) removes the summer dump — only sizing servers or workload to summer demand does. Prior art named (Qarnot/Antal 2021, *Let's Wait Awhile*); no menu claim. |
| **3** | **S2 + M2 — "The transcript catches up", then the year on a real process** | Transparency 25% + must-have #2 + Design 10%: the single most memorable *and* measured moment — exactly-once over 135 interruptions (stand-in job). Under the tank-band policy that the visible demo needs, the year replay reconciles at **7,570.0 vs 7,570.0003 run-hours and 17/17 pauses** (the reference `follow` policy also reconciles: 7,631.24 vs 7,631.25, 3,012/3,012). Needs ONE policy for the demo and the yearly numbers, a rehearsed transcriber, chunk-level proof. |
| — | S5 baseline (migrate mid-sentence) | Still behind on rubric fit: crowding 7, fleet-level, utilisation headline; its live transcription survives inside M2 (now *waiting*, not *moving*). |

---

## Stage 6 — Adversarial review board, gate, central fixes  *(first launch ~23:53 CET — all three reviewers were stopped by a usage limit at ~23:56, after B1 had already re-run the C1 pipeline; relaunched in the foreground at 00:23 CET; reports written 00:25–00:28 CET)*
Three read-only Sonnet reviewers, run in the foreground in parallel, covering the five required lenses: **B1 correctness/methodology + reproducibility** (re-runs every script from a fresh shell, audits the C1 model and the LP, checks C2's reports) · **B2 consistency + Graveyard completeness** (every number in FINDINGS vs its source; every one of the 90 ideas and every discard has a recorded fate; no "novel/unique" claims) · **B3 red-team + goal-fit** (attacks the re-ranked survivors against the verbatim rubric and the baseline; checks each survivor carries the required fields).

### 6.1 Board results  *(00:25–00:28 CET; `workers/board-B1.md`, `board-B2.md`, `board-B3.md`)*
| Reviewer | CRITICAL | HIGH | Key results |
|---|---|---|---|
| **B1** correctness / methodology + reproducibility | none | none | **C1 pipeline re-run from a fresh shell (179.6 s): 5,893 values identical to the previous `results.json`** (the only "differences" are NaN ≠ NaN at λ=0.5, zero dump). `refhouse.py` prints REPRODUCES; the alpine table matches Stage 4. Code audit: EDF policy as described, heat balance = `refhouse.step`, LP formulation correct and a valid relaxation, tank-equivalents and hardware break-even computed as defined, tier attribution identical under both methods; the zero optimality gap is real, not an artefact (eager greedy is near-optimal here). Verified every headline number (λ=2 dump 3,797/3,533/3,057; +0.85/+2.37 pp; 1.1/3.0 tanks; CHF 35/98; 3,148 vs 3,797; tiers 0.255/0.252/0.248; 0.51/0.62/0.97; 3,906 kWh = CHF 520 vs 1,600; 33%; 0.2261; G2-E3 reproduction; C2's 7,631.24/7,631.25, 3,012/3,012, 135 interventions, all hashes equal). MED: "run-hours" are controller state time (CPU −0.64%, chunks −1.4%), omitted in FINDINGS. LOW: three wording/scope items; a log gap for one chunk in seed 3. `pgrep`: nothing running. |
| **B2** consistency + Graveyard completeness | none | **2** | **All 90 idea IDs and all 63 worker discards have a recorded fate (none missing)**; every Stage 4–5 rejection carries proposer, reason, evidence and revival; no numeric mismatch against any worker report; no "novel/unique" assertion. HIGH-1: C3's CRITICAL C-2 (who pays backup heat) never reconciled; C3 claim #9 had no Graveyard row. HIGH-2: "IWB + Neutral-IT" stated as fact in Stage 0 and T5 inconsistent with IV's green.ch snippet. MED: corrected claims carried no inline marker where first stated; Stage 6 header time was an estimate; Stage 6 had no outcomes yet. LOW: Stage 1 "returned" times are logging times; G2/G4 kind counts; "clears May" overstated; "—" cells in the W table. |
| **B3** red-team + goal-fit | none | **3** | Weighted rubric scores (1–5, judgement): **S3 card 3.85 · S1′ patience 3.80 · S2+M2 live proof 3.20 · S5 baseline 2.65**; S3 vs S1′ is within noise; **presented as one structure the three score ≈ 4.2**. HIGH-1: §5.3 paired the freezing-transcript demo (tank-band policy) with `follow`-policy replay numbers. **HIGH-2: must-have #1 is carried by no survivor** (no transcriber installed, no measured energy, no second job type, no jobs/day source). HIGH-3: "not-found-in-print" against the run's own ~50% error bar. MED: tank-band trade-off quoted from a different experiment (N=4 vs the N=1 demo); "LP-optimal" over-general; "patience = tanks" single-load; "a week beats the tank" single-load with a cost; "summer is a product problem" is judgement; Qarnot wording; CHF 8,000 unsourced; C-2 and legionella missing from the card. Pick for the single moment: **the transcript catching up, with the year replay as its proof; the PAYS stamp closes** (if no rehearsed transcriber: the stamp becomes the memorable moment). |

### 6.2 Central fixes applied (one place, by the orchestrator)  *(00:30 CET; `scripts/stage6_fixes.py`, 25 asserted replacements)*
- **B2 HIGH-1 / B3 M8 →** new reconciliation rows **T15** (backup heater = comfort floor; backup energy shown: 13,102 kWh/yr at N=4 heat-following, CHF 1,743/yr at the case's heat value; 20,344–21,084 kWh/yr with λ=2 job supply) and **T16** (hot-water hygiene: where the energy-only model stops); both added to the card's description; Graveyard row **CL-11**.
- **B2 HIGH-2 →** "Neutral-IT" flagged UNVERIFIED in §0.1 and §0.4(e); T5 and C-NI reconciled with IV's snippet (an IWB oil-bath-server pilot is supported, the partner name is not; the "18 June 2020" release is from the team briefing's source list, unopened here).
- **B3 HIGH-1 →** §5.3 and the C2 table now quote the **tank-band replay (7,570.0 vs 7,570.0003 run-h, 17/17 pauses)** for the visible demo; the `follow` replay is labelled the reference-policy check. **B1 MED →** run-hours caveat added to the C2 table.
- **B3 HIGH-3 / M2–M5 →** S1′ reworded to "no prior published work found in our searches (we may have missed one)", the LP claim scoped to its model, patience-in-tanks given as ranges across loads, "a week beats the tank" qualified (λ=2, 1.6% misses), "product problem" replaced by the measured statement. **B3 M1 →** tank-band trade-off figures labelled by setup (N=4 vs N=1).
- **B2 MED/LOW →** inline "(corrected in Stage 5 …)" markers at every first statement of a later-corrected claim (G2's 0 misses, the menu, the one-dial claim); Stage 1 time note; kind-count note; May/shoulder-season numbers corrected (April 154 → 0, October 89 → 0, May 539 → 64 kWh; June–September unchanged); W-table "—" explained; Stage 6 header re-stamped.
- **B3 HIGH-2 (must-have #1)** is a *build* gap that this run cannot close (no installs, no sudo). It is handed to the human explicitly: in every survivor's build list below, in "Not covered", and as open items 1–3.

**Re-verification (grep, 00:30 CET):** 0 unflagged "Neutral-IT" mentions · 0 "not-found-in-print" · 0 "already optimal for this house" · `7,631.24` only in the reference-policy row and as the labelled reference check in §5.3 · T15 and T16 present · CL-11 present · 0 "novel/unique" assertions. All 25 replacements asserted exactly once before writing.

### 6.3 Sufficiency gate  *(00:31 CET)*
**STOP — no second board round.** No CRITICAL finding in any round. Four of the five HIGH findings were wording, scope or reconciliation gaps: each is fixed centrally and grep-verified, and none changes a number (B1 reproduced every number bit for bit). The fifth (must-have #1) is outside this run's remit and is handed over explicitly. The verbatim rubric is addressed by the combined structure (B3 ≈ 4.2/5). Every tension T1–T16 is resolved or explicitly handed to the human. What remains is LOW (e.g. W-table evidence cells, a one-chunk log gap). Another review round would re-read text-only fixes; the playbook names over-review as its most expensive failure mode.

---

## Final — the three survivors, made defensible  *(00:31 CET)*
*(The brief's required fields for each: what the judge sees in 60 s · what we must build · which must-have it strengthens · risks · fallback. All numbers are from `scripts/c1/results.json` / `workers/scratch-c2/run/*/report.json`, verified by B1.)*

### #1 — S3 "The pilot decision card"  (Feasibility-led; B3 3.85/5; founders'-seat #1)
- **The judge sees in 60 s:** "Your formula gives 0.2261 CHF per server-hour at *any* number of servers while no heat is wasted — so the break-even doesn't choose N; coverage and hardware do." → the load-duration curve drawn as 0.8 kW layers with the **backup heater as the top layer (the comfort floor: 13,102 kWh/yr at N=4)** → a threshold table: at an **ASSUMED** CHF 8,000/server over 5 years the house needs ≥ **0.51 CHF/server-h at 65% utilisation, 0.62 at 50%, 0.97 at 25%**; the 4th server's heat is worth CHF 520/yr against CHF 1,600/yr of hardware → "where it does not pay": summer, low utilisation, electricity +30% (0.294), a 50 °C loop needing a hot-water booster → **the three things your pilot must measure first:** (1) share of customer load that tolerates 24 h / 7 days, (2) winter job volume per house, (3) hardware cost and lifetime (plus real heat recovery and flow temperature) → a judge names a compute price and the stamp flips **PAYS / DOES NOT PAY**.
- **What we must build:** a page generated by `simulate_year` (C1's `run_all.py` + `results.json` is the working prototype): the identity, the layered LDC chart, the threshold grid (5k/8k/15k × 3/5 y, from C1-G), backup kWh, the summer row, the three measurements, and a closed-form price input driving the stamp; every number tagged with its source or ASSUMED.
- **Must-have strengthened:** #3 (yearly balance incl. break-even CHF/server-h and "when it does not pay"); rubric Feasibility 25% verbatim.
- **Risks:** CHF 8,000 is unsourced and the largest swing; "you restated our formula" (say "your formula implies"); the stamp can read as showmanship; who pays the backup is DigitalHeat's contract term (T15); thresholds inherit the case simplifications (lossless tank, flat H4 tariff, energy-only heat).
- **Fallback:** a static printed card with three pre-computed price scenarios; a screenshot if the page fails.

### #2 — S1′ "Patience is a battery — we measured how big"  (Idea-led; B3 3.80/5)
- **The judge sees in 60 s:** the slack curve (`figures/c1_slack_curve.png`) with the 24 h and 7-day windows shaded: *"On your reference house, at 2 server-hours of jobs per hour on 4 servers, letting jobs wait one day removes about as much dumped heat as a second 35-kWh tank; a week, about three tanks (0.6–1.1 and 2.2–3.3 across the loads we tried). But the summer would need about three months of patience — and nobody sells that: OpenAI and Anthropic batch windows are 24 h, GCP flex-start 7 days. Qarnot's Antal et al. showed in 2021 that deadline-tolerant jobs can be scheduled against heat demand; we measured how much heat a given patience buys — and in our model the simple run-when-heat-is-wanted rule matched the hindsight optimum."*
- **What we must build:** deadlines and a job-arrival model inside the shared `decide()` and `simulate_year` (EDF "run when the house wants heat, force at laxity 0"), with a sourced jobs/day figure or an explicit "unlimited backlog"; the curve and the LP check (C1's `core.py` is the reference implementation).
- **Must-have strengthened:** #3 (heat covered, dumped and % missed deadlines in the balance) and #2 (deadlines on the real process); rubric Scheduling 20% + Creativity 20%.
- **Risks:** Swiss buyers' patience is unevidenced — present it as the first pilot measurement (C3 C-1); the mechanism is crowded (Antal 2021; *Let's Wait Awhile*) — name them first; the effect is small (CHF 35–98 per house-year at λ=2); Poisson bursts give 1.6–4.9% missed deadlines; no prior published work found for the curve, but ~half of such calls failed a deeper pass.
- **Fallback:** the PNG and a five-line table; no live element.

### #3 — S2 + M2 "The transcript catches up — then the year on a real process"  (the live proof; B3 3.20/5 alone, but it carries a gate item)
- **The judge sees in 60 s:** on a January hour our pitch is being transcribed live by a real job on the Mac mini; its deadline is the end of the pitch → a July hour: tank full, the same `decide()` that produced the yearly numbers pauses the job (tank-band policy, stated on screen) → the transcript freezes mid-sentence and a "backlog: 47 s of untranscribed speech" bar grows — *"this backlog is a battery"* → January returns: the job resumes, catches up faster than real time and meets the deadline → *"the same `decide()` just drove this process through all 8,760 hours of 2025: 7,570.0 run-hours simulated, 7,570.0003 real, 17 of 17 pauses, every audio chunk processed exactly once — tested over 135 interruptions, including 20 kills in the middle of a checkpoint write."*
- **What we must build:** a recorder that is never paused; a per-chunk transcriber wrapper (whisper.cpp or mlx-whisper, small/base, greedy, temperature 0 — **install and download the model before the venue**); the controller with the shared `decide()` and the tank-band policy (prototype in `workers/scratch-c2/`), used for the yearly numbers too; a dashboard (backlog bar, transcript, RUN/PAUSE, clock); the year-replay runner and reconciliation renderer (exist); `reset.sh` (0.5 s, exists); **must-have #1:** a one-time human-run `sudo powermetrics --samplers cpu_power,gpu_power,ane_power -i 1000 -n 60` on the transcription job → Wh per audio-minute → scaled to the 1 kW reference server; a second job type (embedding a stored corpus) with a jobs/day source.
- **Must-have strengthened:** #2 (one scheduler drives the 8,760-h simulation *and* a real paused/resumed process) and, once measured, #1; rubric Transparency 25% + Design 10%.
- **Risks:** no transcriber runs on the Mac today (published M4 speeds of 7–18× real time comfortably exceed the ≤ 2.5× catch-up need, but this is unmeasured here); a whole-transcript hash is not reliable on Whisper (prove exactly-once with chunk IDs and audio-byte hashes); the visible pause requires the tank-band policy everywhere (−0.8% run-hours at N=1); the deadline can land in a second pause (script the window); machine contention on stage; gimmick risk (C3 C-3), so frame it as "one job class, batch transcription with a deadline, measured and scaled to 1 kW".
- **Fallback:** the stand-in job, which works today, fed by pre-recorded rehearsal audio; a recorded video; the stored `report.json` plus a 10-second live July week. If no transcriber can be rehearsed, the PAYS stamp becomes the memorable moment (B3).

### The pitch: one structure using all three  (B3 ≈ 4.2/5 combined vs 3.85 best single; fits the mandatory order)
| Time | Said / shown | Serves |
|---|---|---|
| 0:00–0:35 | **Key figures** on the reference house: N=4 heat-following covers 58%; always-on dumps 9,903 kWh; *your formula implies* 0.2261 CHF/server-h for every N; with hardware (ASSUMED CHF 8,000 / 5 y) the house needs ≥ 0.51 | mandatory opening · Transparency · Feasibility |
| 0:35–1:25 | **January day**, live: heat wanted, our pitch's transcript runs, backlog near zero; policy named on screen (tank band) | Scheduling · must-have #2 · Design |
| 1:25–2:35 | **July day**, live: tank full → job pauses → transcript freezes, backlog bar grows ("the backlog is a battery") → January returns → it catches up; deadline met | the interrupted real process · Creativity · Design |
| 2:35–3:15 | **Same code, proven:** the year replay of the same `decide()` (7,570.0 vs 7,570.0003 run-h, 17/17 pauses; exactly-once over 135 interruptions); measured Wh/audio-minute scaled to 1 kW | Transparency 25% · must-haves #1 + #2 |
| 3:15–4:00 | **Patience is a battery:** one day ≈ a second tank, a week ≈ three, the summer needs a season nobody sells; Qarnot 2021 and *Let's Wait Awhile* named; rule = hindsight optimum *in our model* | Creativity · Scheduling |
| 4:00–4:50 | **The decision card:** thresholds, backup = comfort floor, summer doesn't pay, the three pilot measurements; a judge names a price, the stamp flips | Feasibility 25% · must-have #3 |
| 4:50–5:00 | Close: "Here is when it pays — and the three numbers your pilot should measure first." | — |
**Q&A preparation (C3):** "Which of our customers will wait 24 h or 7 days?" → no evidence yet; it is pilot measurement #1 · "In a cold week with no jobs, who pays the backup heat?" → T15 · "Didn't Qarnot do this?" → yes, Antal et al. 2021; we measured how much patience buys · legionella → T16 · "where does summer compute go?" → under your formula with 2025 weather a Davos house needs ~3 MWh of space heat in June–August (model output, Q&A only) · cost of sovereignty → baseline appendix.

### The single most memorable, credible live-demo moment
**"The transcript catches up."** Our own pitch's live transcript freezes mid-sentence on a July hour, while a backlog bar grows ("the backlog is a battery"). It catches up and meets its end-of-pitch deadline when January returns, followed by 20 seconds of proof: the same `decide()` lived through 2025 on that process, reconciled to the simulator, with exactly-once processing under abuse. It is the only moment that shows a gate item live, it happens to the judges' own words, and it is measured. *Condition:* a rehearsed real transcriber plus the stand-in fallback; without one, close on the PAYS / DOES NOT PAY stamp as the memorable moment. **Versus the current candidate:** the job now *waits* instead of *moving*. Migration is the crowded verb (crowding 7, PA-2; Antal et al. treat migration as a cost to minimise) and moves no reference-house metric.

### Open items only Dhruv can decide or do
1. Install and rehearse a real transcriber (whisper.cpp / mlx-whisper; model downloaded before the venue), or accept the stand-in job.
2. Choose the second job type (e.g. embedding a stored corpus) and a jobs/day source (or state "unlimited backlog").
3. Run `sudo powermetrics` once on the job (must-have #1), or label energy "scaled, not measured".
4. Adopt the tank-band policy for **both** the demo and the yearly balance, or keep `follow` and give up the visible freeze.
5. A source for hardware cost per server and lifetime (or DigitalHeat's own figure) — the card's biggest swing factor.
6. Re-read the 2020 IWB release before naming any partner; read the full Antal et al. 2021 paper before saying "we take the next step".
7. Opening emphasis: feasibility-led (card first) or idea-led (patience first) — B3's scores tie within 0.05.
8. Ask DigitalHeat who carries the backup heat under heat-as-a-service, or present it as a pilot contract item.

### Run log and reproducibility
Agents spawned: 6 generators (G1–G6), 2 prior-art adversaries, 1 impact validator, 3 CONVERGE workers (C1–C3; C1 and C2 re-run once after being killed), 3 board reviewers (relaunched once after a usage-limit stop). Interruptions: two account usage-limit stops (Stage 4, Stage 6) and one session end (Stage 5); every resume reused saved transcripts or on-disk outputs, so no finished work was redone. To regenerate every number after the venv is deleted: `uv venv .venv && uv pip install --python .venv/bin/python numpy pandas matplotlib scipy reportlab markdown pyyaml requests psutil markdown-pdf pymupdf`, then `.venv/bin/python lib/refhouse.py`, `.venv/bin/python scripts/s4_alpine_check.py`, `.venv/bin/python scripts/c1/run_all.py` (~3 min), and `.venv/bin/python lib/md2pdf.py`. `workers/scratch-c2/` is 279 MB, mostly 20,000 pre-generated chunk files in `run/yearchunks` (regenerable with `recorder.py --prefill`). **The analysis venv (`.venv`, 433 MB) is deleted immediately after this PDF is generated.**

### VERDICT
| | |
|---|---|
| **Mode + why** | DIVERGE → CONVERGE. Subtle because the current candidate was a single-pass idea whose centrepiece (migration) is the case slide's own verb (crowded), the rubric scores scheduling "on the reference house" where migration moves nothing, and the case break-even is a constant (0.2261 CHF/server-h for every N) that no scheduler can beat. |
| **Angles run** | DIVERGE: 6 blind altitude frames (free · mechanism · question-the-goal · extreme user · behavioural · distant analogy) → 90 ideas + 63 discards → 7 merges → TRANSFORM → 2 prior-art adversaries (crowding + demand) + impact validator + an orchestrator data check → top 3. CONVERGE: C1 numbers (8,760-h sim, hindsight LP, thresholds), C2 live mechanism on the Mac mini, C3 founder red-team. Board: B1 correctness/reproducibility, B2 consistency/Graveyard, B3 red-team/goal-fit. |
| **What changed** | **1.** Pitch = ONE structure using three survivors (B3 ≈ 4.2/5 combined; alone: card 3.85, patience 3.80, live proof 3.20; current candidate 2.65). <br>**2. #1 Pilot decision card:** hardware and utilisation, not heat, decide whether it pays — 0.51 / 0.62 / 0.97 CHF/server-h at 65 / 50 / 25% utilisation (ASSUMED CHF 8k / 5 y) vs 0.2261 from the case formula [C1-G, reproduced by B1]. <br>**3. #2 Patience is a battery, sized:** at λ=2, N=4, 24 h of slack removes 7.0% of dumped heat (≈ 1 extra tank), 7 days 19.5% (≈ 3 tanks); summer dump untouched; zero dump needs ≈ 2,000 h, which nobody sells; the simple rule matched the hindsight LP optimum (gap 0.000) in our model [C1-A/C/D, B1]. <br>**4. #3 Live proof works on the Mac mini:** pause 0.66 ms / resume 0.06 ms; exactly-once over 135 interruptions incl. 20 kills inside checkpoint writes; tank-band year replay reconciles at 7,570.0 vs 7,570.0003 run-h, 17/17 pauses [C2, B1]. <br>**5. Single moment: "the transcript catches up"** — the job WAITS (backlog = battery) instead of MOVING; migration is crowded (7/10) and moves no reference-house metric. <br>**6. Refuted:** the slack price menu (tiers differ 2.5–4.5% vs 25–53% market discounts); "a smarter/forecast scheduler wins" (look-ahead slightly worse); the follow-policy freeze (only micro-pauses). |
| **Tensions resolved** | T1 S1's mechanism is crowded (Antal 2021) but its measurement was not found · T2/T7 big gains needed 30–90 d of slack; evidence stops at 7 d → re-scoped · T8 G2's 0 misses = deterministic artefact · T9 one dial exact at both ends but 4,000 h long · T10/B3-H1 one policy for demo + yearly numbers · T11 chunk-level, not transcript-hash, proof · T12 ranking flipped to the card · T13 alpine number = model output · T14 energy needs one sudo run · T15 backup heater = comfort floor · T16 hot-water hygiene stated. |
| **Not covered** | Must-have #1 (no real job measured yet: no transcriber installed, watts need sudo, 2nd job type + jobs/day source not chosen) · Swiss buyers' willingness to wait (no evidence; the first pilot measurement) · hardware cost source · the unread tail of Antal et al. 2021 · flow temperature/legionella (energy-only model) · concurrent teams this weekend (unmeasurable) · real founder preferences. |
| **Confidence** | MEASURED: C1 numbers (re-run bit-for-bit, 5,893 values), C2 timings/correctness, the alpine model calc. ARGUED: rankings (#1 vs #2 within 0.05), founders' reception, demo memorability. Every prior-art "not found" carries a ~50% error bar; all economics inherit the case simplifications (lossless tank, flat tariff, energy-only heat). |
| **Your call** | Feasibility-led vs idea-led opening · install a transcriber or demo the stand-in · adopt the tank-band policy for demo AND yearly numbers · hardware-cost source · 2nd job type + jobs/day source + the one sudo measurement · how to name Qarnot/Antal and the IWB partner. The reframe that ties it together is yours: this run recombines within the space; it does not make the jump. |

---

## Graveyard (every idea, angle, claim or finding generated and then rejected, merged or pruned)
*Format: ID · proposed by · why dropped · evidence used · how it could be revived.* Never deleted from; filled from Stage 2 on.

### G-S5 — Rejected, demoted or corrected at Stage 5 (CONVERGE evidence)
| ID | Idea / claim | Proposed by | Why dropped | Evidence used | How it could be revived |
|---|---|---|---|---|---|
| S1-MENU | "A slack price menu read off the heat curve" (Express / Day / Week tiers priced by heat) | Orchestrator (M1), from G5-01 / G1-02 / G3-05 / G6-02 | Heat-derived tier spread is 2.5–4.5% of break-even vs 25–53% market slack discounts: heat cannot fund the discount | C1-F, IV P1b | As demand-side segmentation if a pilot measures what share of load tolerates 24 h / 7 d; never claim heat pays for it |
| S1-DIAL | "The one dial" as a *practical* lever | Orchestrator (Stage 2/3) | Exact at both ends but the dial spans 0–4,000 h; evidenced slack covers 5–20% of it | C1-B | Keep as the explanation slide only ("always-on and heat-following are two ends of patience") |
| S1-SMART | "A smarter / forecast-aware scheduler beats the greedy rule" (G1-05 forecast pre-charge, G2-13 forecast betrayal as a gain, G6-01 water value as a better policy, G4-02 cliff-day rule) | G1, G2, G4, G6 | Hindsight LP gap 0.000; a perfect 24-h look-ahead is slightly worse | C1-D, C1-E | Only if the model adds tank losses, dynamic prices or multi-site options (then re-run the LP) |
| G2-E3-MISS | "Slack gives 0 missed deadlines" | G2 | Artefact of deterministic arrivals; Poisson gives 1.6–4.9% at λ=2 | C1-A | State misses with the arrival model; add "run early if a server is idle" (C1-E) to cut them |
| M2-FOLLOW | The transcript-freeze demo under the reference `follow` policy | Orchestrator (M2) | `follow` gives 24 micro-pauses per July day, not one visible pause | C2 HIGH-1 | Use one tank-band policy for both the yearly balance and the demo (−1 pp coverage, 831 → 107 stop/starts at N=4, G2-E2) |
| S2-HASH | "Same output hash = proven" for a Whisper transcript | G3-10 / G2-10 via M3 | Whisper output not bit-stable on Metal / with temperature fallback | C2 HIGH-3 (whisper.cpp #1941, GDELT), C3 | Hash chunk IDs + audio bytes + per-chunk greedy outputs; claim transcript identity only if verified on the stage machine |
| S2-ONOFF | Year replay with whole-hour on/off mapping | C2 (first variant) | Never pauses at N=1 (+14.8% run-hours) | C2 MED-1 | Valid for N ≥ 2 only |
| E-TOP | `top`'s POWER column as an energy measurement | (tempting shortcut) | It equals %CPU, not watts | C2 §6 | Never; use human-run `sudo powermetrics` |
| CL-1 | "Nobody schedules compute against heat with deadlines" | (would-be pitch line) | False: Antal et al. 2021 (Qarnot) | PA-2, C3 | Say "Qarnot showed X in 2021; we measured Y" |
| CL-2 | "Swiss customers will wait" | (would-be pitch line) | Unevidenced; only hyperscaler batch tiers exist | IV, C3 C-1 | Make it the first pilot measurement |
| CL-3 | "0.2261 is our discovery" | G3-01 framing | It is the judges' own formula | C3 H-2, PA-1 | "Your formula implies…, so N is chosen by coverage and hardware" |
| CL-4 | "Hot water covered" at the stated temperatures | (implicit in the case model) | Energy-only model; 60 °C storage / 55 °C circulation norms (snippets) | C3 H-3 | Say where the numbers stop holding; booster needed |
| CL-5 | Reinsurance tower as an invention | G6-08 | Load-duration sizing with a peak boiler is standard | PA-1, C3 L-2 | "Standard load-duration sizing, shown as layers" |
| CL-6 | Fleet utilisation as the headline metric | Baseline S5 | Rubric ranks heat covered first | C3 H-4 | Report utilisation second, after coverage at least dump |
| CL-7 | "Transcribing our pitch proves it works at 20 kW" | Baseline / M2 | 3–4 orders of magnitude apart | C3 C-3 | "One worked job class, measured on this Mac, scaled to the 1 kW reference server" |
| CL-8 | CHF 8,000 per server, 5 y, stated as fact | Team briefing | Unsourced; largest swing factor | C3 M-2, C1-G | Label ASSUMED; show 5k / 8k / 15k and 3 / 5 y (C1 table) |
| CL-9 | "Regulation requires swiss-only placement" | (implied by sovereignty framing) | privatim warns against international clouds; no mandate for home-sited compute found; FINMA unverified | IV P2a, C3 | Cite the privatim resolution exactly; no stronger claim |
| CL-11 | "Heat covered X%" without saying the rest is backup heat, and who pays for it | (would-be pitch line) | Hides the heat-as-a-service obligation (C3 C-2, claim #9) | C3, B2 HIGH-1 | Always show the backup share and its kWh next to coverage (T15) |
| CL-10 | Davos summer demand on a slide | Orchestrator (Stage 4) | Model output under the case formula, not a measured building; no alpine sink evidenced | C3 H-6, PA-2 | Q&A only: "under your formula, with 2025 weather, a Davos house would need ~3 MWh in Jun–Aug" |

### G-S4 — Rejected or demoted at Stage 4 (prior art, impact, selection)
| ID | Idea / claim | Proposed by | Why dropped | Evidence used | How it could be revived |
|---|---|---|---|---|---|
| S5 | **Current candidate as the centrepiece**: laptops as houses, Whisper of our pitch migrated mid-sentence, sovereignty refusal priced, fleet utilisation | Team (Dhruv's current candidate) | Crowding 7 (Antal et al. 2021 fetched: deadline-aware heat-driven placement; Qarnot routing, snippet); migration does not move the reference-house metrics the rubric scores; network fragility on stage | PA-2; rubric "on the reference house" | Keep `/migrate` as an optional 20-s segment if the founders ask for "distribute"; publish the cost-of-sovereignty number (least-occupied piece, PA-2) in a fleet appendix; "our own pitch as the job" lives on in M2 |
| S4 | Follow the cold, stay Swiss (fleet across Swiss climates) | Orchestrator merge of G1-06, G2-08, G4-10, G6-09, G3-08, G4-04, G5-07 | Rubric fit: no effect on the reference house; needs alpine partner sites; demand unsized (IV) | PA-2 (crowding 3); orchestrator calc: Davos 2,967 kWh / Samedan 6,370 kWh Jun–Aug space heat vs Basel 0 | Already partly revived: a cited Q&A line ("summer compute goes up the mountain") and a summer row on the card; full revival if DigitalHeat has or wants an alpine site |
| S1-W | The 90-day "Winter" slack tier (seasonal reservoir jobs) | G2-04, G3-04, G5-05, G6-07 | No buyer evidence beyond 7 days of slack | IV P1b: OpenAI/Anthropic 24 h, GCP ≤ 7 d | If a pilot customer signs a seasonal batch contract (archive re-embedding, yearly re-indexing) — then rerun C1 with that tier |
| C-N | "Nerdalize failed because of seasonality" (hypothesis in the IV brief) | Orchestrator (IV prompt) | No source attributes it; reported cause "unsustainable losses" | nltimes (fetched); mtsprout (snippet) | Only with a cited post-mortem — never on a slide otherwise |
| C-NI | "IWB + Neutral-IT, Basel 2020" as stated in the team briefing and FACTSHEET | Team briefing | No fetched source names Neutral-IT as IWB's partner (3 searches); the green.ch snippet (IV) describes an IWB oil-bath-server pilot without confirming the partner | PA-2, IV | Re-read the 18 June 2020 IWB press release (listed in the team briefing's sources) and quote it exactly |
| C-Q | "Qarnot routes jobs by heat demand; ~25% summer utilisation" | Search snippets (PA-2, IV) | DCD page 403; the fetched 2016 page does not confirm it | PA-2, IV | Open the DCD article; until then do not put it on a slide |
| C-P3 | "The industry suffers from untrustworthy pilot economics" | Orchestrator (P3 hypothesis) | No stated pain found | IV | Pitch S2/S3 as "what your rubric asks for, made checkable" instead |
| C-WV | "Water value / shadow price is new for heat or deferrable compute" | G6-01 via M1 | One search; LP duality on a storage constraint is standard | PA-1 | Use it as an explanation device, never as a novelty claim |

### G-P — Pruned at cross-pollination (Stage 2, orchestrator)
| ID | Idea | Proposed by | Why dropped | Evidence used | How it could be revived |
|---|---|---|---|---|---|
| G1-13 | Geiger-tick house (sonified work rate) | G1 | Sonification is Design-only garnish; no rubric evidence; venue noise | 3 frames converged (G1-13, G2-11, G6-11) but none carries a number | 10-second garnish on the Jan/Jul replay if rehearsal shows it carries in the room |
| G2-11 | Hear the house breathe | G2 | Same as G1-13 | as above | as above |
| G6-11 | Rubato on a January day | G6 | Same as G1-13; strongest of the three (paused work "repaid" before the bar line = deadline) | Wikipedia tempo rubato (fetched) | Use the rubato metaphor as one spoken line for slack |
| G1-14 | Warm mug on the laptop exhaust | G1 | Laptop air heat ≠ 50–70 °C liquid; founders know the physics; G6 discarded the same prop for the same reason | G6 W-G6-l; FACTSHEET flow temp | Only as an honest-scale sentence, no prop |
| G3-12 | Warm exhaust handover | G3 | Same as G1-14 | as above | as above |
| G6-05 (prop) | Sourdough jar on stage | G6 | Gimmick risk with experts; the *mechanism* (resume overhead grows with pause length) survives in M3 | worker's own "falls apart" note | As a homeowner-facing metaphor in a video, not on stage |
| G6-10 | Side-pond cascade (building mass) | G6 | Changes the fixed case physics (tank 35 kWh); comparability across teams | FACTSHEET | As a labelled sensitivity in M4 ("if building mass counted X kWh…") |
| G6-03 | Storage-priority day plan | G6 | Lossless tank → end-of-day depletion has no benefit in the case physics (worker's own note) | case physics | If tank losses are added in a sensitivity |
| G6-04 (as direction) | Shiver swarm (decentralised recruitment) | G6 | Same metrics as staged heat-following; no reference-house gain; visual kept for M5 | — | As the fleet visual in M5 |
| G4-13 | Grid-operator curtail button | G4 | Utility flexibility is outside the rubric metrics; district grid out of scope; Swissgrid fact cuts both ways (adds winter load) | Swissgrid blog (fetched) | Q&A answer for "what does the utility get?" |
| G5-06 | Power-Up/Down sessions for IWB | G5 | Same as G4-13 | Octopus FAQ (fetched) | Q&A answer; a one-page protocol if IWB is in the room |

### G-M — Merged into a hybrid (alive inside it; listed so nothing is lost)
| ID | Proposed by | Merged into | What survives of it | If that hybrid dies |
|---|---|---|---|---|
| G3-03 | G3 | M1 | The reframe: backlog of patient jobs = heat storage | Revive as a pitch line on any scheduler |
| G2-03 / G2-15 | G2 | M1 / M2 | E3 slack→coverage/dump curve; slack slider | Keep E3 as a sensitivity chart |
| G2-04 | G2 | M1 | Winter-only reservoir tier | Seasonal SKU slide |
| G5-01 / G1-02 / G3-05 | G5 / G1 / G3 | M1 | Slack price list read off the curve | Pricing appendix |
| G4-11 | G4 | M1 | Urgency premium quote | Q&A answer |
| G6-02 | G6 | M1 | Littlewood protection level for express jobs | Scheduler option |
| G6-01 / G6-13 | G6 | M1 | Water value of holding a patient job; needle gauge | Standalone policy (H5) if M1's heuristic underperforms |
| G6-12 | G6 | M1 | Expiry-board UI for jobs | Dashboard skin |
| G3-04 / G5-05 / G6-07 | G3 / G5 / G6 | M1 | "Winter" tier (79% of N=4 server-h fall Nov–Mar) | Seasonal SKU slide |
| G2-06 / G4-06 | G2 / G4 | M1 | Heat-window admission for non-interruptible jobs | Scheduler rule |
| G5-03 | G5 | M1 | Missed deadlines priced as credits | Contract appendix |
| G1-05 | G1 | M1 | Look-ahead *within* a job's slack window (C1 tests whether it adds anything) | Drop if C1 shows no gain |
| G1-01 / G3-06 / G5-02 | G1 / G3 / G5 | M1 (via M10) | Posted heat value enters the quote | Market framing if judges prefer it |
| G5-10 | G5 | M1 / M2 | Judges choose slack live | Audience-participation option |
| G1-10 / G1-11 | G1 | M2 | Judge's sentence as a job; "open the window" | Standalone DEMO-0003 variant |
| G1-12 / G4-07 / G2-12 / G4-12 | G1 / G4 / G2 / G4 | M3 | Compressed real days driven by `decide()` | Required Jan/Jul segment regardless |
| G2-10 / G3-10 / G5-16 | G2 / G3 / G5 | M3 | Hash identity + interruption receipt | Attach to any real-process demo |
| G2-05 / G6-05 (mechanism) | G2 / G6 | M3 | Checkpoint-cost band; resume overhead parameter | Sensitivity row |
| G5-11 | G5 | M3 / M7 | Click-any-number trace | Always attach (Transparency 25%) |
| G4-05 / G3-01 / G6-08 / G6-14 / G5-12 / G3-07 / G3-02 / G4-01 / G4-14 / G4-15 / G1-09 / G5-15 / G2-13 / G2-14 / G1-15 / G3-11 / G5-13 / G4-09 / G4-02 / G5-08 / G3-09 | G1–G6 | M4 | Card, identity, tower sizing, stamp, siege, sensitivities, dump line | Each is an independent slide/widget |
| G1-06 / G2-08 / G4-10 / G6-09 / G3-08 / G4-04 / G5-07 / G6-04 (visual) | G1–G6 | M5 | Swiss climate diversity, router, eligibility refusal | Fleet appendix |
| G2-01 / G2-02 / G2-09 / G3-15 / G1-03 | G2 / G3 / G1 | M6 | Slow-down verb as a measured dial; E1 negative result | Supporting module |
| G1-08 / G5-09 / G5-14 / G5-04 / G3-13 / G3-14 / G4-08 | G1 / G5 / G3 / G4 | M7 | Provenance, A–G label, homeowner card, backup receipt, tank+queue bar | Always attach |
| G6-06 / G2-07 / G1-04 / G1-07 / G4-03 | G6 / G2 / G1 / G4 | M9 → parameter in M1/M3 | Summer burst mode; start/stop count | Matters only with start-up cost or tank losses |

### W — Worker-level discards (ideas a generator thought of and did not develop; reasons are the worker's own)
*A "—" in the evidence or revival column means the worker gave a reason without a source, or the idea has no sensible revival (B2 LOW).*

| ID | Idea | Proposed by | Why dropped | Evidence | How it could be revived |
|---|---|---|---|---|---|
| W-G1-a | Sell heat via live CHF bids per hour | G1 | Flat tariff in the case makes it vacuous | FACTSHEET: flat H4 price | As a dynamic-tariff sensitivity if DigitalHeat contracts move off flat prices |
| W-G1-b | Bitcoin mining as the interruptible load | G1 | Off-brand for "Sovereign AI" | Case deck title | As an explicit price-floor filler for otherwise-idle hours in a sensitivity, never as the product |
| W-G1-c | Cooking food on the Mac mini | G1 | Unsafe, not credible | — | Not revivable (joke prop) |
| W-G1-d | Thermal-camera overlay | G1 | Needs special hardware | Constraint: no special hardware | If a teammate owns a phone thermal camera, as an optional visual |
| W-G1-e | Compute on a Swiss hydro price signal | G1 | Case uses a flat price | FACTSHEET | As a price-aware layer in sensitivities |
| W-G1-f | Fake power-meter graphics | G1 | Invents data; violates transparency | Rubric: transparency 25% | Never; replace with measured or clearly declared watts |
| W-G1-g | Ice storage for summer heat | G1 | Tank is fixed (35 kWh lossless) by the case | FACTSHEET | As a "tank size" sensitivity |
| W-G1-h | Distribute to a southern-hemisphere winter site | G1 | Breaks the Swiss data-location promise | Case theme | Kept as the *foil* that prices sovereignty (see G1-06) |
| W-G1-i | Drone / robot demo | G1 | No hardware | Constraint | Not revivable |
| W-G1-j | Reinforcement-learning scheduler | G1 | Opaque; hurts transparency | Rubric: transparency 25% | As an upper-bound benchmark only (an LP bound is more transparent) |
| W-G3-a | Sonify the year as audio | G3 | Low evidence value; judges cannot trace numbers | Rubric: transparency | Merge with G1-13 (Geiger house) as a Design garnish, never as evidence |
| W-G3-b | Giant 8,760-h timelapse video | G3 | Standard; no goal-questioning | — | As the backdrop for "year then real" (G1-12) |
| W-G3-c | Carbon-intensity-aware scheduling | G3 | Outside the heat-matching goal | Case scope | As an L4 layer if the founders ask about CO₂ |
| W-G3-d | Hourly heat price from spot electricity | G3 | Not in case physics; heat value fixed | FACTSHEET | As a dynamic-tariff sensitivity |
| W-G3-e | Grid-service (flex market) revenue | G3 | New revenue outside must-haves; no source | — | As a utility-facing extension if IWB asks; needs a cited Swiss flex price |
| W-G3-f | "Homeowner pays nothing" tariff | G3 | Business model, not scheduling | — | As a pitch line if DigitalHeat's heat-as-a-service model is shown |
| W-G3-g | N=13 coverage marketing | G3 | Rubric orders coverage at least dump, then utilisation | Rubric | As the upper end of the N sweep |
| W-G3-h | Forecast pre-charge of the tank | G3 | "Obvious extension, not goal-questioning" | — | Same idea survives as G1-05 / G2 (other frames) |
| W-G3-i | Solar "Prepper" stretch | G3 | Explicitly not scored | Brief | As a stretch slide only |
| W-G4-a | Night-time compute-only rate | G4 | No occupancy-driven hourly heat shape in the case model | G4 data check | If DigitalHeat has real hourly heat profiles with occupancy peaks |
| W-G4-b | Blackout / Prepper day | G4 | Stretch, not scored | Brief | Stretch slide |
| W-G4-c | Carbon-intensity scheduling | G4 | No data in the fact sheet | — | With a cited Swiss hourly carbon-intensity series |
| W-G4-d | Dump heat into a swimming pool | G4 | Not in the model's tank/physics | Case physics | As a fleet "summer sink" site in a portfolio scenario |
| W-G4-e | Electricity price-spike hour | G4 | Price is flat in the case | FACTSHEET | Dynamic-tariff sensitivity |
| W-G4-f | Heat-pump coupling (COP varies with T) | G4 | Heat value fixed at /2.5 by the case | FACTSHEET | Survives in G3-07 as a sensitivity |
| W-G4-g | Noise-limited night mode | G4 | No noise data; unsourced | — | With a measured dB figure for a 1 kW liquid-cooled node |
| W-G4-h | 20% winter coverage sold as heat-pump pre-heat | G4 | Merged into G4-15 | — | See G4-15 |
| W-G4-i | Tenant-vs-owner split incentive | G4 | No data | — | With Swiss rental-market heating-cost rules (Nebenkosten) as a source |
| W-G4-j | First warm day of spring as its own idea | G4 | Folded into G4-10 | — | See G4-10 |
| W-G5-a | Carbon-credit trading for dumped heat | G5 | Needs a market and carbon accounting beyond the case | — | Only with a real Swiss heat-certificate scheme |
| W-G5-b | Gamified homeowner leaderboard | G5 | No evidence it helps; off-question | — | Not recommended |
| W-G5-c | Pay homeowners per server-hour | G5 | Conflicts with heat-as-a-service (building owns no hardware) | FACTSHEET | If DigitalHeat changes its contract model |
| W-G5-d | Crowdfunded servers | G5 | Financing, not matching | — | Business-plan appendix |
| W-G5-e | Live auction of buyers vs homes | G5 | Complex; G5-02 gets most of the effect | — | Merge with G1-01 / G3-06 if a market framing wins |
| W-G5-f | Prepaid heat tokens | G5 | Cash-flow, not matching | — | Not recommended |
| W-G5-g | "Feel the heat" noise/temperature prop | G5 | Needs hardware (frame violation) | Frame rule | Survives in G1-14 / G3-12 (other frames) |
| W-G5-h | Blockchain provenance for jobs | G5 | Hashes in G5-11 already give tamper evidence | — | Not recommended |
| W-G5-i | Public leaderboard of teams | G5 | Not about this brief | — | — |
| W-G5-j | Sell heat credits to neighbours | G5 | District-grid-like; out of scope | Brief | — |
| W-G5-k | Judges role-play compute buyers | G5 | Merged into G5-10 | — | See G5-10 |
| W-G5-l | Homeowner push notification when tank full | G5 | Low value; no one-minute read | — | — |
| W-G2-a | Overclock for cold snaps beyond 0.8 kW/server | G2 | Unsourced boost headroom; folded into G2-02 | — | With a measured boost power figure for a real 1 kW node |
| W-G2-b | Pure "race to idle" | G2 | Idle servers make no heat; folded into E1 | Wikipedia DVS (fetched) | As a summer-only policy inside G2-02 |
| W-G2-c | Run until tank empty to bank heat | G2 | Lossless tank → no gain over G2-01 | Case physics | If tank losses are added in a sensitivity |
| W-G2-d | Price-based scheduling | G2 | Flat electricity price in the case | FACTSHEET | Dynamic-tariff sensitivity |
| W-G2-e | Heat storage in building mass | G2 | Outside fixed physics | Case physics | As a "beyond the reference house" pilot note |
| W-G2-f | Dump-to-hot-water-only in summer | G2 | Already in the model | — | — |
| W-G2-g | Bin-packing jobs into tank cycles | G2 | Covered by G2-07 | — | See G2-07 |
| W-G2-h | Thermal-throttling demo | G2 | No heat sensor available | Constraint (no special hardware) | With a cheap USB thermometer if allowed |
| W-G2-i | Cooling-fan noise demo on the Mac mini | G2 | Fan likely silent at these loads (unverified) | — | Test on the Omen (louder fans) |
| W-G6-a | Orchestral tempo as an approach | G6 | Mapping adds nothing to the scheduler | — | Survives as sonification (G6-11) |
| W-G6-b | Immune memory (warm caches / resident jobs) | G6 | Duplicates G6-05/G6-09; no scheduler consequence | Wikipedia memory T cell (fetched) | If warm-start cost per site is measured |
| W-G6-c | Bird-migration stopover rule | G6 | Source fetch blocked; G6-01 already covers it | Springer blocked | Cite a fetched optimal-migration paper |
| W-G6-d | Postal deferred mail classes | G6 | No mechanism found; same as G6-02 | USPS search only | Merge into slack tiers (H1) |
| W-G6-e | Tidal windows at sea locks | G6 | Search found nothing | — | Map to forecast heat windows (G2-06) |
| W-G6-f | Restaurant mise en place | G6 | Weak mapping; not searched | — | — |
| W-G6-g | Beehive cluster rotation | G6 | No rotation mechanism found | Wikipedia (fetched) | A fairness rule for which server throttles |
| W-G6-h | Airline overbooking | G6 | Risky with deadlines | — | Only with a measured no-show/cancel rate of jobs |
| W-G6-i | Ice-storage MPC beyond storage priority | G6 | Needs forecasts; folded into G6-03 | OSTI (fetched) | See G6-03 |
| W-G6-j | Insurance quota share | G6 | Same as simple load splitting | — | — |
| W-G6-k | Blood-bank sharing between hospitals | G6 | Folded into G6-09 | — | See G6-09 |
| W-G6-l | Ice-bag / hot-water prop as the tank | G6 | Mac mini heat cannot visibly warm a cup; not credible to founders | Physics | Not recommended |
| W-G6-m | Thermal camera / feel-the-heat | G6 | Special hardware | Brief | — |
