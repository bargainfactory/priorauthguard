"""Minisign verifier tests.

We mint an Ed25519 key in-process, hand-roll a minisign-format signature
matching the wire layout, and assert `verify_signature` accepts only the
signatures it should and rejects everything else.
"""
from __future__ import annotations

import base64
import hashlib
import os

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from pa_guard.security.minisign import (
    MinisignPubkey,
    MinisignSignature,
    parse_pubkey,
    parse_signature,
    verify_signature,
)


def _mint_keypair() -> tuple[ed25519.Ed25519PrivateKey, MinisignPubkey, bytes]:
    sk = ed25519.Ed25519PrivateKey.generate()
    pk = sk.public_key()
    raw_pk = pk.public_bytes_raw()
    key_id = os.urandom(8)
    return sk, MinisignPubkey(key_id=key_id, public_key=raw_pk), key_id


def _make_signature(
    sk: ed25519.Ed25519PrivateKey,
    key_id: bytes,
    message: bytes,
    *,
    trusted_comment: str = "release 1.0.0",
    algo: bytes = b"ED",
) -> MinisignSignature:
    if algo == b"ED":
        digest = hashlib.blake2b(message, digest_size=64).digest()
        sig_bytes = sk.sign(digest)
    elif algo == b"Ed":
        sig_bytes = sk.sign(message)
    else:
        raise AssertionError(f"unknown algo: {algo!r}")
    global_sig = sk.sign(sig_bytes + trusted_comment.encode())
    return MinisignSignature(
        algo=algo,
        key_id=key_id,
        signature=sig_bytes,
        trusted_comment=trusted_comment,
        global_sig=global_sig,
    )


# ---------------------------------------------------------------------------
# Hashed (ED) signatures — the variant Tauri uses.
# ---------------------------------------------------------------------------

def test_hashed_signature_verifies() -> None:
    sk, pubkey, key_id = _mint_keypair()
    message = b'{"version":"1.0.0","platforms":{}}'
    sig = _make_signature(sk, key_id, message)
    assert verify_signature(message, sig, pubkey) is True


def test_hashed_signature_rejects_tampered_payload() -> None:
    sk, pubkey, key_id = _mint_keypair()
    message = b'{"version":"1.0.0","platforms":{}}'
    sig = _make_signature(sk, key_id, message)
    assert verify_signature(b'{"version":"2.0.0"}', sig, pubkey) is False


def test_hashed_signature_rejects_wrong_key() -> None:
    sk, _, _ = _mint_keypair()
    _, other_pub, other_id = _mint_keypair()
    message = b"payload"
    sig = _make_signature(sk, other_id, message)
    # key_id matches, but verifier holds a different actual key.
    sig = MinisignSignature(
        algo=sig.algo,
        key_id=other_pub.key_id,
        signature=sig.signature,
        trusted_comment=sig.trusted_comment,
        global_sig=sig.global_sig,
    )
    assert verify_signature(message, sig, other_pub) is False


def test_legacy_signature_verifies() -> None:
    sk, pubkey, key_id = _mint_keypair()
    message = b"legacy payload"
    sig = _make_signature(sk, key_id, message, algo=b"Ed")
    assert verify_signature(message, sig, pubkey) is True


def test_global_signature_tamper_rejected() -> None:
    sk, pubkey, key_id = _mint_keypair()
    message = b"payload"
    sig = _make_signature(sk, key_id, message)
    bad = MinisignSignature(
        algo=sig.algo,
        key_id=sig.key_id,
        signature=sig.signature,
        trusted_comment="DIFFERENT",
        global_sig=sig.global_sig,
    )
    assert verify_signature(message, bad, pubkey) is False


def test_key_id_mismatch_rejected() -> None:
    sk, pubkey, _ = _mint_keypair()
    message = b"payload"
    sig = _make_signature(sk, b"\x00" * 8, message)
    assert verify_signature(message, sig, pubkey) is False


def test_unknown_algo_rejected() -> None:
    _, pubkey, _ = _mint_keypair()
    message = b"payload"
    sig = MinisignSignature(
        algo=b"??",
        key_id=pubkey.key_id,
        signature=b"\x00" * 64,
        trusted_comment="x",
        global_sig=b"\x00" * 64,
    )
    assert verify_signature(message, sig, pubkey) is False


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_parse_pubkey_roundtrip() -> None:
    _, pubkey, _ = _mint_keypair()
    blob = base64.b64encode(b"Ed" + pubkey.key_id + pubkey.public_key).decode()
    text = f"untrusted comment: minisign public key\n{blob}\n"
    parsed = parse_pubkey(text)
    assert parsed.key_id == pubkey.key_id
    assert parsed.public_key == pubkey.public_key


def test_parse_signature_full_blob() -> None:
    sk, pubkey, key_id = _mint_keypair()
    message = b"payload"
    sig = _make_signature(sk, key_id, message)
    payload_b64 = base64.b64encode(sig.algo + sig.key_id + sig.signature).decode()
    global_b64 = base64.b64encode(sig.global_sig).decode()
    text = (
        f"untrusted comment: signature from minisign secret key\n"
        f"{payload_b64}\n"
        f"trusted comment: {sig.trusted_comment}\n"
        f"{global_b64}\n"
    )
    parsed = parse_signature(text)
    assert parsed.algo == sig.algo
    assert parsed.key_id == sig.key_id
    assert parsed.signature == sig.signature
    assert parsed.trusted_comment == sig.trusted_comment
    assert parsed.global_sig == sig.global_sig
    # Parsed signature must still verify.
    assert verify_signature(message, parsed, pubkey) is True


def test_parse_signature_rejects_incomplete_blob() -> None:
    with pytest.raises(ValueError):
        parse_signature("untrusted comment: x\n")


def test_parse_pubkey_rejects_wrong_length() -> None:
    text = f"untrusted comment: x\n{base64.b64encode(b'short').decode()}\n"
    with pytest.raises(ValueError):
        parse_pubkey(text)
