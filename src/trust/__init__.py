"""Trust layer: envelope encryption, MOCK attestation, key broker, hash-chained audit log.

Contract: contracts/src/trust.md. Pure functions and in-memory objects, no network, no I/O.

Attestation here is a MOCK: a dict signed with a fixed demo Ed25519 key. It shows the protocol
shape (evidence -> verifier -> key release), not real hardware trust. Every Attestation, release
result and audit entry carries ``mock=True`` / ``"attestation": "mock"`` so nobody mistakes it.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Union

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

__all__ = [
    "ACCESS_CLASSES", "Envelope", "Attestation", "ReleasedKey", "Denied", "AuditEntry", "AuditLog",
    "KeyBroker", "PublishedHead", "generate_keypair", "seal", "open_", "attest", "region_allowed",
]

ACCESS_CLASSES = ("public", "swiss-only", "certified")
_HKDF_INFO = b"digitalheat-trust-envelope-v1"
_RAW = dict(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)


# ---------------------------------------------------------------- envelopes (AES-256-GCM + X25519)
@dataclass(frozen=True)
class Envelope:
    ephemeral_pub: bytes  # sender's one-time X25519 public key (32 B)
    nonce: bytes          # AES-GCM nonce (12 B)
    ciphertext: bytes     # includes the 16 B GCM tag
    aad: bytes = b""      # authenticated, not encrypted (e.g. job id)


def generate_keypair() -> tuple[X25519PrivateKey, X25519PublicKey]:
    priv = X25519PrivateKey.generate()
    return priv, priv.public_key()


def _wrap_key(shared: bytes, ephemeral_pub: bytes, recipient_pub: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=ephemeral_pub + recipient_pub,
                info=_HKDF_INFO).derive(shared)


def seal(plaintext: bytes, recipient_pub: X25519PublicKey, aad: bytes = b"") -> Envelope:
    """Encrypt to ``recipient_pub``: ephemeral X25519 agreement -> HKDF-SHA256 -> AES-256-GCM."""
    eph = X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(**_RAW)
    key = _wrap_key(eph.exchange(recipient_pub), eph_pub, recipient_pub.public_bytes(**_RAW))
    nonce = os.urandom(12)
    return Envelope(eph_pub, nonce, AESGCM(key).encrypt(nonce, plaintext, aad), aad)


def open_(env: Envelope, recipient_priv: X25519PrivateKey) -> bytes:
    """Decrypt an Envelope. Raises ``cryptography.exceptions.InvalidTag`` on a wrong key or tampering."""
    eph_pub = X25519PublicKey.from_public_bytes(env.ephemeral_pub)
    key = _wrap_key(recipient_priv.exchange(eph_pub), env.ephemeral_pub,
                    recipient_priv.public_key().public_bytes(**_RAW))
    return AESGCM(key).decrypt(env.nonce, env.ciphertext, env.aad)


# ---------------------------------------------------------------- MOCK attestation
# Fixed demo key so attestations are reproducible across processes. NOT a secret, NOT real trust.
_MOCK_SIGNER = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"digitalheat-mock-attestation").digest())
MOCK_VERIFIER_PUB = _MOCK_SIGNER.public_key()


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


@dataclass(frozen=True)
class Attestation:
    node_id: str
    evidence: Mapping[str, Any]  # e.g. {"measurement": "...", "certified": True, "region": "CH-BL"}
    signature: bytes
    mock: bool = True

    def payload(self) -> bytes:
        return _canon({"node_id": self.node_id, "evidence": dict(self.evidence), "attestation": "mock"})

    def is_valid(self) -> bool:
        try:
            MOCK_VERIFIER_PUB.verify(self.signature, self.payload())
            return True
        except InvalidSignature:
            return False


def attest(node_id: str, evidence: Mapping[str, Any]) -> Attestation:
    """MOCK attestation: sign ``(node_id, evidence)`` with the demo key. Label: mock."""
    unsigned = Attestation(node_id, dict(evidence), b"")
    return Attestation(node_id, dict(evidence), _MOCK_SIGNER.sign(unsigned.payload()))


# ---------------------------------------------------------------- audit log (hash chain)
GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    index: int
    event: Mapping[str, Any]
    prev_hash: str
    hash: str


def _entry_hash(index: int, event: Mapping[str, Any], prev_hash: str) -> str:
    return hashlib.sha256(_canon({"i": index, "e": dict(event), "p": prev_hash})).hexdigest()


class AuditLog:
    """Append-only, hash-chained log. ``verify()`` is False after any edit, insertion or deletion."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def append(self, event: Mapping[str, Any]) -> AuditEntry:
        prev = self.entries[-1].hash if self.entries else GENESIS
        i = len(self.entries)
        entry = AuditEntry(i, dict(event), prev, _entry_hash(i, event, prev))
        self.entries.append(entry)
        return entry

    def verify(self, expected_head: str | None = None, expected_len: int | None = None) -> bool:
        """Chain integrity, optionally anchored to a previously published head.

        A hash chain alone cannot see its newest entries being dropped. With an anchor
        (``expected_len`` entries ending in ``expected_head``, e.g. from ``KeyBroker.published_head()``)
        the log must still contain that prefix: truncation below the anchor fails, appends after it pass.
        """
        prev = GENESIS
        for i, e in enumerate(self.entries):
            if e.index != i or e.prev_hash != prev or e.hash != _entry_hash(i, e.event, prev):
                return False
            prev = e.hash
        if expected_len is not None:
            if expected_len < 0 or len(self.entries) < expected_len:
                return False
            anchor = self.entries[expected_len - 1].hash if expected_len else GENESIS
            if expected_head is not None and anchor != expected_head:
                return False
        elif expected_head is not None:
            if expected_head != GENESIS and all(e.hash != expected_head for e in self.entries):
                return False
        return True

    @property
    def head(self) -> str:
        return self.entries[-1].hash if self.entries else GENESIS


