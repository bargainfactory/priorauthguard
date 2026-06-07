"""Tauri desktop update manifest endpoint.

The Tauri updater plugin calls
`GET /v1/updates/desktop/{target}/{current_version}` and expects either:

- **204 No Content** when no update is available, or
- **200 OK** with a JSON body matching Tauri's updater schema:

```json
{
  "version": "1.2.3",
  "notes": "Release notes",
  "pub_date": "2026-06-07T08:00:00Z",
  "platforms": {
    "darwin-aarch64": {
      "signature": "minisign-signature-bytes",
      "url": "https://releases.priorauthguard.com/v1.2.3/pa-guard_1.2.3_aarch64.dmg"
    }
  }
}
```

Manifest contents come from the file at `PAG_UPDATE_MANIFEST_PATH`
(default: `data/desktop-updates.json` in the working directory). Ops
publishes a new release by uploading the artifacts to a CDN, generating a
minisign signature for each artifact, and committing the manifest file
to a config repo that's mounted into the backend.

The endpoint is **read-only** and never accepts payloads — it cannot be
used to push manifests. New releases land in the manifest file out-of-band.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response

from ..core.config import get_settings
from ..core.logging import get_logger

router = APIRouter()


def _load_manifest() -> dict[str, Any] | None:
    settings = get_settings()
    path = Path(getattr(settings, "update_manifest_path", "data/desktop-updates.json"))
    if not path.exists():
        return None
    try:
        with path.open() as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        get_logger("updates").warning("manifest_load_failed", error=str(exc))
        return None


def _semver_tuple(v: str) -> tuple[int, ...]:
    """Parse `MAJOR.MINOR.PATCH` into a comparable tuple. Ignores suffix."""
    base = v.split("-", 1)[0].split("+", 1)[0]
    parts = []
    for chunk in base.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


@router.get("/v1/updates/desktop/{target}/{current_version}", tags=["updates"])
async def desktop_update_manifest(
    target: str,
    current_version: str,
    user_agent: str | None = Header(default=None),
) -> Response:
    """Return the latest applicable update manifest, or 204 if none."""
    log = get_logger("updates")
    manifest = _load_manifest()
    if manifest is None:
        log.info("update_no_manifest", target=target, current=current_version)
        return Response(status_code=204)

    latest = str(manifest.get("version", ""))
    if not latest:
        log.warning("update_manifest_missing_version")
        return Response(status_code=204)

    if _semver_tuple(latest) <= _semver_tuple(current_version):
        log.info(
            "update_already_current",
            target=target,
            current=current_version,
            latest=latest,
        )
        return Response(status_code=204)

    platforms: dict[str, Any] = manifest.get("platforms", {})
    if target not in platforms:
        log.info(
            "update_target_unsupported",
            target=target,
            current=current_version,
            latest=latest,
        )
        return Response(status_code=204)

    body = {
        "version": latest,
        "notes": manifest.get("notes", ""),
        "pub_date": manifest.get("pub_date", datetime.now(UTC).isoformat()),
        "platforms": {target: platforms[target]},
    }
    log.info(
        "update_offered",
        target=target,
        current=current_version,
        latest=latest,
        user_agent=user_agent,
    )
    return Response(
        content=json.dumps(body),
        media_type="application/json",
    )


@router.head("/v1/updates/desktop/{target}/{current_version}", tags=["updates"])
async def desktop_update_head(
    target: str, current_version: str
) -> Response:
    """Cheap HEAD probe used by `tauri:check-only` flows."""
    return Response(status_code=200 if _load_manifest() else 204)


__all__ = ["router"]


# Defensive 404 helper so call sites can short-circuit cleanly.
def _not_implemented() -> None:
    raise HTTPException(status_code=501)
