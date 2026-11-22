# contract: live transcription (demo wow #1), v1 (2026-11-22)

Story: a client (phone) streams speech; server 1 (Omen, local Whisper GPU) transcribes it live; STOP on Omen →
the coordinator moves the job to server 2 (friend's laptop; ElevenLabs Scribe, **disclosed as cloud**) and the
transcript continues **without losing or repeating a segment**. Same coordinator, leases, events, trust as today.

## Job model
- New job type `live_transcription` (catalogue), access class **public** (so a cloud node is eligible), unbounded:
  it stays `running` until the client ends it. Its work = an ordered stream of **segments** (unit per segment).
- Segment = 4.0 s of 16 kHz mono PCM16 WAV (≤ 160 KB) + 0.5 s overlap prefix from the previous segment; id `seq` 0,1,2…
- A node holding the job's lease processes segments in order; each segment result = `{seq, text, words?:[{w,t0,t1}], node, backend, ms}`.

## Coordinator (P1 lane: src/coordinator + src/portal)  → macmini
1. `POST /v1/client/jobs {type:"live_transcription", access_class:"public", idempotency_key}` → `{job_id}` (no deadline/rounds).
2. `POST /v1/client/jobs/{id}/segments` (role client, own job) body = WAV bytes, header `X-Seq: n` → 201; idempotent per (job, seq);
   rejects seq gaps > 50, size > 256 KB, non-WAV. Stored encrypted (trust envelope) under the job.
3. `POST /v1/client/jobs/{id}/end` → no more segments; job finishes when all are transcribed.
4. Node side: the existing lease (`/v1/nodes/{id}/lease`) returns the job like any unit; while holding it the node calls
   `GET /v1/leases/{lease}/segments?after=<seq>` (long-poll ≤ 10 s) → next pending segments (decrypted key via key_release)
   and `POST /v1/leases/{lease}/segments/{seq}/result {text, words, backend, ms}` → exactly-once per seq (dup = 200 no-op,
   conflicting text after accept = 409). Also `context`: the last ~200 chars of accepted text, returned with each fetch
   (so the next node continues the sentence).
5. Lease lapse / kill / drain → pending + in-flight segments go back to the queue; the next eligible node gets the lease and
   resumes at the first un-accepted seq. **Target: ≤ 6 s from STOP to the first new segment accepted on the new node.**
6. Events: `transcript.segment {job, seq, text, node, backend}`, `job.moved {from,to,at_seq}`; client sees its own; ops sees all.
7. `GET /v1/client/jobs/{id}/transcript` → `{segments:[{seq,text,node,backend}], text}` (stitched, overlap-deduped).

## Node agent (src/live_agent)  → macmini
- `--backend whisper-local` (faster-whisper, model `--model small.en`, device cuda if available, int8) and
  `--backend elevenlabs` (Scribe REST, key from `ELEVENLABS_API_KEY` env / `--key-file`; never logged), both behind one
  `Transcriber.transcribe(wav_bytes, context) -> {text, words}`. Overlap dedupe by word timestamps (drop words with t1 ≤ 0.5 s).
- Registers with `eligible_classes` incl. public, and `backend` reported in heartbeat (shown on pages + trace card).
- Fake backend `echo` for tests (returns "seg <n>").

## Screens (design)
- 08 Client: "Live transcription" card: Start (mic via getUserMedia, AudioWorklet → 16 kHz PCM, 4 s + 0.5 s overlap),
  live transcript with a colour/margin mark per node + "moved to <node>" divider, End. Works on a phone (HTTPS).
- 10 Coordinator: big **STOP <node>** button (drain+kill) + live "who transcribes" trail.
- Installer for server 2 (Windows/macOS/Linux): one command, public URL, its own node token; no Tailscale.

## Tests
In-process coordinator + 2 agents with `echo`: stream 30 segments, kill agent A at seq 12 → agent B continues; every seq
accepted exactly once, in order, transcript complete; resume ≤ 6 s; client/ops events; auth (other client 404, node w/o lease 403).

## v2: end-to-end encryption, coordinator-blind (design, 2026-11-22)
Goal: the coordinator (and every node that does not hold a segment) can never read audio or transcript.
Crypto: ECDH **P-256** + HKDF-SHA256 + **AES-256-GCM** (WebCrypto on phones supports all three; Python `cryptography`).
1. **Node keys:** each transcriber node generates a P-256 keypair at start (private key never leaves the node), sends the
   public key (SPKI, base64) in register/heartbeat as `e2e_pub`. Coordinator exposes
   `GET /v1/client/jobs/{id}/recipients` → `[{node_id, e2e_pub, backend}]` = eligible, online transcriber nodes.
2. **Phone (client):** per job an ephemeral P-256 keypair (`client_pub` sent at job create, private key only in the tab).
   Per segment: random AES key K, `ct = AES-GCM(K, wav)`, and for EACH recipient `wrap_i = AES-GCM(HKDF(ECDH(eph_seg, node_i)), K)`
   with a per-segment ephemeral key. Upload `{ct, iv, eph_pub, wraps:{node_id: {iv, wrapped}}}` as JSON (≤ 400 KB) instead of WAV.
3. **Coordinator:** stores the blob opaquely (no key, cannot decrypt); hands it to the lease holder unchanged.
4. **Node:** unwraps its own `wraps[node_id]`, decrypts, transcribes, then encrypts the text to `client_pub`
   (`{eph_pub, iv, ct}`); the coordinator stores and serves that ciphertext only. The `text` field stays empty.
5. **Phone:** decrypts each transcript segment locally; the transcript exists in clear only on the phone.
6. A node not in `wraps` (joined later) cannot read old segments: the phone re-fetches recipients every 10 s and new
   segments include it. STOP → next node is already a recipient → handover unchanged.
7. Honest limits (on the trace card + pitch): the node transcribing a segment must see that segment (no TEE); the cloud
   node (ElevenLabs) sends its segments to the provider; metadata (timing, sizes, which node) is visible to the coordinator.
Tests: coordinator DB contains no plaintext audio/text (grep for known words); a non-recipient node gets a blob it cannot open;
handover across 3 nodes still exactly once; legacy WAV path stays for the batch/e2e tool behind `e2e: false`.
