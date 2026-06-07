"""Multi-tenant isolation tests — PARegistry partitioning + API header guard."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from pa_guard.api.main import app
from pa_guard.storage.pa_registry import InMemoryPARegistry, SqlPARegistry

# ---------------------------------------------------------------------------
# Registry partitioning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_in_memory_registry_partitions_by_tenant() -> None:
    reg = InMemoryPARegistry()
    rid_a = uuid4()
    rid_b = uuid4()
    await reg.put("acme", rid_a, {"status": "submitted", "tenant": "acme"})
    await reg.put("beta", rid_b, {"status": "submitted", "tenant": "beta"})

    # Cross-tenant lookups must be invisible.
    assert await reg.get("acme", rid_a) is not None
    assert await reg.get("acme", rid_b) is None
    assert await reg.get("beta", rid_a) is None
    assert await reg.get("beta", rid_b) is not None


@pytest.mark.asyncio
async def test_in_memory_list_recent_only_returns_own_tenant() -> None:
    reg = InMemoryPARegistry()
    for _ in range(3):
        await reg.put("acme", uuid4(), {"status": "submitted"})
    for _ in range(2):
        await reg.put("beta", uuid4(), {"status": "submitted"})
    assert len(list(await reg.list_recent("acme"))) == 3
    assert len(list(await reg.list_recent("beta"))) == 2
    assert list(await reg.list_recent("nonexistent")) == []


@pytest.mark.asyncio
async def test_sql_registry_partitions_by_tenant(tmp_path: Path) -> None:
    try:
        db = tmp_path / "tenant.sqlite"
        reg = SqlPARegistry(database_url=f"sqlite+aiosqlite:///{db}")
        rid_a = uuid4()
        rid_b = uuid4()
        await reg.put("acme", rid_a, {"status": "submitted"})
        await reg.put("beta", rid_b, {"status": "submitted"})

        assert await reg.get("acme", rid_a) is not None
        assert await reg.get("acme", rid_b) is None
        assert await reg.get("beta", rid_a) is None
    except ModuleNotFoundError as e:
        pytest.skip(f"aiosqlite missing: {e}")


# ---------------------------------------------------------------------------
# API tenant header guard
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _payload(tenant_id: str = "default") -> dict:
    return {
        "note": {
            "source": "manual",
            "text": "Mr. John Smith MRN: AB12345678 chronic radicular pain.",
        },
        "meta": {
            "jurisdiction": {"jurisdiction": "us-state", "state_code": "CA"},
            "payer_id": "anthem",
            "procedure_code": "64483",
            "diagnosis_codes": ["M54.16"],
            "urgency": "routine",
            "tenant_id": tenant_id,
        },
    }


def test_api_header_matching_tenant_accepted(client: TestClient) -> None:
    r = client.post("/v1/pa", json=_payload("acme"), headers={"X-Tenant-Id": "acme"})
    assert r.status_code == 200
    assert r.json()["pa_request"]["meta"]["tenant_id"] == "acme"


def test_api_header_mismatched_tenant_rejected_403(client: TestClient) -> None:
    r = client.post(
        "/v1/pa",
        json=_payload("acme"),
        headers={"X-Tenant-Id": "beta"},
    )
    assert r.status_code == 403


def test_api_cross_tenant_get_returns_404(client: TestClient) -> None:
    r = client.post("/v1/pa", json=_payload("acme"), headers={"X-Tenant-Id": "acme"})
    assert r.status_code == 200
    rid = r.json()["pa_request"]["meta"]["request_id"]

    other = client.get(f"/v1/pa/{rid}", headers={"X-Tenant-Id": "beta"})
    assert other.status_code == 404

    same = client.get(f"/v1/pa/{rid}", headers={"X-Tenant-Id": "acme"})
    assert same.status_code == 200
