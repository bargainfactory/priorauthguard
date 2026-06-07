"""Smoke tests for the FastAPI surface — Phase 0."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pa_guard.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    # `with` triggers FastAPI's lifespan so app.state is populated.
    with TestClient(app) as c:
        yield c


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_reports_circuits(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "denial_risk_v0" in body["fhe_circuits"]


def test_intake_strips_phi(client: TestClient) -> None:
    payload = {
        "note": {
            "source": "manual",
            "text": "Mr. John Smith MRN: AB12345678 ph (415) 555-0142.",
            "patient_first_name": "John",
            "patient_last_name": "Smith",
            "patient_mrn": "AB12345678",
        },
        "meta": {
            "jurisdiction": {"jurisdiction": "us-state", "state_code": "CA"},
            "payer_id": "anthem-001",
            "procedure_code": "64483",
            "diagnosis_codes": ["M54.16"],
            "urgency": "routine",
        },
    }
    r = client.post("/v1/intake", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    cleaned = body["safe_context"]["cleaned_text"]
    assert "Smith" not in cleaned
    assert "AB12345678" not in cleaned
    assert "555-0142" not in cleaned
    assert body["deid_report"]["deid_method"] == "hipaa-safe-harbor"
