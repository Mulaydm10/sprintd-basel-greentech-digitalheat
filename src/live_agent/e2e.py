"""Node side of live-transcription E2E (contract live_transcribe.md v2): reference implementation matching phone-e2e.js.
P-256 ECDH -> HKDF-SHA256 (salt empty, info b"dh-e2e-v1", 32 B) -> AES-256-GCM, 12-byte IV, keys as SPKI DER base64."""
from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

INFO = b"dh-e2e-v1"
b64, unb64 = (lambda b: base64.b64encode(b).decode()), base64.b64decode


def new_pair() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def pub_b64(priv) -> str:
    return b64(priv.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))


def _key(priv, pub_b64_: str) -> bytes:
    pub = serialization.load_der_public_key(unb64(pub_b64_))
    shared = priv.exchange(ec.ECDH(), pub)
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=INFO).derive(shared)


def open_segment(priv, node_id: str, blob: bytes | str) -> bytes:
    """Unwrap my copy of the segment key and decrypt the WAV. KeyError if I'm not a recipient."""
    d = json.loads(blob)
    w = d["wraps"][node_id]
    k = AESGCM(_key(priv, w["eph"])).decrypt(unb64(w["iv"]), unb64(w["k"]), None)
    return AESGCM(k).decrypt(unb64(d["iv"]), unb64(d["ct"]), None)


def seal_text(client_pub_b64: str, text: str) -> dict:
    """Encrypt a transcript segment to the phone's job key: {eph, iv, ct}."""
    eph = new_pair()
    iv = os.urandom(12)
    ct = AESGCM(_key(eph, client_pub_b64)).encrypt(iv, text.encode(), None)
    return {"eph": pub_b64(eph), "iv": b64(iv), "ct": b64(ct)}


def seal_segment(wav: bytes, recipients: dict[str, str]) -> str:
    """Test helper: the phone's side in Python (recipients = {node_id: e2e_pub})."""
    k, iv = os.urandom(32), os.urandom(12)
    wraps = {}
    for nid, pub in recipients.items():
        eph, wiv = new_pair(), os.urandom(12)
        wraps[nid] = {"eph": pub_b64(eph), "iv": b64(wiv), "k": b64(AESGCM(_key(eph, pub)).encrypt(wiv, k, None))}
    return json.dumps({"v": 1, "iv": b64(iv), "ct": b64(AESGCM(k).encrypt(iv, wav, None)), "wraps": wraps})
