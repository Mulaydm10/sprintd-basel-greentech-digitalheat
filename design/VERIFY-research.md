# End-to-end verification against research (design-owned)

Every number we quote must be reproduced by the built pipeline. Automated: `tests/review/test_research_golden.py` (skips until each lane lands, then fails loudly).

| Claim (source) | Value | Check |
|---|---|---|
| Space heat, total, heating days, min T, peak (briefing) | 26,851 / 31,231 kWh, 206 d, −5.6 °C, 10.5 kW | house_model golden test |
| Hours above N servers (briefing) | 4,936 … 29 h | house_model golden test |
| Thermostat coverage/util/break-even N=1..10 (briefing) | 19.5→99.3%, 87→44%, 0.2261 | simulate_year golden test |
| Always-on dump & break-even (briefing) | N=4: 9,903 kWh, 0.2637 | simulate_year golden test |
| Patience is a battery (Run B) | 24 h −7%, 7 d −19.5% (ours −6.9/−16.6%) | simulate_year golden test |
| Hardware flips the conclusion (briefing) | N=4 0.446 vs 0.509 (CHF 8k ASSUMED) | add when hardware keys land |
| Exactly-once over interruptions (Run B C2) | 135 interruptions, 0 lost/repeated | #8 live test |
| Pause 0.66 ms / resume 0.06 ms (Run B C2) | | #8 measured, EXP row |
| Same decide() in sim and live (must-have 2) | | #8 imports scheduler.policy; grep test |
| Sovereignty: certified job never on public site | | tests/review fuzz (done) + #10 broker |
| Teammate claims (CHF 1.70/GPU-h, 34k EBIT, r=0.99) | unverified | scale layer only; cite as teammate model |
