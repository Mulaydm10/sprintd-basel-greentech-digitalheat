# Sources for REPORT.md (#24)

All accessed **2026-11-21** by parth-hp. **Status:** every source below was read through search-engine
result snippets/summaries, not full text, so each is **UNVERIFIED** in the sense of #24 until someone
opens the page and confirms the quoted point. Claims in REPORT.md cite these as `[S#]`.

**Full-text check (2026-11-21, second pass):** S1, S19, S23 and S30 were read in full text and are now
**VERIFIED** (notes in the table). S21 (Borg) and S22 (BOINC) were fetched but the PDFs came back as unreadable
binary, so they stay UNVERIFIED. All others remain snippet-level.

| ID | Source | URL | What it is cited for |
|---|---|---|---|
| S1 ✅ VERIFIED | Radovanović et al., *Carbon-Aware Computing for Datacenters* (Google CICS / VCC), arXiv 2106.11750 | https://arxiv.org/abs/2106.11750 | VERIFIED (arXiv HTML v1): VCC "artificially limits the cluster's hourly compute usage"; computed once per day for the next day; computation "decoupled from the real-time scheduling operations" but VCCs "directly impact the real-time admission of flexible workloads"; objective = weighted carbon + daily power peak; result 1–2 % power drop in highest-carbon hours (8 % in some clusters) |
| S2 | Hall, Micheli, Belgioioso, Radovanović, Dörfler, *Carbon-Aware Computing for Data Centers with Probabilistic Performance Guarantees*, arXiv 2410.21510 | https://arxiv.org/abs/2410.21510 | distributionally robust day-ahead planning + real-time placement |
| S3 | Carbon Aware SDK (Green Software Foundation, ex-Microsoft) docs and repo | https://github.com/microsoft/carbon-aware-sdk , https://carbon-aware-sdk.greensoftware.foundation/docs/tutorial-basics/carbon-aware-webapi | forecast-window API over WattTime / ElectricityMaps; window selection left to wrappers |
| S4 | DATE 2021, *Distributed grid computing manager covering waste heat reuse constraints* (Qarnot) | https://past.date-conference.com/proceedings-archive/2021/html/18001.html | heat-aware job scheduler in a grid manager |
| S5 | Data Center Knowledge, *Qarnot's home heating servers now plugged into data centers* | https://www.datacenterknowledge.com/servers/qarnot-s-home-heating-servers-now-plugged-into-data-centers | hybrid: peaks to DATA4 data centres, steady work to Q.rads |
| S6 | CORDIS, *Smart grid redirects computing power to heat homes* | https://cordis.europa.eu/article/id/182009-smart-grid-redirects-computing-power-to-heat-homes | Q.rads pull jobs when heat is needed; frequency reduction in summer |
| S7 | Qarnot architecture paper (core.ac.uk) | https://core.ac.uk/download/288124086.pdf | QNode/QBox/QMobo hierarchy; goals: task throughput and heating shortfall |
| S8 | East Devon District Council, Exmouth pool heated by Deep Green | https://eastdevon.gov.uk/news/2023/03/exmouth-swimming-pool-is-heated-by-a-uk-first-in-technology-heating-solutions/ | gas boiler only as backup; heat via exchanger |
| S9 | DCD, *UK data center startup offers to heat Britain's swimming pools* | https://datacenterdynamics.com/en/news/uk-data-center-startup-offers-to-heat-britains-swimming-pools-with-waste-heat | Deep Green model: operator pays power, host gets heat |
| S10 | Leafcloud, *Heat reuse technology* / *Leafsites* | https://leaf.cloud/resources/heat-reuse/ , https://leaf.cloud/leafsites/ | water-cooled servers in buildings with steady hot-water demand; separate loop |
| S11 | Leafcloud talk at CERN (2024) | https://indico.cern.ch/event/1332413/contributions/5773203/attachments/2819048/4922292/Leafcloud%202024.pdf | storage in core DCs, compute at Leafsites |
| S12 | MDPI Sensors, *Heating Homes with Servers: Workload Scheduling for Heat Reuse in Distributed Data Centers* | https://www.mdpi.com/1424-8220/21/8/2879 | thermal-aware scheduling as a constraint satisfaction problem (SLA + tenant heat) |
| S13 | Rais, Caron, Lefèvre, CCNC 2018 (computing water heaters) | https://perso.ens-lyon.fr/laurent.lefevre/pdf/CCNC2018_Rais_Caron_Lefevre.pdf | hierarchical scheduling for distributed water heaters |
| S14 | CNX Software, Heata | https://www.cnx-software.com/2023/02/15/install-a-server-in-your-house-get-free-hot-water/ | server on hot-water cylinder, daily free-hot-water cap, separate electricity meter |
| S15 | NL Times, Nerdalize bankruptcy | https://nltimes.nl/2019/01/02/startup-using-servers-heat-homes-files-bankruptcy | post-mortem: no follow-on funding after pilots |
| S16 | Cloud&Heat white paper (2025) | https://www.cloudandheat.com/wp-content/uploads/2025/07/2025-CloudandHeat-White-Paper-2-en-rev20.pdf | direct water cooling up to ~65 °C; modular systems where heat is needed |
| S17 | WEF, *4 innovative ways to harness waste data centre energy* | https://www.weforum.org/stories/energy-transition/harnessing-waste-energy-data-centres/ | WindCORES: DC in wind-turbine tower; tower as heat sink when no heat user |
| S18 | Kueue docs: Preemption, Fair Sharing | https://kueue.sigs.k8s.io/docs/concepts/preemption , https://kueue.sigs.k8s.io/docs/concepts/fair_sharing/ | Classic vs Fair Sharing preemption; proof against mutual preemption between two queues |
| S19 ✅ VERIFIED | Slurm preemption docs | https://slurm.schedmd.com/preempt.html | VERIFIED: GraceTime (default 0); PreemptExemptTime = "minimum run time of jobs before they are considered for preemption"; PreemptMode OFF/CANCEL/REQUEUE/SUSPEND/GANG |
| S20 | SchedMD ticket 15459 | https://support.schedmd.com/show_bug.cgi?id=15459 | preemption independent of backfill cycle |
| S21 | Verma et al., *Large-scale cluster management at Google with Borg*, EuroSys 2015 | https://research.google.com/pubs/archive/43438.pdf | quota checked at admission; priority bands; no preemption within production band to avoid cascades |
| S22 | Anderson, *BOINC: A Platform for Volunteer Computing*, arXiv 1903.01699 | https://arxiv.org/abs/1903.01699 | weighted round robin; EDF when a simulated miss is predicted; suspend work fetch when it would cause misses |
| S23 ✅ VERIFIED | HTCondor manual: special environment considerations (job lease) | https://htcondor.readthedocs.io/en/24.0/users-manual/special-environment-considerations.html | VERIFIED: "A default value equal to 40 minutes exists"; on expiry the startd "kills off the condor_starter daemon and user job"; too small → killed before the submitter recovers, too large → resource tied up |
| S24 | HTCondor `condor_vacate` man page | https://manpages.debian.org/buster/htcondor/condor_vacate.1.en.html | graceful vacate = checkpoint then leave; fast = hard kill |
| S25 | Burrows, *The Chubby lock service*, OSDI 2006 | https://research.google/pubs/pub27897/ | session leases + KeepAlive; lease timer frozen during master failover |
| S26 | Aschidamini et al., review of heat-pump control for flexibility, arXiv 2502.14111 | https://arxiv.org/abs/2502.14111 | MPC vs RL vs rule-based for heat pumps / thermal storage |
| S27 | Riederer, EnInnov 2026 (TU Graz) | https://www.tugraz.at/fileadmin/user_upload/Events/Eninnov/EnInnov2026/files/lf/662_LF_Riederer.pdf | MILP MPC vs rule-based; rule-based already efficient for simpler systems |
| S28 | Urgaonkar et al., Lyapunov optimisation of data-centre electricity cost, arXiv 1103.3099 | https://arxiv.org/abs/1103.3099 | drift-plus-penalty within O(1/V) of optimum with delay-tolerant work |
| S29 | arXiv 1501.03457 (utility-delay-reliability trade-off) | https://arxiv.org/abs/1501.03457 | [O(1/V), O(V)] cost-delay trade-off |
| S30 ✅ VERIFIED | Lechowicz et al., *The Online Pause and Resume Problem*, arXiv 2303.17551 (ACM TOMPECS) | https://arxiv.org/abs/2303.17551 | VERIFIED: find k lowest prices in a length-T sequence with switching cost β; DTPR-min uses threshold ℓ_i when idle and u_i = ℓ_i + 2β when running; "best achievable by any deterministic online algorithm" (Thm 8); PACMSIGMETRICS 7(3) Art. 45, Dec 2023, doi 10.1145/3626776 |
| S31 | CarbonClipper, arXiv 2408.07831 | https://arxiv.org/abs/2408.07831 | spatiotemporal online allocation with deadlines (multi-site extension) |
