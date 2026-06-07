"""Minisign signature verification + manifest sign helpers.

Tauri's auto-updater verifies update manifests with **minisign** — an
Ed25519-based scheme by Frank Denis (compatible with `signify`). The
plugin embeds the public key (`pubkey` in `tauri.conf.json`) and rejects
any manifest whose signature doesn't match.

This module ships:

- `verify_signature(message, signature_b64, pubkey_b64)` — pure-Python
  Ed25519 verifier built on `cryptography`. Useful for backend-side
  validation of any manifest we serve, so we never hand out a manifest
  the Tauri client would refuse.
- `parse_pubkey` / `parse_signature` — minisign's compact base64 layout
  (the same `untrusted comment:` headers + base64 blob the CLI emits).
- `sign_manifest_with_external_cli(...)` — shells out to the `minisign`
  binary on the host. Production signing always uses the offline CLI
  (keys live on a yubikey or HSM), so we keep the signing path narrow
  and verify-only on the server.

Format reference:
  https://jedisct1.github.io/minisign/
"""
from __future__ import annotations

import base64
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

# Minisign signature algorithm tags.
SIG_ALGO_LEGACY = b"Ed"
SIG_ALGO_HASHED = b"ED"


@dataclass(frozen=True)
class MinisignPubkey:
    key_id: bytes      # 8 bytes
    public_key: bytes  # 32 bytes (Ed25519)


@dataclass(frozen=True)
class MinisignSignature:
    algo: bytes        # `b"Ed"` or `b"ED"`
    key_id: bytes      # 8 bytes
    signature: bytes   # 64 bytes (Ed25519)
    trusted_comment: str
    global_sig: bytes  # 64 bytes (signature over signature || trusted_comment)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_pubkey(text: str) -> MinisignPubkey:
    """Parse the body of a minisign `.pub` file.

    Format (without comment lines): base64 of `algo(2) || key_id(8) || pubkey(32)`.
    """
    line = _strip_comments(text)
    raw = base64.b64decode(line)
    if len(raw) != 2 + 8 + 32:
        raise ValueError(f"unexpected pubkey blob length: {len(raw)}")
    if raw[:2] not in (SIG_ALGO_LEGACY, SIG_ALGO_HASHED):
        raise ValueError(f"unexpected pubkey algo {raw[:2]!r}")
    return MinisignPubkey(key_id=raw[2:10], public_key=raw[10:])


def parse_signature(text: str) -> MinisignSignature:
    """Parse a minisign `.minisig` file.

    Layout (after comment lines):
       line 1: base64 of `algo(2) || key_id(8) || signature(64)`
       line 2: `trusted comment: <text>`
       line 3: base64 of `global_signature(64)`
    """
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    payload_b64 = None
    trusted = None
    global_b64 = None
    for line in lines:
        if line.startswith("untrusted comment:"):
            continue
        if line.startswith("trusted comment:"):
            trusted = line.split(":", 1)[1].strip()
            continue
        if payload_b64 is None:
            payload_b64 = line.strip()
        elif global_b64 is None:
            global_b64 = line.strip()
    if not (payload_b64 and trusted is not None and global_b64):
        raise ValueError("incomplete minisign signature blob")
    payload = base64.b64decode(payload_b64)
    if len(payload) != 2 + 8 + 64:
        raise ValueError(f"unexpected signature blob length: {len(payload)}")
    return MinisignSignature(
        algo=payload[:2],
        key_id=payload[2:10],
        signature=payload[10:],
        trusted_comment=trusted,
        global_sig=base64.b64decode(global_b64),
    )


def _strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        if line.startswith("untrusted comment:") or line.startswith("trusted comment:"):
            continue
        if line.strip() == "":
            continue
        out.append(line.strip())
    if not out:
        raise ValueError("no payload lines found")
    return out[-1]


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_signature(
    message: bytes,
    signature: MinisignSignature,
    pubkey: MinisignPubkey,
) -> bool:
    """Verify the minisign signature blob produced by `minisign -S`.

    Implements both legacy (`Ed`) and hashed-prehash (`ED`) variants:

    - **Legacy** (`Ed`): signature is over the message itself.
    - **Hashed** (`ED`): signature is over BLAKE2b(message, 64). This is
      the variant `minisign -SH` and the Tauri updater emit by default.
    """
    if pubkey.key_id != signature.key_id:
        return False
    verifier = ed25519.Ed25519PublicKey.from_public_bytes(pubkey.public_key)
    try:
        if signature.algo == SIG_ALGO_HASHED:
            import hashlib

            digest = hashlib.blake2b(message, digest_size=64).digest()
            verifier.verify(signature.signature, digest)
        elif signature.algo == SIG_ALGO_LEGACY:
            verifier.verify(signature.signature, message)
        else:
            return False
    except InvalidSignature:
        return False

    # Verify the global signature over `signature || trusted_comment`.
    try:
        gtarget = signature.signature + signature.trusted_comment.encode("utf-8")
        verifier.verify(signature.global_sig, gtarget)
    except InvalidSignature:
        return False
    return True


# ---------------------------------------------------------------------------
# CLI shim — production signing always goes through the offline minisign
# binary (keys live on a yubikey / HSM); never expose private-key material
# inside this process.
# ---------------------------------------------------------------------------

def sign_manifest_with_external_cli(
    manifest_path: Path,
    secret_key_path: Path,
    *,
    trusted_comment: str,
    minisign_bin: str | None = None,
    password_env: str = "MINISIGN_PASSWORD",  # noqa: S107 — env var name, not a secret
) -> Path:
    """Invoke the minisign CLI to sign `manifest_path` with a hashed sig.

    Returns the path of the resulting `.minisig` file.

    Caller is expected to set `MINISIGN_PASSWORD` (or pipe the password
    in via the minisign CLI's stdin) before invoking. Ops typically runs
    this inside a one-shot signing job that ejects the password immediately.
    """
    bin_path = minisign_bin or shutil.which("minisign")
    if not bin_path:
        raise RuntimeError(
            "minisign CLI not found on PATH; install via brew/apt or set minisign_bin."
        )
    cmd = [
        bin_path,
        "-SH",
        "-s", str(secret_key_path),
        "-m", str(manifest_path),
        "-t", trusted_comment,
    ]
    res = subprocess.run(  # noqa: S603 — bin_path resolved above
        cmd,
        check=False,
        capture_output=True,
        env={"MINISIGN_PASSWORD": "" if password_env not in {"MINISIGN_PASSWORD"} else "REDACTED"},
    )
    if res.returncode != 0:
        raise RuntimeError(f"minisign failed: {res.stderr.decode(errors='replace')}")
    sig_path = manifest_path.with_suffix(manifest_path.suffix + ".minisig")
    if not sig_path.exists():
        raise RuntimeError(f"expected sig at {sig_path}, not found")
    return sig_path


__all__ = [
    "MinisignPubkey",
    "MinisignSignature",
    "parse_pubkey",
    "parse_signature",
    "sign_manifest_with_external_cli",
    "verify_signature",
]
