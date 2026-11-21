# contract: src/trust  (pure functions; no network)
- `seal(plaintext: bytes, recipient_pub) -> Envelope` / `open_(env, recipient_priv) -> bytes` — AES-256-GCM + X25519 key wrap (`cryptography`).
- `attest(node_id, evidence) -> Attestation` — **MOCK** (signed dict); label "mock" in every output.
- `KeyBroker.release(job_id, node_id, attestation, region) -> key | Denied(reason)` — denies if attestation invalid, region not allowed for the job's access_class, or node tampered.
- `AuditLog.append(event) -> entry` with `entry.prev_hash`; `AuditLog.verify() -> bool` detects any edit.
- `tamper(node_id)` marks node; subsequent `release` denied; `shred(customer_id)` drops keys.
