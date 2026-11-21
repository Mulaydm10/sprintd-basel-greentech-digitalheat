# How real compute-heat and carbon/price-aware schedulers work, and what our `decide()` should take (#24)

Author: parth-hp, 2026-11-21. Report only, no `src/` changes. Sources: `sources.md` (`[S#]`).
**Evidence level:** every source was read through search summaries, not full text, so every claim tagged
`[S#]` is **UNVERIFIED** until checked against the page. Statements marked *(our analysis)* are inference.

## 0. Summary

1. **Nobody we found publishes a thermostat-interrupt scheduler.** The heat operators either pull work when heat
   is wanted (Qarnot [S6]), size hardware to a steady sink (Leafcloud, hot-water buildings [S10]; Deep Green,
   pools with the gas boiler as backup [S8]), or move peaks elsewhere (Qarnot → DATA4 data centres [S5]).
   That matches our merit order: heat sets the price, it does not switch servers.
2. **Big schedulers split planning from placement.** Google's carbon-aware system plans next-day hourly
   capacity caps per cluster (VCCs), and the real-time scheduler only obeys them [S1]. Borg rejects work at
   admission when quota is short instead of discovering it at run time [S21]. Our `decide()` has no
   admission step and no plan; adding a thin one is the biggest robustness gain.
