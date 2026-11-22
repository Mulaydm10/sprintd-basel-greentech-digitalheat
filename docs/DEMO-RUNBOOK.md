# Demo runbook: final pitch (Sun 22 Nov)

All URLs are public (Tailscale Funnel on the Mac). Tokens live on the Mac under
`~/Dhruv/hackathons/sprintd-basel-greentech-digitalheat/runs/coordinator/tok/` (never printed, never committed).
Copy one to the clipboard from the Omen: `ssh macmini 'cat ~/Dhruv/hackathons/sprintd-basel-greentech-digitalheat/runs/coordinator/tok/<name>' | wl-copy`

| What | URL | Token |
|---|---|---|
| Website (all pages) | https://dhruvs-mac-mini.tailaf7ebe.ts.net:8443 | none |
| Big screen, wow #2 (phone fleet + QR) | …:8443/DigitalHeat%2004%20Live.dc.html (scroll to "Your phones. Our fleet.") | none |
| Phone client (wow #1, live transcription) | …:8443/phone-client.html | `client_client-demo` |
| Phone server / STOP (wow #1) | …:8443/phone-server.html | `admin` (controls) / `observer` (view) |
| Volunteer join (wow #2) | the QR on the big screen (`phone-join.html#code=…`) | none (event code is in the QR) |
| Coordinator API | https://dhruvs-mac-mini.tailaf7ebe.ts.net | per role |

## Before the pitch (10 min)
1. **Mac stack** (from the Omen): `ssh macmini 'cd ~/Dhruv/hackathons/sprintd-basel-greentech-digitalheat && tools/demo/mac_stack.sh restart'`
   → coordinator ok, public site 200, phone fleet "join open". (Processes count includes any test servers; ignore.)
2. **Omen**: `~/digitalheat-omen-agent.sh start` (batch node) and `~/digitalheat-omen-agent.sh gpu-start` (Whisper transcriber `omen-gpu`).
3. **Parth's HP** (`laptop-2`, ElevenLabs, disclosed as cloud): running from his terminal; check it's online on phone-server.html.
4. **Empty the phone fleet** (after rehearsals): `ssh macmini 'cd ~/Dhruv/hackathons/sprintd-basel-greentech-digitalheat && set -a && . runs/phones/env && set +a && curl -s -X POST -H "X-DH-Admin: $DH_PHONES_ADMIN" http://127.0.0.1:8720/api/phones/reset'`
5. **Smoke test**: `ssh macmini 'cd ~/Dhruv/hackathons/sprintd-basel-greentech-digitalheat && T=runs/coordinator/tok && PYTHONPATH=src .venv/bin/python -m tools.e2e --coordinator https://dhruvs-mac-mini.tailaf7ebe.ts.net --site https://dhruvs-mac-mini.tailaf7ebe.ts.net:8443 --client-token-file $T/client_client-demo --client2-token-file $T/client_client-macmini --observer-token-file $T/observer --host-token-file $T/host_node-mac --host-token-file $T/host_node-omen2 --admin-token-file $T/admin | tail -1'` → `9 pass`.

## Wow #1: live transcription, nothing lost (≈ 90 s)
1. Phone (client): phone-client.html → sign in → **Start** → allow the mic → speak. Shows "🔒 end-to-end encrypted · N recipient nodes · coordinator cannot read".
2. The transcript appears; the colour bar = the node (Omen first: local nodes are preferred, cloud last).
3. Second device: phone-server.html (admin) → **■ STOP omen-gpu**. Within ~5 s the transcript continues on the next node, with a "moved to …" divider; no segment lost.
4. Optional chain: STOP the next node too (Mac → Parth's HP → back). Then **▶ Resume** them.
5. **End** → "✓ chain intact · N linked · signatures ✓ · root ab12…".
Say: audio is encrypted on the phone; only the node holding the job can open its segment; the coordinator only stores
locked boxes; each segment is signed by the node and hash-linked, so nothing can be dropped or reordered unnoticed.
**Honest limits:** the transcribing node hears its segment (no secure hardware); Parth's node uses ElevenLabs (cloud).

## Wow #2: the room becomes a data centre (≈ 2 min)
1. Big screen: 04 Live, scroll to the fleet. The Mac core + laptops (Omen, Mac, Parth's HP) are already there.
2. "Scan the QR." Volunteers: read the caution screen → **I understand · join**. Every 4th joiner is a **client**, the others **servers** (cap 20).
3. Clients: **Submit a job**. A server phone starts heating (Dhruv's phone-heat-test: CPU + GPU), shows the job, client, step x/25.
4. When it feels warm: **■ STOP · my heat need is met** → the big screen shows the job jumping to another phone, "continues at step N · nothing lost".
5. Clients see "✓ completed · ran on 2 phones · path A → B".
Ask server volunteers: brightness to maximum, screen on, page open.

## Rehearse without people
`python -m tools.demo.phone_sim --site https://dhruvs-mac-mini.tailaf7ebe.ts.net:8443 --code <DH_EVENT_CODE from runs/phones/env> --phones 16 --jobs 3 --seconds 180`
→ prints `done == jobs`, `progress_lost: []`. Reset the fleet afterwards (step 4 above).

## If something breaks
- Public site down: `tools/demo/mac_stack.sh restart` on the Mac.
- A node missing in phone-server.html: restart it (Omen: `~/digitalheat-omen-agent.sh gpu-start`; Mac: stack restart).
- Fleet full / stale volunteers: reset the fleet (step 4). New event code: delete `runs/phones/env` and restart the stack.
- Backup: the 3D Year page + recorded runs; the E2E receipts are in the audit log.
