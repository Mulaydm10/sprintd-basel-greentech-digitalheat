# PLAN — robust scheduler, then deployment system (DRAFT v1, 2026-11-21 CET)

> Status: **DRAFT for Dhruv's review.** Nothing is claimed; contracts and issues are unchanged until approved.
>
> Sources merged:
> - **[T]** teammate PDF `Compute-Heat_Solution_Explained.pdf`
> - **[H]** Heatmesh Field Manual (artifact)
> - **[N]** NW Swiss Compute-Heat Brief (artifact)
> - **[B]** Run B FINDINGS (`research/playbook-B/`)
> - **[O]** our briefing (`research/briefing/`)
>
> Run A produced nothing and is ignored.

## 0. Two things to settle first

1. **The teammates' scale differs from our case.** [T]/[N]/[H] model 5–20 kW GPU nodes in apartment blocks and farms across BS/BL/AG/SO, with CHF 1.70/GPU-h sovereign pricing. The DigitalHeat case we're judged on fixes:
   - **one reference house**, 1 kW server (0.8 kW heat), 35 kWh tank, Basel 2025;
   - the break-even formula (elec − heat value) ÷ server-hours;
   - must-haves: ≥2 job types; one `decide()` for both the sim and a real paused process; a yearly balance.

   **Proposal:** the case's reference house stays the *graded core*, with numbers reproduced exactly. Their fleet, market and economics become the *"how it scales"* layer on top, run by the same scheduler at a larger N.
2. **The design flip agrees with our own data.** All three teammate docs say *compute-led* (run ~85%, the thermostat only routes heat); heat-following is uneconomic. [O] found the same once hardware is counted: always-on 0.446 vs heat-following 0.509 CHF/h at N=4, and [N] has a 34k vs 3k EBIT case.
   - **But** under the case's *own* formula (no capex), heat-following looks best, and dumping is what the rubric penalises.
   - **Proposal:** don't pick a side; make it **one price-driven policy** where heat value is an input. It behaves heat-led when compute is cheap and compute-led when compute is valuable, and we show *both* numbers plus the crossover (the decision card, [B] #1). That answers "when does it not pay off" honestly.

## 1. The scheduler: best of all sources

