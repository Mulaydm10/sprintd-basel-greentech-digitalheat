# Hearthbeat: 5-minute pitch script (final, Sun 22 Nov, room 2.20, 10:20–10:28)

Two speakers work best: **A** talks, **B** drives the screens and phones. Times are cumulative.
Every number comes from `research/PITCH_NUMBERS.md` (row #), `runs/yearview`, `runs/fleetview` or `runs/experiment_tracker.md`.
Before you go on: run the pre-flight in `docs/DEMO-RUNBOOK.md` and **reset the phone fleet**.

---

## 0:00–0:30 · Hook (A, website 01 Overview)
> "Every server in this building is a heater that someone pays to cool. In Basel, a house needs **31,231 kWh** of heat a year.
> What if the computer in the basement *was* the heater, and it only worked when the house wanted the warmth?
> We're **Hearthbeat**: basement servers that heat the house, scheduled by what their heat is worth."

## 0:30–1:10 · The problem (A, 02 Problem)
- Heat is seasonal; compute is flat and has deadlines.
- "Follow the thermostat and you **miss 31% of paid deadlines** (row 5). Run always-on and you throw heat away; either way it costs **0.69–0.74 CHF per server-hour** to break even (rows 22, 11)."
> "So the real question isn't 'can a server heat a home'. It's **who decides, every hour, which job runs where**."

## 1:10–1:50 · Our scheduler (A, 03 Scheduler)
- "Every hour each house puts a **price on its heat**: cheap when the heat is wanted, expensive when it would be dumped. Jobs go to the cheapest heat first."
- "Jobs with spare time **wait** for cold hours: patience is our battery. Cheap filler work soaks up winter capacity. A job is accepted only if it can finish in time."
- "**One `decide()`** runs the simulated year *and* the real machines you're about to see."

## 1:50–2:50 · WOW #1: pull the plug, lose nothing (B on phone + big screen)
**B:** phone-client.html → **Start** → speaks into the phone.
> A: "This phone is a customer. It needs live transcription. Its audio is **encrypted on the phone**; our coordinator only ever holds locked boxes.
> Right now a gaming laptop, the Omen, is transcribing. It's the 'server in a basement'."

**B:** on phone-server.html → **■ STOP omen-gpu**.
> A: "We just pulled the plug. Watch the transcript…" *(it continues, with 'moved to …')*
> "…it moved to the Mac, and not one word was lost. Every segment is **signed by the node that did it and hash-linked** to the one before, so nothing can be dropped or reordered unnoticed. That's blockchain techniques, without a blockchain."

*(Optional, if time: STOP the Mac → Parth's laptop continues. Say: "that node uses a cloud speech engine; we disclose it.")*
**B:** **End** → "✓ chain intact · root …".

## 2:50–3:50 · WOW #2: the room becomes a data centre (big screen 04 Live, QR)
> A: "Now *you* are the fleet. Scan the code."
- Volunteers join; phones fly into the 3D view around the coordinator. Every 4th phone is a **client**, the rest **servers**.
> "Clients: tap **Submit a job**. Servers: your phone is now a basement server. It's working, and it's getting warm.
> When it's warm enough, when *your heat need is met*, tap **STOP**."
- Point at the screen: the job jumps to another phone and continues from the same step.
> "That's exactly what a house does when the tank is full: it hands the work to the next house that wants heat."

## 3:50–4:30 · It scales and it pays when… (A, 07 Year → 3D Basel map, 05 Economics)
- "We ran Basel 2025, hour by hour, through the same scheduler. For one house we'd buy **3 servers**: **45% of its heat, 0% missed deadlines** (yearview)."
- 3D map, play at 8×: "Across a city fleet of **100 houses**, same heat covered as the thermostat (~44%), but **0% missed vs 25.8%**, and **2.2× the net income** (fleetview; fleet assumed, weather and algorithm real)."
- Honest line: "At today's assumed price it does **not** pay off yet: paid work must sell for **≥ 0.53 CHF per server-hour** including hardware (row 44). We show exactly when it does."

## 4:30–5:00 · Close (A)
> "Measured, not invented: our Whisper workload runs at **35× real time on 9.2 W** (EXP-0001).
> Mocked, said out loud: the attestation is a mock; the fleet in the city map is assumed.
> **Hearthbeat**: the thermostat steers the valve, not the GPU. We schedule compute by the value of its heat, prove it on real machines, and tell you exactly when it pays."

---

## Q&A cheat sheet
- **Why not always-on?** Same heat, but it dumps ~9,910 kWh a year and needs 0.69 CHF/h (rows 13–22).
- **Is it secure?** Audio encrypted on the phone (P-256 ECDH + AES-GCM); only the node holding a segment can open it; the coordinator stores ciphertext only; segments signed (Ed25519) and hash-linked; Merkle receipt in a hash-chained audit log. **Limit:** the transcribing node hears its segment (no secure hardware); the cloud node uses ElevenLabs.
- **Real or simulated?** Real: scheduler, coordinator, leases, checkpoints, encryption, 3 machines + phones, Basel 2025 weather. Simulated: the house heat demand (case formula), the 100-house fleet. Assumed: prices, hardware cost.
- **Hot water / legionella?** Energy model only; a booster heats to 60 °C.
- **Reproduce?** README → `python -m tools.pitch`, `python -m tools.e2e`, `python -m tools.demo.live_sim`, `python -m tools.demo.phone_sim`.

## If a demo breaks
- Transcription stalls → keep talking, show the 3D map; `~/digitalheat-omen-agent.sh gpu-start`.
- Phones don't join → Wi-Fi: use mobile data; fleet full → reset (runbook step 4).
- Everything down → `tools/demo/mac_stack.sh restart` and the recorded video in the Drive folder.
