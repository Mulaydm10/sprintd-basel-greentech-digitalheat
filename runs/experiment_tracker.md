# Experiment tracker

> Header/schema below is LOCKED. Rows are append-only. Never edit or delete a row.

| id | date | who | commit | what | config / assumptions.yaml hash | result (key numbers) | notes |
|---|---|---|---|---|---|---|---|
| EXP-0001 | 2026-11-21 08:33 CET | macmini (Dhruv ran sudo powermetrics) | 23744e2 | Whisper-small (mlx-community/whisper-small-mlx, Metal) on Mac mini M4, 104.4 s TTS clip × 3 after warm-up, 53 s idle baseline | cde8ebf65c88 | RTF 0.028 (2.96 s per clip, median); package power 9.2 W (idle 0.1 W); 27.4 J/clip → **0.26 Wh per audio-hour**; word recall 95% | Package CPU+GPU+ANE only (excludes DRAM/SSD/PSU). Per-run energy 19.6–33.7 J (3 s runs vs 1 s samples): median quoted. Scaled to 1 kW at equal efficiency per joule = ASSUMED (efficiency_vs_m4: 1.0). src/jobs/measurements/whisper_m4.json |
