"""Phone-equivalent E2E live-transcription rehearsal (does exactly what phone-client.html + phone-e2e.js do).

    python tools/demo/live_sim.py --clip clip.wav [--coordinator http://127.0.0.1:8710]
        [--client-token-file runs/coordinator/tok/client_client-macmini] [--admin-token-file runs/coordinator/tok/admin]
        [--stop-sequence 'omen-gpu@11,mac-live@23,laptop-2@35,mac-live@47'] [--reference ref.txt | --reference-mlx]
        [--seg 4.0] [--overlap 1.0] [--json out.json]

1. Waits until no other live transcription job is running.
2. New job with a per-job P-256 client_pub; every segment (4 s + 1.0 s overlap, then the closing segment = last overlap +
   0.5 s silence, then /end) is sealed to the current /recipients (refreshed per segment) and streamed in REAL TIME.
3. --stop-sequence 'node@seq,...': entry i's node holds the job (every other transcriber node drained at start); when
   seq N is about to be sent, the next entry's node is undrained and entry i's node is drained + killed (the STOP).
   Nodes drained by the tool are undrained at the end (the operator's own drains are left as they were).
4. Decrypts every segment with the job key, stitches like the phone (overlap repeats across node switches), verifies
   the hash links, the Ed25519 node signatures and the Merkle receipt (root + every inclusion proof).
5. Verdict (JSON): every seq exactly once and in order, which node did each, handovers, chain/sig/root ok, and the
   stitched words vs a single-pass transcript (--reference text, or --reference-mlx: mlx-whisper small on this Mac).
Exit 0 = all checks pass (word diff is reported, not gated: Whisper itself varies between passes).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import time
import wave
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from live_agent import e2e  # noqa: E402  (the reference crypto, interop-checked against phone-e2e.js)

SR = 16000
TRANSCRIBERS = {"whisper-local", "elevenlabs", "echo"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def read_wav(p: Path) -> np.ndarray:
    with wave.open(str(p), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == SR, "need 16 kHz mono PCM16"
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").copy()


def to_wav(pcm: np.ndarray) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.astype("<i2").tobytes())
    return b.getvalue()


def segments(pcm: np.ndarray, seg_s: float, ov_s: float) -> list[bytes]:
    """The phone's cut: seq 0 = [0, 4 s); seq k = [4k - 1.0 s, 4(k+1)); then the closing segment (last 1.0 s + 0.5 s)."""
    n, hop, ov = len(pcm), int(seg_s * SR), int(ov_s * SR)
    out, k = [], 0
    while k * hop < n:
        out.append(to_wav(pcm[max(0, k * hop - (ov if k else 0)):(k + 1) * hop]))
        k += 1
    out.append(to_wav(np.concatenate([pcm[max(0, n - ov):], np.zeros(int(0.5 * SR), dtype=np.int16)])))
    return out


_norm = lambda w: re.sub(r"[^\w']", "", w.lower())  # noqa: E731  (phone: /[^\p{L}\p{N}']/gu)


class PhoneStitch:  # phone-client.html stitch(): drop the longest run (<= 8) of the last words repeated at the start
    def __init__(self):
        self.acc: list[str] = []

    def add(self, txt: str) -> list[str]:
        words, cut = txt.split(), 0
        for k in range(min(8, len(self.acc), len(words)), 0, -1):
            if [_norm(x) for x in self.acc[-k:]] == [_norm(x) for x in words[:k]] and (k > 1 or len(_norm(words[0])) >= 4):
                cut = k
                break
        kept = words[cut:]
        self.acc = (self.acc + kept)[-40:]
        return kept


def word_diff(rw: list[str], sw: list[str]) -> dict:
    """Word-level edit distance (Levenshtein, with backtrace). Not difflib: a clip that repeats itself makes difflib's
    longest-block heuristic align copy 1 against copy 2 (found on the first run: '49 %')."""
    n, m = len(rw), len(sw)
    d = np.zeros((n + 1, m + 1), dtype=np.int32)
    d[:, 0], d[0, :] = np.arange(n + 1), np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (rw[i - 1] != sw[j - 1]))
    i, j, ops = n, m, []
    while i or j:
        if i and j and d[i, j] == d[i - 1, j - 1] + (rw[i - 1] != sw[j - 1]):
            if rw[i - 1] != sw[j - 1]:
                ops.append(("sub", i - 1, rw[i - 1], sw[j - 1]))
            i, j = i - 1, j - 1
        elif i and d[i, j] == d[i - 1, j] + 1:
            ops.append(("lost", i - 1, rw[i - 1], "")); i -= 1
        else:
            ops.append(("extra", i, "", sw[j - 1])); j -= 1
    ops.reverse()
    groups: list[list] = []  # merge neighbouring edits into readable spans with 3 words of context
    for o in ops:
        if groups and o[1] - groups[-1][-1][1] <= 2:
            groups[-1].append(o)
        else:
            groups.append([o])
    spans = []
    for g in groups:
        a0 = max(0, g[0][1] - 3)
        spans.append(f"…{' '.join(rw[a0:g[0][1]])} [{' '.join(x[2] for x in g if x[2])} → {' '.join(x[3] for x in g if x[3])}]…")
    return {"reference_words": n, "stitched_words": m, "wer_pct": round(100 * int(d[n, m]) / max(1, n), 1),
            "lost": sum(o[0] == "lost" for o in ops), "extra": sum(o[0] == "extra" for o in ops),
            "substituted": sum(o[0] == "sub" for o in ops), "edits": spans[:25]}


