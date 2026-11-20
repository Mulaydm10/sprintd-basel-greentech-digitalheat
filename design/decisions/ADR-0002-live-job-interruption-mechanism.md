# ADR-0002 - How the live agent interrupts a real job

- Status: Proposed
- Date / deciders: 2026-11-21, TODO(Dhruv)
- Related: DEMO-0001, DEMO-0003, EXP-0001, T01, T04

## Context
Must-have: the SAME scheduler code pauses/resumes (or checkpoint/restarts) a real process on the heat signal. DEMO-0001 additionally needs migration to another machine, which a frozen process cannot do.

## Options
- A. SIGSTOP/SIGCONT (psutil `suspend`/`resume`): trivial, instant, same machine only; memory stays resident.
- B. Cooperative checkpoint-and-exit, restart from checkpoint (progress offset + partial outputs): works across machines, needed for migration; requires the job to be chunked.
- C. Both: A for short pauses on one node, B for migration/long pauses.

## Criteria
Reliability on stage, time to implement, enables DEMO-0001, honest measurement of energy while paused.

## Decision
Not yet taken. Leaning C (A first for DEMO-0003 at G1, B for DEMO-0001 at G2). Whoever accepts this updates `DEMO.md` steps and lands a green test in the same change.
