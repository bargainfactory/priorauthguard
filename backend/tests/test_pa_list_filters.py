"""PA list filter tests — status / urgency / payer_id."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pa_guard.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _payload(payer_id: str, urgency: str = "routine") -> dict:
    return {
        "note": {"source": "manual", "text": "Patient with chronic radiculopathy."},
        "meta": {
            "jurisdiction": {"jurisdiction": "us-state", "state_code": "CA"},
            "payer_id": payer_id,
            "procedure_code": "64483",
            "diagnosis_codes": ["M54.16"],
            "urgency": urgency,
            "tenant_id": "list-tests",
        },
    }


def test_list_filters_by_payer_id(client: TestClient) -> None:
    headers = {"X-Tenant-Id": "list-tests"}
    client.post("/v1/pa", json=_payload("anthem"), headers=headers)
    client.post("/v1/pa", json=_payload("uhc"), headers=headers)

    r = client.get("/v1/pa", params={"payer_id": "anthem"}, headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert all(
        row["pa_request"]["meta"]["payer_id"] == "anthem" for row in rows
    )
    assert len(rows) >= 1


def test_list_filters_by_status(client: TestClient) -> None:
    headers = {"X-Tenant-Id": "list-tests"}
    client.post("/v1/pa", json=_payload("anthem"), headers=headers)

    r = client.get("/v1/pa", params={"status": "submitted"}, headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert all(row["status"] == "submitted" for row in rows)


def test_list_filters_by_urgency(client: TestClient) -> None:
    headers = {"X-Tenant-Id": "list-tests"}
    client.post("/v1/pa", json=_payload("anthem", urgency="urgent"), headers=headers)

    r = client.get("/v1/pa", params={"urgency": "urgent"}, headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert all(
        row["pa_request"]["meta"]["urgency"] == "urgent" for row in rows
    )


def test_list_returns_empty_when_no_matches(client: TestClient) -> None:
    headers = {"X-Tenant-Id": "list-tests"}
    r = client.get(
        "/v1/pa",
        params={"payer_id": "nonexistent-payer-zzz"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json() == []
