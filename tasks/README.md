> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# Tasks - deadline-ordered work list

Times and gates are defined in `COMPETITION.md` (CET). This index sequences the existing work packages
`tasks/01_jobs_and_energy` (T01), `02_scheduler` (T02), `03_yearly_balance` (T03), `04_live_demo` (T04).
Their READMEs are unchanged and LOCKED; their duplicated "Context" blocks are copies, and `COMPETITION.md` wins on any conflict.
Claims go in `STATE.md`; lanes in `AGENTS.md`. Rubric proof for each item: `notes/judging_alignment.md`.

## Gate G0 - DRAFT submission, Sat 21 Nov 15:00-15:30 CET (first gate)
Goal: a reproducible, honest first version, not the wow demo.
| # | Item | Task / lane | Done when |
|---|---|---|---|
| G0-1 | Resolve price (`Q-0002`), fetch weather into `data/`, record sources | T03 `common`/data | `chf_per_kwh` set with source; weather file present locally |
| G0-2 | House model reproduces ~27,000 kWh / 206 days (verified 26,851) | T03 `house_model` | test with tolerance green |
| G0-3 | >=2 job types in catalogue; one measured for real, scaled to 1 kW; jobs/day with source | T01 `jobs` | `EXP-0001` row + catalogue values from it |
| G0-4 | Scheduler v1 (heat + tank + deadline) and `simulate_year` prints the yearly balance incl. break-even and "does NOT pay off" case | T02 `scheduler`, T03 `simulate_year` | one command prints all required metrics |
| G0-5 | Draft package staged per `COMPETITION.md` submission format (`Q-0003`) | `submissions/` | commit hash recorded |

## Gate G1 - mentors leave, Sat 21 Nov 20:00 CET
Ask mentors the open rule questions first (`Q-0003`, `Q-0004`: submission format, pre-built code/AI-code rules).
| # | Item | Task / lane |
|---|---|---|
| G1-1 | Live agent: signal in, pause/resume of a real process (DEMO-0003) using the SAME scheduler | T04 `live_agent` + T01 `jobs` |
| G1-2 | Dashboard v1: day replay (Jan/Jul), yearly table, assumptions page (DEMO-0002) | T04 `dashboard` |

## Gate G2 - Sat night: wow + rehearsal
| # | Item | Task / lane |
|---|---|---|
| G2-1 | Access classes + eligibility in scheduler; refuse ineligible; cost-of-rule metric | T02 + T04 |
| G2-2 | Checkpoint / migrate / resume across machines (DEMO-0001) | T01 + T04 |
| G2-3 | Full 5-min rehearsal of `DEMO.md`; log known-broken edges and reset time | all |

## Gate G3 - FINAL submission, Sun 22 Nov 08:30 CET (hard)
Team convention (not an event rule): feature freeze ~1.5 h before; only fixes after that.
| # | Item | Done when |
|---|---|---|
| G3-1 | Every number in the pitch regenerated from the final commit; `docs/ASSUMPTIONS.md` matches `data/assumptions.yaml` | tracker rows + commit hash |
| G3-2 | Submit on the sprintd platform; staged copy in `submissions/` | confirmation recorded in `workflow.md` |

## Gate G4 - Sun 09:00-11:30 CET pitch (slot TODO), 12:00 finalists, 13:00-14:45 Grand Finale
Pitch from `DEMO.md`. Stretch ("Prepper": solar + compute + storage) only if G0-G3 are green.
