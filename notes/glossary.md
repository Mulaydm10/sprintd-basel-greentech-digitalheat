# Glossary (use these exact terms; add new ones, never redefine)

| Term | Meaning |
|---|---|
| House | One simulated or real site: demand model + tank + N servers. In the live demo one physical machine = one house. |
| Heat signal | Per-house, per-hour kW of heat the house can use now (demand + tank headroom). The only input that makes a job run or pause. |
| Tank | 35 kWh lossless thermal buffer shared by heating and hot water. |
| Heat dumped | Server heat produced that the house could not use (tank full, no demand). Lower is better. |
| Heat covered | Share of the house's yearly heat demand supplied by server heat. |
| Utilisation | run-hours / (servers * 8760). |
| Server-hour sold | One server running one hour of paid compute. |
| Break-even CHF/server-h | (electricity cost - value of heat used) / server-hours sold. |
| Heat value | electricity price / 2.5 (per kWh of heat used). |
| Interruptible job | Can be paused or checkpointed without losing work; has deadline and access class. |
| Access class | `public` / `swiss-only` / `certified`: which sites may run the job. |
| Eligible site | A house whose class satisfies the job's access class. |
| Sovereignty cost | Extra dumped heat / missed deadlines / lost income caused by refusing ineligible sites. |
| Lane | A `src/` subpackage with a single owner at a time (see `AGENTS.md`). |
| Claim | A row in `STATE.md` (bus: a `claim/<n>` ref) declaring a lane+unit is being worked. |
| Main Agent / Main Human | Mulaydm10 / Dhruv: sole authority over LOCKED files. |
| Gate | A submission or pitch moment from `COMPETITION.md`, G0-G4 in `tasks/README.md`. |
