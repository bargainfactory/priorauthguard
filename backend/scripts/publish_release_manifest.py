"""Build + sign + publish a Tauri update manifest.

Workflow (intended for the CI release job):

  1. After the `tauri` matrix job uploads bundles for every target,
     the release job runs:

        python -m scripts.publish_release_manifest \
            --version 1.2.3 \
            --notes-file CHANGELOG.md \
            --base-url https://releases.priorauthguard.com/desktop/v1.2.3 \
            --secret-key /tmp/minisign.key \
            --artifacts darwin-aarch64=dist/pa-guard_1.2.3_aarch64.tar.gz \
                        darwin-x86_64=dist/pa-guard_1.2.3_x86_64.tar.gz \
                        linux-x86_64=dist/pa-guard_1.2.3_amd64.AppImage.tar.gz \
                        windows-x86_64=dist/pa-guard_1.2.3_x64-setup.nsis.zip

  2. Each artifact gets a hashed signature via the offline `minisign`
     binary. The signature blob is embedded directly into the manifest
     under `platforms[target].signature`.
  3. The resulting `data/desktop-updates.json` is verified locally and
     uploaded to the CDN. The backend's `/v1/updates/...` endpoint
     reads the same file and offers the update to clients.

The script never holds private-key material in memory — every signing
operation goes through the minisign CLI invocation.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from pa_guard.security.minisign import (
    parse_pubkey,
    parse_signature,
    verify_signature,
)


def _sign_file(file_path: Path, secret_key: Path, trusted_comment: str) -> str:
    """Sign `file_path` with the offline minisign CLI and return the sig blob."""
    cmd = [
        "minisign",
        "-SH",
        "-s", str(secret_key),
        "-m", str(file_path),
        "-t", trusted_comment,
    ]
    res = subprocess.run(cmd, check=False, capture_output=True)  # noqa: S603
    if res.returncode != 0:
        raise RuntimeError(f"minisign failed: {res.stderr.decode(errors='replace')}")
    sig_path = file_path.with_suffix(file_path.suffix + ".minisig")
    if not sig_path.exists():
        raise RuntimeError(f"sig not produced at {sig_path}")
    blob = sig_path.read_text()
    return blob


def _verify_locally(
    artifact: Path, sig_blob: str, pubkey_path: Path
) -> None:
    """Double-check: parse our own pubkey + sig and verify before publishing."""
    pubkey = parse_pubkey(pubkey_path.read_text())
    sig = parse_signature(sig_blob)
    message = artifact.read_bytes()
    if not verify_signature(message, sig, pubkey):
        raise RuntimeError(
            f"local verification failed for {artifact} — manifest is broken"
        )


def _artifact_url(base_url: str, artifact_name: str) -> str:
    return f"{base_url.rstrip('/')}/{artifact_name}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return base64.b16encode(h.digest()).decode().lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes-file", type=Path, default=None)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--secret-key", type=Path, required=True)
    parser.add_argument("--pubkey", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path,
                        default=Path("data/desktop-updates.json"))
    parser.add_argument("--trusted-comment-prefix", default="PriorAuthGuard release")
    parser.add_argument(
        "--artifacts",
        nargs="+",
        required=True,
        help="Pairs of target=path, e.g. darwin-aarch64=dist/pa-guard.tar.gz",
    )
    args = parser.parse_args()

    notes = ""
    if args.notes_file and args.notes_file.exists():
        notes = args.notes_file.read_text()

    if "MINISIGN_PASSWORD" not in os.environ:
        print(
            "WARNING: MINISIGN_PASSWORD not set; minisign will prompt interactively.",
            file=sys.stderr,
        )

    platforms: dict[str, dict[str, str]] = {}
    for pair in args.artifacts:
        target, path_str = pair.split("=", 1)
        artifact = Path(path_str)
        if not artifact.exists():
            print(f"missing artifact for {target}: {artifact}", file=sys.stderr)
            return 2
        trusted = f"{args.trusted_comment_prefix} {args.version} {target}"
        print(f"signing {target}: {artifact}")
        sig_blob = _sign_file(artifact, args.secret_key, trusted)
        _verify_locally(artifact, sig_blob, args.pubkey)

        platforms[target] = {
            "signature": sig_blob,
            "url": _artifact_url(args.base_url, artifact.name),
            "sha256": _sha256(artifact),
        }

    manifest = {
        "version": args.version,
        "notes": notes.strip(),
        "pub_date": datetime.now(UTC).isoformat(),
        "platforms": platforms,
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest, indent=2))
    print(f"manifest written: {args.manifest_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