# ---------------------------------------------------------------- key broker
def region_allowed(access_class: str, region: str, certified: bool) -> bool:
    """public: anywhere; swiss-only: region 'CH-*'; certified: 'CH-*' AND a certified node."""
    if access_class == "public":
        return True
    swiss = region.upper().startswith("CH-")
    if access_class == "swiss-only":
        return swiss
    if access_class == "certified":
        return swiss and certified
    raise ValueError(f"unknown access_class {access_class!r}; expected one of {ACCESS_CLASSES}")


@dataclass(frozen=True)
class ReleasedKey:
    job_id: str
    node_id: str
    key: X25519PrivateKey  # opens envelopes sealed to the job's public key
    mock: bool = True


@dataclass(frozen=True)
class Denied:
    reason: str  # bad_attestation | region_mismatch | region_not_allowed | node_tampered | unknown_job | shredded
    job_id: str
    node_id: str
    mock: bool = True


@dataclass
class _Job:
    customer_id: str
    access_class: str
    priv: X25519PrivateKey | None


@dataclass(frozen=True)
class PublishedHead:
    """A signed anchor for the audit log: ``length`` entries ending in ``head``. MOCK signature
    (demo Ed25519 key); in production it would go to a store the operator cannot rewrite."""

    length: int
    head: str
    signature: bytes
    mock: bool = True

    def payload(self) -> bytes:
        return _canon({"length": self.length, "head": self.head, "anchor": "mock"})

    def is_valid(self) -> bool:
        try:
            MOCK_VERIFIER_PUB.verify(self.signature, self.payload())
            return True
        except InvalidSignature:
            return False


def _publish(log: AuditLog) -> PublishedHead:
    unsigned = PublishedHead(len(log.entries), log.head, b"")
    return PublishedHead(unsigned.length, unsigned.head, _MOCK_SIGNER.sign(unsigned.payload()))


