"""Tauri updater endpoint tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pa_guard.api.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Point the endpoint at a tmp manifest each test.
    manifest_path = tmp_path / "desktop-updates.json"
    monkeypatch.setenv("PAG_UPDATE_MANIFEST_PATH", str(manifest_path))
    # Reset the cached settings so the new env vars take effect.
    from pa_guard.core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    with TestClient(app) as c:
        # Attach the manifest path so tests can write to it.
        c.app.state._manifest_path = manifest_path  # type: ignore[attr-defined]
        yield c


def _write_manifest(path: Path, version: str, targets: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": version,
        "notes": f"Release {version}",
        "pub_date": "2026-06-07T00:00:00Z",
        "platforms": targets,
    }
    path.write_text(json.dumps(payload))


def test_no_manifest_returns_204(client: TestClient) -> None:
    r = client.get("/v1/updates/desktop/darwin-aarch64/0.4.0")
    assert r.status_code == 204


def test_older_current_version_gets_manifest(client: TestClient) -> None:
    path: Path = client.app.state._manifest_path  # type: ignore[attr-defined]
    _write_manifest(
        path,
        version="1.0.0",
        targets={
            "darwin-aarch64": {
                "signature": "fake-sig",
                "url": "https://releases.example.com/pa-guard_1.0.0.dmg",
            }
        },
    )
    r = client.get("/v1/updates/desktop/darwin-aarch64/0.4.0")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "1.0.0"
    assert "darwin-aarch64" in body["platforms"]
    assert body["platforms"]["darwin-aarch64"]["url"].endswith(".dmg")


def test_current_version_equal_returns_204(client: TestClient) -> None:
    path: Path = client.app.state._manifest_path  # type: ignore[attr-defined]
    _write_manifest(
        path,
        version="1.0.0",
        targets={
            "darwin-aarch64": {"signature": "x", "url": "https://example.com/x.dmg"}
        },
    )
    r = client.get("/v1/updates/desktop/darwin-aarch64/1.0.0")
    assert r.status_code == 204


def test_current_version_newer_returns_204(client: TestClient) -> None:
    path: Path = client.app.state._manifest_path  # type: ignore[attr-defined]
    _write_manifest(
        path,
        version="1.0.0",
        targets={
            "darwin-aarch64": {"signature": "x", "url": "https://example.com/x.dmg"}
        },
    )
    r = client.get("/v1/updates/desktop/darwin-aarch64/1.5.0")
    assert r.status_code == 204


def test_target_not_in_manifest_returns_204(client: TestClient) -> None:
    path: Path = client.app.state._manifest_path  # type: ignore[attr-defined]
    _write_manifest(
        path,
        version="2.0.0",
        targets={
            "darwin-aarch64": {"signature": "x", "url": "https://example.com/x.dmg"}
        },
    )
    r = client.get("/v1/updates/desktop/linux-x86_64/1.0.0")
    assert r.status_code == 204


def test_head_endpoint(client: TestClient) -> None:
    r = client.head("/v1/updates/desktop/darwin-aarch64/0.4.0")
    assert r.status_code == 204
    path: Path = client.app.state._manifest_path  # type: ignore[attr-defined]
    _write_manifest(
        path,
        version="2.0.0",
        targets={
            "darwin-aarch64": {"signature": "x", "url": "https://example.com/x.dmg"}
        },
    )
    r2 = client.head("/v1/updates/desktop/darwin-aarch64/0.4.0")
    assert r2.status_code == 200