**Core: merit-order dispatch with a heat price** ([N] + [H], replacing our draft's "Run/Pause" rules).

- Each site, each step, posts a marginal cost per kWh:
  - heat used: `MC_used = p_el − η·h(t)`, where h(t) is the heat value, rising with demand and tank deficit;
  - heat dumped: `MC_dump = p_el (+ fan)`.
- Jobs bid CHF/server-h ÷ kW. A job runs where bid ≥ MC, cheapest eligible block first, earliest deadline first.
- **Filler/ballast** jobs run only where their low price clears, so this one rule decides "dump or idle".

**Heat routing (thermostat steers the valve, not the server)** [T]/[N]:
- Priority: space heat → hot water → tank → dump.
- In the case house: no dry cooler; dumped kWh is counted and penalised.

**Patience as storage** [B]:
- Each job carries `slack`. A deferrable job's bid falls while heat is unwanted and rises as its deadline nears.
- Measured value: 24 h slack → −7% dump; 7 d → −19.5%. The greedy rule = hindsight optimum, so **no forecast optimiser** (S1-SMART refuted).
- A forecast is used only as a *check* ([N] "24 h heat budget"): don't start a long non-checkpointable job without one checkpoint interval of budget.

**Stable actuation** [B]/[N]:
- Tank-band hysteresis everywhere (prevents the 24 micro-pauses/day).
- Migrate only if `(MC_now − MC_best)·remaining_kWh > migration_cost + margin`.
- Actuator ladder, fastest first: valve → power cap/duty cycle → drain → checkpoint+pause → move.

**Sovereignty** [T]/[N]/[H]:
- `access_class ∈ {public, swiss-only/regional, certified}`; ineligible placement is impossible (a hard filter before pricing).

**Comfort and limits:**
- Backup heater share always reported [B].
- Night power cap (noise) [T]; hot water booster to 60 °C [B]/[T].

**Purity:** stays pure (no I/O), deterministic, seeded, so the same `decide()` runs in sim and live (must-have #2).

### Contract changes (proposed)

- `SiteState` += `p_el`, `heat_value`, `slack_budget`, `night_cap_kw`, `has_dump`.
- `Job` += `bid_chf_h`, `slack_h`, `checkpointable`, `class`.
- `Action` = `SetPower(site, kw)`, `Assign(unit, site)`, `Pause(job)`, `Route(site, {space, dhw, tank, dump})`.
- Drop `Migrate` as a primitive; moving = lease lapse + reassign (see §2).

### Baselines we beat, on the same job stream ([H]/[N] A/B)

1. naive thermostat (heat-led);
2. always-on;
3. ours.

Metrics:
- **Graded core:** coverage, dump kWh, break-even CHF/h (case formula and + hardware), missed deadlines, utilisation.
- **Scale layer:** EBIT.

[H] reports a thermostat-led policy at 45% past deadline vs 0% for merit dispatch; we reproduce that kind of result ourselves.

## 2. The deployment system: best of all sources

**Leases, not live migration** ([H], matches [B] demoting migration):
- Jobs are split into ~15-min idempotent **work units**.
- Nodes hold renewable leases. A crashed or tampered node's lease lapses; another node takes the unit.
- Results are content-addressed, so a duplicate counts once.
- This *is* exactly-once ([B]: hash chunk IDs, 135 interruptions).
- It also gives the "judge pulls the plug" demo (D3) almost for free.

**Architecture** ([N]): one coordinator (FastAPI). Real and simulated nodes speak **the same JSON over WebSocket**, so the scheduler cannot tell them apart.
- **Coordinator:** runs `decide()` every tick (5 min real / accelerated); lease book; fleet state.
- **Node agent (real):**
  - reads watts (`powermetrics` on Mac, NVML/RAPL on Omen);
  - applies power cap, or a duty-cycle fallback when caps are refused ([N] day-0 check);
  - pulls units; pause/resume via SIGSTOP/CONT or checkpoint;
  - measured watts are scaled to 1 kW.
- **Node agent (simulated):** a reference house from `house_model`, plus N fleet buildings.
- **Workloads (≥2 job types):**
  - (a) Whisper transcription [B], measured on the Mac;
  - (b) image tagging (SigLIP/CLIP) or entity extraction on synthetic German court text [H].
  - One sovereign/certified class, one public/ballast class.
- **Trust layer ("blockchain ideas without a blockchain")** [T]/[N]/[H]:
  - AES-GCM envelopes and X25519 key wrap;
  - key broker with *mock* attestation, stated as mock;
  - hash-chained audit log;
  - tamper button → key denied → unit re-leased elsewhere;
  - crypto-shredding.
  - Honest limits stated on stage (geofencing only to ~100 km; TEE.Fail).
- **Dashboard:** Basel reference house + fleet map, CHF ticker, A/B, audit log, decision card.

## 3. Build order (lanes map to existing issues)

| Step | What | Lane / issue | Machine |
|---|---|---|---|
| S1 | Contract v2 (§1), assumptions.yaml additions (prices, slack, η, capex 5k/8k/15k ASSUMED) | design | Omen |
| S2 | `house_model` (exact case numbers, tests vs 26,851 kWh / 206 d) + tank routing | #4 | worker |
| S3 | `scheduler` merit-order + slack + hysteresis + eligibility; 3 baselines | #6 | **Mac (first job)** |
| S4 | `simulate_year` → balance.json, A/B table, coverage/dump/break-even, crossover | #7 | worker |
| S5 | `jobs`: 2 types, units, real measurement → EXP row | #5 | Mac (has the workload) |
| S6 | Coordinator + lease book + WebSocket protocol (sim nodes first) | #8 (rename: deploy) | worker |
| S7 | Real node agent: watts, cap/duty-cycle, pause/resume, scaled to 1 kW | #8 | Mac + Omen |
| S8 | Trust layer (envelope, mock attestation, audit chain, tamper) | new lane `trust` | teammate |
| S9 | Dashboard + decision card | #9 | teammate |
| S10 | Demo: transcript catches up → A/B → pull the plug / tamper → decision card (D1 phones optional) | DEMO.md | all |

**Timeline:**
- S1–S3 by Sat ~12:00 CET; S4 + S6 by the draft at **15:00 CET**.
- Real node, trust and dashboard Sat evening; rehearsal overnight; final **Sun 08:30**.

## 4. What we take vs what we drop

**Take:**
- merit order + heat price [N][H];
- compute-led insight, shown with the crossover [T][N][O];
- leases + content-addressed units [H];
- valve priority [T];
- trust layer [T][N];
- A/B vs thermostat [H][N];
- slack-as-storage + hysteresis + honest-claims list [B];
- exact case numbers [O].

**Drop or demote:**
- live CUDA checkpoint migration (48-h stretch item in [N]);
- ICON forecasting as an optimiser;
- the 48-building fleet as the *headline* (it goes in the scale layer);
- the farm/multi-canton tariff story (appendix);
- unverified legal claims (MuKEn, TMmV) → Q&A only, flagged "to confirm".

**Verify before quoting:**
- the teammates' CHF 1.70/GPU-h and GPU prices;
- MeteoSwiss vs Open-Meteo (case uses Open-Meteo);
- 2027 vs 2026 tariff (case: IWB 2026 33.25 Rp).

## 5. Decisions needed from Dhruv
1. OK to keep the 1 kW reference house as the graded core and use the teammates' fleet as the scale layer?
2. Is the scheduler on the Mac the first job (S1 → S3 now)?
3. Add a `trust` lane for a teammate?

## Deployment requirements added by research #29 (fit-reviewed)
Leases with renewal at ~1/3 of lease length (HTCondor JobLeaseDuration 40 min as reference); lease timers frozen across a coordinator restart; degraded mode when the weather feed fails (persistence forecast, slack off, no new dumping on stale data, flagged in trace); BOINC-style backpressure / work-fetch stop; heartbeats; vacate→drain, kill→kill mapping.