def open_text(priv, enc: dict) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(e2e._key(priv, enc["eph"])).decrypt(base64.b64decode(enc["iv"]), base64.b64decode(enc["ct"]), None).decode()


def verify(job: str, segs: list[dict]) -> tuple[bool, int, int]:
    """phone-e2e.js verifyChain: links (raw digests) + Ed25519 signatures. -> (chain ok, sigs, sigs ok)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    prev, ok, n, good = hashlib.sha256(job.encode()).digest(), True, 0, 0
    for s in segs:
        lk = hashlib.sha256(prev + bytes.fromhex(s["blob_sha256"]) + bytes.fromhex(s["enc_sha256"]) + s["node"].encode()).hexdigest()
        ok &= lk == s["link"]
        prev = bytes.fromhex(s["link"])
        if s.get("sig") and s.get("sig_pub"):
            n += 1
            try:
                Ed25519PublicKey.from_public_bytes(base64.b64decode(s["sig_pub"])).verify(
                    base64.b64decode(s["sig"]), f"dh-seg-v1|{job}|{s['seq']}|{s['blob_sha256']}|{s['enc_sha256']}".encode())
                good += 1
            except Exception:  # noqa: BLE001
                pass
    return ok, n, good


def proof_ok(link: str, path: list[dict], root: str) -> bool:
    h = hashlib.sha256(b"\x00" + bytes.fromhex(link)).digest()
    for p in path:
        s = bytes.fromhex(p["hash"])
        h = hashlib.sha256(b"\x01" + (s + h if p["side"] == "L" else h + s)).digest()
    return h.hex() == root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True, type=Path)
    ap.add_argument("--coordinator", default="http://127.0.0.1:8710")
    ap.add_argument("--client-token-file", type=Path, default=Path("runs/coordinator/tok/client_client-macmini"))
    ap.add_argument("--admin-token-file", type=Path, default=Path("runs/coordinator/tok/admin"))
    ap.add_argument("--stop-sequence", default="")
    ap.add_argument("--reference", type=Path)
    ap.add_argument("--reference-mlx", action="store_true")
    ap.add_argument("--seg", type=float, default=4.0)
    ap.add_argument("--overlap", type=float, default=1.0)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()

    cli = httpx.Client(base_url=a.coordinator, timeout=30, headers={"Authorization": "Bearer " + a.client_token_file.read_text().strip()})
    adm = httpx.Client(base_url=a.coordinator, timeout=30, headers={"Authorization": "Bearer " + a.admin_token_file.read_text().strip()})
    plan = [(x.split("@")[0].strip(), int(x.split("@")[1])) for x in a.stop_sequence.split(",") if x.strip()]

    def nodes():
        return {n["node_id"]: n for n in adm.get("/v1/ops/nodes", params={"limit": 200}).json()["items"]}

    def live_running():
        js = adm.get("/v1/ops/jobs", params={"limit": 50}).json()["items"]
        return [j["job_id"] for j in js if j["type"] == "live_transcription" and j["status"] in ("running", "queued", "admitted")]

    t0 = time.time()
    while (busy := live_running()) and time.time() - t0 < 600:
        log("waiting: another live job is running", busy)
        time.sleep(5)
    if busy:
        log("gave up: a live job is still running", busy)
        return 2

    pcm = read_wav(a.clip)
    segs = segments(pcm, a.seg, a.overlap)
    drained_by_me: set[str] = set()
    if plan:  # only entry 0's node may take the job: drain every other online node (they stay recipients)
        for nid, n in nodes().items():
            if n["state"] == "online" and not n["drained"] and nid != plan[0][0]:
                adm.post(f"/v1/ops/nodes/{nid}/drain"); drained_by_me.add(nid)
        log("plan", plan, "| drained for the run:", sorted(drained_by_me))

    priv = e2e.new_pair()
    r = cli.post("/v1/client/jobs", json={"type": "live_transcription", "access_class": "public",
                                         "idempotency_key": f"live-sim-{int(time.time() * 1000)}", "client_pub": e2e.pub_b64(priv)})
    r.raise_for_status()
    job = r.json()["job_id"]
    log("job", job, "e2e", r.json().get("e2e"), "| segments", len(segs), f"({len(pcm) / SR:.1f} s audio)")
    stops, pi, start = [], 0, time.time()
    try:
        for seq, wav in enumerate(segs):
            if pi < len(plan) and seq == plan[pi][1]:
                cur = plan[pi][0]
                nxt = plan[pi + 1][0] if pi + 1 < len(plan) else None
                for nid in ([nxt] if nxt else sorted(drained_by_me)):  # the next holder is ready before the STOP
                    adm.post(f"/v1/ops/nodes/{nid}/undrain"); drained_by_me.discard(nid)
                adm.post(f"/v1/ops/nodes/{cur}/drain"); kr = adm.post(f"/v1/ops/nodes/{cur}/kill").json()
                drained_by_me.add(cur)
                stops.append({"seq": seq, "stopped": cur, "next": nxt, "revoked": kr.get("revoked_lease")})
                log(f"STOP {cur} at seq {seq} -> {nxt or 'any'} (revoked {kr.get('revoked_lease')})")
                pi += 1
            rc = cli.get(f"/v1/client/jobs/{job}/recipients").json()["recipients"]
            blob = e2e.seal_segment(wav, {x["node_id"]: x["e2e_pub"] for x in rc})
            up = cli.post(f"/v1/client/jobs/{job}/segments", content=blob.encode(),
                          headers={"Content-Type": "application/json", "X-Seq": str(seq)})
            if up.status_code not in (200, 201):
                log("upload", seq, up.status_code, up.text[:200])
            if seq < len(segs) - 2:
                time.sleep(max(0.0, start + (seq + 1) * a.seg - time.time()))  # real time, like the microphone
        cli.post(f"/v1/client/jobs/{job}/end").raise_for_status()
        t_end, t = time.time(), {}
        while time.time() - t_end < 120:
            t = cli.get(f"/v1/client/jobs/{job}/transcript").json()
            if t.get("ended") and t.get("pending") == 0 and t.get("root"):
                time.sleep(3)  # the final-tail flush may re-seal the last segment right after
                t = cli.get(f"/v1/client/jobs/{job}/transcript").json()
                break
            time.sleep(1)
    finally:
        for nid in sorted(drained_by_me):
            adm.post(f"/v1/ops/nodes/{nid}/undrain")

    got = t.get("segments", [])
    seqs = [s["seq"] for s in got]
    st, words, per = PhoneStitch(), [], []
    for s in got:
        raw = open_text(priv, s["enc"]) if s.get("enc") else s.get("text", "")
        kept = st.add(raw)
        words += kept
        per.append({"seq": s["seq"], "node": s["node"], "text": raw, "phone_cut": len(raw.split()) - len(kept)})
    chain, nsig, gsig = verify(job, got) if got else (False, 0, 0)
    rc = cli.get(f"/v1/client/jobs/{job}/transcript/receipt")
    rcj = rc.json() if rc.status_code == 200 else {}
    root_ok = bool(rcj) and rcj.get("root") == t.get("root") and all(proof_ok(p["link"], p["path"], rcj["root"]) for p in rcj["proofs"])
    by_node, hand = [], 0
    for s in got:
        if not by_node or by_node[-1][0] != s["node"]:
            by_node.append([s["node"], s["seq"], s["seq"]]); hand += len(by_node) > 1
        by_node[-1][2] = s["seq"]
    ref = None
    if a.reference:
        ref = a.reference.read_text()
    elif a.reference_mlx:
        import mlx_whisper
        ref = mlx_whisper.transcribe(pcm.astype(np.float32) / 32768.0, path_or_hf_repo="mlx-community/whisper-small-mlx",
                                     language="en")["text"]
    diff = None
    if ref is not None:
        diff = word_diff([_norm(x) for x in ref.split() if _norm(x)], [_norm(x) for x in words if _norm(x)])
    v = {"job": job, "segments_sent": len(segs), "seqs_ok": seqs == list(range(len(segs))),
         "missing": sorted(set(range(len(segs))) - set(seqs)), "duplicates": len(seqs) - len(set(seqs)),
         "in_order": seqs == sorted(seqs), "ended": t.get("ended"), "by_node": by_node, "handovers": hand,
         "stops": stops, "chain_ok": chain, "signatures": f"{gsig}/{nsig}", "root": (t.get("root") or "")[:16],
         "receipt_ok": root_ok, "coordinator_text_empty": all(not s.get("text") for s in got), "words": diff,
         "transcript": " ".join(words), "per_segment": per}
    print(json.dumps(v, indent=1))
    if a.json:
        a.json.write_text(json.dumps(v, indent=1))
    passed = v["seqs_ok"] and v["duplicates"] == 0 and chain and gsig == nsig and root_ok and v["coordinator_text_empty"]
    log("VERDICT", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
