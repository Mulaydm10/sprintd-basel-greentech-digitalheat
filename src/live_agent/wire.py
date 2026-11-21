"""Wire codecs shared by the node agent and the coordinator (contracts live_agent v2 / coordinator v1).

Pure functions, no I/O. The coordinator may import these so both sides encode attestations, keys,
envelopes and checkpoint bundles identically.
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from trust import Attestation, Envelope

_RAW_PRIV = dict(encoding=serialization.Encoding.Raw, format=serialization.PrivateFormat.Raw,
                 encryption_algorithm=serialization.NoEncryption())


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode(), validate=True)


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ attestation
def attestation_to_json(a: Attestation) -> dict[str, Any]:
    return {"node_id": a.node_id, "evidence": dict(a.evidence), "signature_b64": b64e(a.signature), "mock": True}


def attestation_from_json(d: dict[str, Any]) -> Attestation:
    return Attestation(str(d["node_id"]), dict(d["evidence"]), b64d(d["signature_b64"]))


# ------------------------------------------------------------------ job key (key_release)
def key_to_json(priv: X25519PrivateKey) -> dict[str, Any]:
    return {"key_b64": b64e(priv.private_bytes(**_RAW_PRIV)), "mock": True}


def key_from_json(d: dict[str, Any]) -> X25519PrivateKey:
    raw = b64d(d["key_b64"])
    if len(raw) != 32:
        raise ValueError(f"job key must be 32 bytes, got {len(raw)}")
    return X25519PrivateKey.from_private_bytes(raw)


# ------------------------------------------------------------------ envelope
def envelope_to_bytes(e: Envelope) -> bytes:
    return json.dumps({"ephemeral_pub_b64": b64e(e.ephemeral_pub), "nonce_b64": b64e(e.nonce),
                       "ciphertext_b64": b64e(e.ciphertext), "aad_b64": b64e(e.aad)},
                      sort_keys=True).encode()


def envelope_from_bytes(b: bytes) -> Envelope:
    d = json.loads(b)
    return Envelope(b64d(d["ephemeral_pub_b64"]), b64d(d["nonce_b64"]), b64d(d["ciphertext_b64"]),
                    b64d(d.get("aad_b64", "")))


# ------------------------------------------------------------------ checkpoint bundle (plaintext inside the envelope)
def bundle_to_bytes(checkpoint: dict[str, Any], out_log: bytes) -> bytes:
    """A resumable unit state: the runner's checkpoint plus its output log up to out_bytes."""
    n = int(checkpoint["out_bytes"])
    if len(out_log) < n:
        raise ValueError(f"output log has {len(out_log)} bytes, checkpoint committed {n}")
    return json.dumps({"checkpoint": checkpoint, "out_b64": b64e(out_log[:n])}, sort_keys=True).encode()


def bundle_from_bytes(b: bytes) -> tuple[dict[str, Any], bytes]:
    d = json.loads(b)
    ck, out = d["checkpoint"], b64d(d["out_b64"])
    if len(out) != int(ck["out_bytes"]):
        raise ValueError(f"bundle output is {len(out)} bytes, checkpoint says {ck['out_bytes']}")
    return ck, out
