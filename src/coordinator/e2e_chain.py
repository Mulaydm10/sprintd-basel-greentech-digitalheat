"""Live transcription v2 / v2.1 helpers (contracts/src/live_transcribe.md): pure functions, no I/O.

v2   the coordinator only VALIDATES shapes (an E2E blob, a P-256 SPKI key); it never holds a key that opens a segment.
v2.1 signed work + hash-linked segments + a Merkle receipt (blockchain techniques, no chain):
  enc_sha256  = sha256(canonical JSON of the node's `enc` {eph, iv, ct})  (legacy clear text: sha256(utf8 text))
  m           = "dh-seg-v1|" + job + "|" + seq + "|" + blob_sha256 + "|" + enc_sha256   (Ed25519, raw 32-byte key)
  link_-1     = sha256(job_id);  link_n = sha256(link_{n-1} || blob_sha256 || enc_sha256 || utf8(node))  (raw digests)
  Merkle      leaf = sha256(0x00 || link), node = sha256(0x01 || l || r), an odd last node is promoted unchanged.
These match src/dashboard/static/site/phone-e2e.js (verifyChain) byte for byte.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

E2E_MAX = 400 * 1024  # contract: JSON blob <= 400 KB
B64_MAX = 600 * 1024


def _b64(s: Any, max_len: int = B64_MAX) -> bytes:
    if not isinstance(s, str) or not s or len(s) > max_len:
        raise ValueError("not a base64 string")
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("bad base64") from e


def is_e2e(body: bytes) -> bool:
    return body[:1] == b"{"


def check_blob(body: bytes) -> list[str]:
    """Validate an E2E segment blob's SHAPE only -> its recipients (node ids). ValueError on anything malformed."""
    if len(body) > E2E_MAX:
        raise ValueError(f"E2E segment larger than {E2E_MAX} bytes")
    try:
        d = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError("E2E segment is not JSON") from e
    if not isinstance(d, dict) or d.get("v") != 1:
        raise ValueError("E2E segment: v must be 1")
    if len(_b64(d.get("iv"), 64)) != 12:
        raise ValueError("E2E segment: iv must be 12 bytes")
    _b64(d.get("ct"))
    wraps = d.get("wraps")
    if not isinstance(wraps, dict) or not 1 <= len(wraps) <= 32:
        raise ValueError("E2E segment: wraps must name 1..32 recipients")
    for nid, w in wraps.items():
        if not isinstance(nid, str) or not 1 <= len(nid) <= 64 or not isinstance(w, dict):
            raise ValueError("E2E segment: bad wrap")
        _b64(w.get("eph"), 400); _b64(w.get("k"), 200)
        if len(_b64(w.get("iv"), 64)) != 12:
            raise ValueError("E2E segment: wrap iv must be 12 bytes")
    return sorted(wraps)


def valid_p256(pub_b64: Any) -> bool:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        k = serialization.load_der_public_key(_b64(pub_b64, 400))
        return isinstance(k, ec.EllipticCurvePublicKey) and isinstance(k.curve, ec.SECP256R1)
    except Exception:  # noqa: BLE001
        return False


def valid_ed25519(pub_b64: Any) -> bool:
    try:
        return len(_b64(pub_b64, 100)) == 32
    except ValueError:
        return False


def canon_enc(enc: dict) -> str:
    return json.dumps({k: enc[k] for k in ("eph", "iv", "ct")}, sort_keys=True, separators=(",", ":"))


def check_enc(enc: Any) -> dict:
    if not isinstance(enc, dict) or set(enc) != {"eph", "iv", "ct"}:
        raise ValueError("enc must be {eph, iv, ct}")
    _b64(enc["eph"], 400); _b64(enc["ct"], 40_000)
    if len(_b64(enc["iv"], 64)) != 12:
        raise ValueError("enc.iv must be 12 bytes")
    return enc


def enc_sha256(enc: dict | None, text: str = "") -> str:
    return hashlib.sha256((canon_enc(enc) if enc else text or "").encode()).hexdigest()


def seg_message(job: str, seq: int, blob_sha: str, enc_sha: str) -> bytes:
    return f"dh-seg-v1|{job}|{seq}|{blob_sha}|{enc_sha}".encode()


def verify_sig(sig_pub_b64: str, sig_b64: Any, msg: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(_b64(sig_pub_b64, 100)).verify(_b64(sig_b64, 200), msg)
        return True
    except Exception:  # noqa: BLE001
        return False


def link(prev_hex: str | None, job: str, blob_sha: str, enc_sha: str, node: str) -> str:
    prev = hashlib.sha256(job.encode()).digest() if prev_hex is None else bytes.fromhex(prev_hex)
    return hashlib.sha256(prev + bytes.fromhex(blob_sha) + bytes.fromhex(enc_sha) + node.encode()).hexdigest()


def _h(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def merkle(links: list[str]) -> tuple[str | None, list[list[dict]]]:
    """-> (root hex, per-leaf inclusion proof [{side: 'L'|'R', hash}]) ; side = where the sibling sits."""
    if not links:
        return None, []
    level = [_h(b"\x00" + bytes.fromhex(x)) for x in links]
    idx = list(range(len(level)))  # position of each leaf in the current level
    proofs: list[list[dict]] = [[] for _ in links]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            nxt.append(_h(b"\x01" + level[i] + level[i + 1]) if i + 1 < len(level) else level[i])
        for leaf, pos in enumerate(idx):
            sib = pos ^ 1
            if sib < len(level):
                proofs[leaf].append({"side": "L" if sib < pos else "R", "hash": level[sib].hex()})
            idx[leaf] = pos // 2
        level = nxt
    return level[0].hex(), proofs


def verify_proof(link_hex: str, proof: list[dict], root: str) -> bool:
    h = _h(b"\x00" + bytes.fromhex(link_hex))
    for p in proof:
        s = bytes.fromhex(p["hash"])
        h = _h(b"\x01" + s + h) if p["side"] == "L" else _h(b"\x01" + h + s)
    return h.hex() == root