@dataclass
class KeyBroker:
    """Holds one X25519 key per job. Customers seal inputs to ``job_public_key``; nodes get the
    private key only via ``release``. Every decision is written to ``audit``."""

    expected_measurements: frozenset[str] = frozenset({"digitalheat-node-image-v1"})
    audit: AuditLog = field(default_factory=AuditLog)
    _jobs: dict[str, _Job] = field(default_factory=dict)
    _tampered: set[str] = field(default_factory=set)
    _published: PublishedHead | None = None

    def _log(self, event: Mapping[str, Any]) -> None:
        """Append to the audit log and publish the new signed head (anchor against truncation)."""
        self.audit.append(event)
        self._published = _publish(self.audit)

    def published_head(self) -> PublishedHead:
        """The last head the broker signed. Compare a log against it with ``verify_audit``."""
        return self._published if self._published is not None else _publish(self.audit)

    def verify_audit(self, anchor: PublishedHead | None = None) -> bool:
        """Chain intact AND still contains the (signed) published head: catches tail truncation."""
        a = anchor or self.published_head()
        return a.is_valid() and self.audit.verify(expected_head=a.head, expected_len=a.length)

    def register_job(self, job_id: str, customer_id: str, access_class: str) -> X25519PublicKey:
        if access_class not in ACCESS_CLASSES:
            raise ValueError(f"unknown access_class {access_class!r}")
        priv = X25519PrivateKey.generate()
        self._jobs[job_id] = _Job(customer_id, access_class, priv)
        self._log({"type": "register", "job": job_id, "customer": customer_id, "class": access_class})
        return priv.public_key()

    def job_public_key(self, job_id: str) -> X25519PublicKey:
        job = self._jobs[job_id]
        if job.priv is None:
            raise KeyError(f"job {job_id} was shredded")
        return job.priv.public_key()

    def release(self, job_id: str, node_id: str, attestation: Attestation,
                region: str) -> Union[ReleasedKey, Denied]:
        job = self._jobs.get(job_id)
        reason = None
        if job is None:
            reason = "unknown_job"
        elif job.priv is None:
            reason = "shredded"
        elif node_id in self._tampered:
            reason = "node_tampered"
        elif (attestation.node_id != node_id or not attestation.is_valid()
              or attestation.evidence.get("measurement") not in self.expected_measurements):
            reason = "bad_attestation"
        elif attestation.evidence.get("region") != region:
            reason = "region_mismatch"  # the request's region must equal the attested region
        elif not region_allowed(job.access_class, attestation.evidence["region"],
                                bool(attestation.evidence.get("certified"))):
            reason = "region_not_allowed"
        event = {"type": "release" if reason is None else "deny", "job": job_id, "node": node_id,
                 "region": region, "attestation": "mock",
                 "evidence_sha256": hashlib.sha256(attestation.payload()).hexdigest()}
        if reason is not None:
            event["reason"] = reason
            self._log(event)
            return Denied(reason, job_id, node_id)
        self._log(event)
        return ReleasedKey(job_id, node_id, job.priv)

    def tamper(self, node_id: str) -> None:
        """Mark a node as tampered (enclosure opened / moved). All later releases to it are denied."""
        self._tampered.add(node_id)
        self._log({"type": "tamper", "node": node_id})

    def is_tampered(self, node_id: str) -> bool:
        return node_id in self._tampered

    def shred(self, customer_id: str) -> int:
        """Crypto-shred: drop every job key of ``customer_id``. Envelopes sealed to those jobs can
        no longer be opened through the broker. Returns the number of keys dropped."""
        n = 0
        for job in self._jobs.values():
            if job.customer_id == customer_id and job.priv is not None:
                job.priv = None
                n += 1
        self._log({"type": "shred", "customer": customer_id, "keys_dropped": n})
        return n


# Re-exported so callers can catch a failed open without importing cryptography themselves.
InvalidEnvelope = InvalidTag
