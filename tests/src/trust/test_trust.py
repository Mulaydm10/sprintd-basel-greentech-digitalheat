"""Tests for src/trust (contract: contracts/src/trust.md). No network, no model downloads."""
from dataclasses import replace

import pytest

from trust import (
    AuditLog, Denied, InvalidEnvelope, KeyBroker, ReleasedKey, attest, generate_keypair, open_,
    region_allowed, seal,
)

GOOD = {"measurement": "digitalheat-node-image-v1", "certified": False}
CERT = {"measurement": "digitalheat-node-image-v1", "certified": True}


def test_seal_open_roundtrip_and_aad():
    priv, pub = generate_keypair()
    env = seal(b"court file 42", pub, aad=b"job-1")
    assert env.ciphertext != b"court file 42"
    assert open_(env, priv) == b"court file 42"


def test_open_with_wrong_key_or_tampered_ciphertext_fails():
    priv, pub = generate_keypair()
    other, _ = generate_keypair()
    env = seal(b"secret", pub)
    with pytest.raises(InvalidEnvelope):
        open_(env, other)
    flipped = replace(env, ciphertext=bytes([env.ciphertext[0] ^ 1]) + env.ciphertext[1:])
    with pytest.raises(InvalidEnvelope):
        open_(flipped, priv)
    with pytest.raises(InvalidEnvelope):
        open_(replace(env, aad=b"other-job"), priv)


def test_attestation_is_mock_and_signed():
    a = attest("BL-01", GOOD)
    assert a.mock is True and a.is_valid()
    assert b'"attestation":"mock"' in a.payload()
    forged = replace(a, evidence={**GOOD, "certified": True})
    assert not forged.is_valid()


def _broker_with_job(access_class="swiss-only"):
    b = KeyBroker()
    pub = b.register_job("job-1", "canton-bs", access_class)
    return b, pub


def test_release_ok_and_key_opens_job_envelope():
    b, pub = _broker_with_job()
    env = seal(b"input shard", pub, aad=b"job-1")
    r = b.release("job-1", "BL-01", attest("BL-01", GOOD), "CH-BL")
    assert isinstance(r, ReleasedKey) and r.mock
    assert open_(env, r.key) == b"input shard"


def test_deny_bad_attestation():
    b, _ = _broker_with_job()
    a = attest("BL-01", GOOD)
    assert b.release("job-1", "BL-01", replace(a, signature=b"\0" * 64), "CH-BL").reason == "bad_attestation"
    assert b.release("job-1", "BL-02", a, "CH-BL").reason == "bad_attestation"  # attestation for another node
    wrong_image = attest("BL-01", {**GOOD, "measurement": "unknown-image"})
    assert b.release("job-1", "BL-01", wrong_image, "CH-BL").reason == "bad_attestation"


@pytest.mark.parametrize("access_class,region,evidence,ok", [
    ("public", "DE-BW", GOOD, True),
    ("swiss-only", "CH-BS", GOOD, True),
    ("swiss-only", "DE-BW", GOOD, False),
    ("certified", "CH-AG", GOOD, False),  # Swiss but node not certified
    ("certified", "CH-AG", CERT, True),
    ("certified", "FR-68", CERT, False),
])
def test_region_rule_per_access_class(access_class, region, evidence, ok):
    b, _ = _broker_with_job(access_class)
    r = b.release("job-1", "N1", attest("N1", evidence), region)
    assert isinstance(r, ReleasedKey) is ok
    if not ok:
        assert isinstance(r, Denied) and r.reason == "region_not_allowed"


def test_deny_tampered_node():
    b, _ = _broker_with_job()
    a = attest("BL-01", GOOD)
    assert isinstance(b.release("job-1", "BL-01", a, "CH-BL"), ReleasedKey)
    b.tamper("BL-01")
    r = b.release("job-1", "BL-01", a, "CH-BL")
    assert isinstance(r, Denied) and r.reason == "node_tampered"
    assert isinstance(b.release("job-1", "BL-02", attest("BL-02", GOOD), "CH-BL"), ReleasedKey)


def test_shred_makes_old_envelopes_unopenable():
    b, pub = _broker_with_job()
    env = seal(b"pre-shred data", pub)
    assert b.shred("canton-bs") == 1
    r = b.release("job-1", "BL-01", attest("BL-01", GOOD), "CH-BL")
    assert isinstance(r, Denied) and r.reason == "shredded"
    with pytest.raises(KeyError):
        b.job_public_key("job-1")
    # the only key that could open env is gone: a fresh key cannot open it
    with pytest.raises(InvalidEnvelope):
        open_(env, generate_keypair()[0])


def test_unknown_job_denied():
    assert KeyBroker().release("nope", "N1", attest("N1", GOOD), "CH-BS").reason == "unknown_job"


def test_audit_log_chain_and_single_edit_detected():
    log = AuditLog()
    for i in range(5):
        log.append({"type": "x", "i": i})
    assert log.verify()
    assert log.entries[3].prev_hash == log.entries[2].hash
    log.entries[2] = replace(log.entries[2], event={"type": "x", "i": 99})
    assert not log.verify()


def test_audit_log_detects_deletion():
    log = AuditLog()
    for i in range(3):
        log.append({"i": i})
    del log.entries[1]
    assert not log.verify()


def test_broker_audits_every_decision_with_mock_label():
    b, _ = _broker_with_job()
    b.release("job-1", "BL-01", attest("BL-01", GOOD), "CH-BL")
    b.release("job-1", "BL-01", attest("BL-01", GOOD), "DE-BW")
    b.tamper("BL-01")
    b.shred("canton-bs")
    types = [e.event["type"] for e in b.audit.entries]
    assert types == ["register", "release", "deny", "tamper", "shred"]
    assert all(e.event.get("attestation") == "mock" for e in b.audit.entries if e.event["type"] in ("release", "deny"))
    assert b.audit.verify()


def test_unknown_access_class_rejected():
    with pytest.raises(ValueError):
        region_allowed("secret", "CH-BS", True)
    with pytest.raises(ValueError):
        KeyBroker().register_job("j", "c", "secret")