3. **Guarantees exist for exactly our problem.** "Online pause and resume" (run k hours before deadline T,
   minimise price incl. switching cost) has an optimal double-threshold algorithm with a proven
   competitive ratio [S30]; a multi-site extension exists [S31]. Our rule 4 ("hold if the cheapest
   block dumps heat") is a one-threshold heuristic with no bound.
4. **Robustness patterns are standard:** leases with renewal and expiry (HTCondor default 40 min [S23],
   Chubby KeepAlive [S25]), minimum run time before preemption (Slurm PreemptExemptTime [S19]), no
   preemption inside a priority band to stop cascades (Borg [S21]), simulate-then-EDF when a miss is
   predicted (BOINC [S22]).

**Top 5 for our next 6 hours** (detail in §5): (1) forecast admission check, (2) double-threshold slack rule,
(3) index units by eligibility to hit the 50 ms budget, (4) safe degraded mode when the forecast feed fails,
(5) minimum dwell time against flapping.

## 1. Compute-heat operators

| Operator | Algorithm / placement | Control loop | Failure handling | Optimises |
|---|---|---|---|---|
| **Qarnot** (FR) | Heat-aware grid manager [S4]; Q.rads take jobs from an encrypted building cache when occupants need heat [S6]; hierarchy QNode (global) → QBox (building) → QMobo (diskless compute) [S7] | Per-building scheduling under a global scheduler [S7]; CPU frequency lowered in summer to cut heat [S6] | Diskless, stateless nodes; suspect heaters removed until the next visit [S6]; peaks moved to DATA4 data centres [S5] | Task throughput and heating shortfall [S7] |
| **Deep Green** (UK) | Immersion "digital boiler" at a pool; heat via exchanger [S8] | Pool's gas boiler runs only when needed to hold temperature [S8] | Backup boiler covers any shortfall [S8] | Free heat for host, free cooling for operator [S9] |
| **Leafcloud** (NL) | Compute at "Leafsites" with steady hot-water demand; storage in core DCs [S10][S11] | Not published (no scheduling docs found) | Separate cooling loop never mixes with building water [S10] | Heat reuse + a public cloud product [S10] |
| **Heata** (UK) | Server on the home hot-water cylinder [S14] | Daily free-hot-water cap [S14] | Separate electricity meter [S14] | Free hot water up to a cap [S14] |
| **Nerdalize** (NL) | Servers as home radiators | n/a | Bankrupt after pilots, no follow-on funding [S15] | (post-mortem: space heating alone was not a business, *our analysis*) |
| **Cloud&Heat** (DE) | Water-cooled modular DCs where heat is needed, up to ~65 °C [S16] | Not published | n/a | Cooling + heating cost savings [S16] |
| **WindCORES** (DE) | DC inside a wind-turbine tower on local wind power [S17] | Not published | Tower acts as heat sink when no heat user exists [S17] | Green power use |

Academic heat-reuse schedulers frame it as constraint satisfaction (meet SLA and tenant heat) [S12] or
hierarchical scheduling across water heaters [S13]. **Gap:** no operator publishes its real control
loop, tick length or deadline handling; claims above are about architecture, not algorithms.

## 2. Carbon/price-aware and batch schedulers

| System | Algorithm | Control loop / tick | Failure handling | Optimises |
|---|---|---|---|---|
| **Google CICS (VCC)** | Day-ahead risk-aware optimisation → hourly per-cluster capacity caps; flexible work delayed to greener hours [S1]; DR planning + real-time placement follow-up [S2] | Daily plan, hourly caps, independent real-time scheduler [S1] | SLO and capacity constraints in the plan [S1]; robust (distributional) version in [S2] | Fleet carbon vs power peaks [S1] |
| **Carbon Aware SDK** | Returns forecast intensity for a location/time window; choosing the window is left to wrappers [S3] | On request | Provider-dependent (some lack historical forecasts) [S3] | gCO₂/kWh [S3] |
| **Kueue** | Quota per ClusterQueue, cohorts can borrow; Classic or Fair Sharing preemption [S18] | Admission loop | Proof that two queues cannot keep preempting each other under Fair Sharing [S18] | Fair share of borrowable quota [S18] |
| **Slurm** | Priority + backfill; preemption by REQUEUE/CANCEL/SUSPEND [S19]; preemption does not wait for the backfill cycle [S20] | Scheduler cycles + on submit [S20] | GraceTime before kill; PreemptExemptTime = minimum run before a job can be preempted [S19] | Throughput / priority |
| **Borg** | Quota checked at admission; non-overlapping priority bands [S21] | Continuous | No preemption within production band (prevents cascades); lower-priority quota oversold [S21] | Utilisation under SLOs |
| **BOINC** | Weighted round robin by resource share; when a simulated schedule predicts a miss, switch to EDF; stop fetching work if it would cause misses [S22] | Periodic, plus on job exit/arrival [S22] | Deadline-driven fallback to EDF [S22] | Long-run resource share, met deadlines [S22] |
| **HTCondor** | Matchmaking; jobs vacate (checkpoint then leave) or are hard-killed [S24] | Event-driven | Job lease: run continues while the submitter renews; expiry kills the job; default 40 min, too short loses work, too long ties machines [S23] | Opportunistic throughput |

Volcano and YuniKorn: searched, nothing usable returned; **not covered**.

## 3. Algorithms: guarantees vs heuristics

| Technique | What it is | Guarantee | Fit for us *(our analysis)* |
|---|---|---|---|
| Merit order / economic dispatch | Cheapest block first | Optimal per tick for linear costs, myopic over time | **What we have** (rules 2–3) |
| Double-threshold online pause/resume [S30] | Run while price is below a threshold that moves with remaining work and time; pays switching cost | **Optimal deterministic competitive ratio** [S30] | Direct replacement for rule 4's binary hold; needs price bounds (min/max MC over horizon) |
| Spatiotemporal online allocation (CarbonClipper) [S31] | Multi-site version with deadlines | Competitive, learning-augmented [S31] | Later: when units can go to several houses |
| MPC for tank/heat pump [S26][S27] | Optimise next N hours with a forecast (often MILP) | None in general; depends on forecast | Rule-based already close for simple systems [S27]; heavy for 6 h |
| Lyapunov drift-plus-penalty [S28][S29] | Each tick minimise V·cost + queue·backlog | Cost within O(1/V) of optimal, queue O(V) [S28][S29] | Gives one knob V for cost vs missed deadlines; elegant pitch line, medium build |
| EDF + slack (BOINC) [S22] | EDF only when a miss is predicted | EDF optimal on a single machine, not multi [S22] | We already order by deadline; add "predicted miss → EDF override" |
| Bin-packing heuristics | First/best fit | Approximation ratios, no deadline awareness | Our blocks are already a fractional packing |

## 4. Production robustness patterns

- **Leases + heartbeat:** renew well before expiry; expiry frees the work [S23][S25]. Chubby freezes lease
  timers while a new master is elected, so a coordinator restart does not mass-expire leases [S25].
  *For #8:* lease 15 min units with renewal at ~1/3 lease; freeze expiry for one coordinator restart window.
- **Idempotent units:** content-addressed results already planned in #8; HTCondor-style vacate-with-checkpoint
  vs hard kill maps to our drain vs kill [S24].
- **Admission control / backpressure:** reject at submit when capacity or quota is short (Borg [S21], Kueue
  [S18]); BOINC stops fetching work that would cause misses [S22].
- **Anti-flapping:** minimum run before preemption (Slurm PreemptExemptTime [S19]); no preemption inside a
  band (Borg [S21]); provable no-ping-pong between queues (Kueue [S18]).
- **Graceful degradation:** Deep Green keeps the gas boiler as backup [S8]; Qarnot sends peaks to central
  DCs [S5]. *For us:* if the weather/forecast feed fails, fall back to a persistence forecast and heat-led
  behaviour (never start dumping on stale data), and say so in `trace`.
- **Observability:** our `trace` line per decision already matches what Google's split design implies
  (plan vs execution logged separately [S1]). Add the plan/forecast version to each trace line.

## 5. Fit table (cost to build < 6 h, ranked)

| Rank | Technique | Change in our code | Expected gain | Cost | Risk |
|---|---|---|---|---|---|
| **1** | **Forecast admission check** (Borg/Kueue admission [S21][S18], VCC plan [S1], BOINC predicted-miss [S22]) | New pure `scheduler.admit(job, forecast_capacity, queue) -> Accept/Reject(reason)`; caller (sim/live) calls it at arrival; capacity = forecast heat room + dump allowance over the deadline window | Missed deadlines turn into explicit rejections at submit; customers get an honest "no" | 2–3 h | Low; additive API, decide() unchanged |
| **2** | **Double-threshold slack rule** [S30] | Rule 4 in `policy.py` (`best.kind == DUMP and slack>0 → Hold`) becomes: run if MC ≤ θ(remaining work, time left, MC bounds), with switching cost = `migration_margin_chf` | Provable competitive ratio for the pitch; fewer forced last-minute dumps | 3 h | Medium: needs MC bounds per horizon; golden numbers move → re-baseline |
| **3** | **Index units by eligibility** (production queues bucket by class) | `policy.py:147-160`: group queue by `access_class`, precompute eligible block lists once per class instead of per unit | Meets the 50 ms / 100k-unit budget (F7, #21) | 1–2 h | Low; covered by red-team F7 + determinism tests |
| **4** | **Safe degraded mode** [S8][S5] | Caller-level: if forecast missing/stale → persistence forecast, `slack_enabled=False`, no new dumping starts; `trace` says "degraded: forecast stale" | No silent bad decisions when the feed dies on stage | 1 h | Low |
| **5** | **Minimum dwell time** (Slurm PreemptExemptTime [S19]) | `next_mode_hysteresis` (`policy.py:57-62`): also require `min_dwell_h` since the last switch (new `SiteState` field, additive) | Kills residual flapping (red-team F6 class) and the on/off churn judges see | 1 h | Low |
| 6 | Lyapunov V-knob [S28] | Replace bid/MC test with drift-plus-penalty score | One tunable trade-off curve | 4–5 h | High: retuning + golden numbers |
| 7 | MPC over tank [S26][S27] | New planner around decide() | Better tank use with good forecasts | > 6 h | High; rule-based already close [S27] |
| 8 | Lease timer freeze on coordinator restart [S25] | #8 coordinator | No mass lease expiry after a crash | 1 h (in #8) | Low |

**Recommendation:** do 3 and 5 first (small, test-backed, already demanded by red team), then 1 and 4
(robustness the judges can see), then 2 if time remains. Leave 6 and 7 for the pitch's "next steps".
