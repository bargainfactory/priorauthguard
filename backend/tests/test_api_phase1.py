"""API tests for Phase 1 endpoints (/v1/pa, /v1/pa/{rid}, /v1/pa/{rid}/appeal, /v1/voice/dictation)."""
from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from pa_guard.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _intake_payload() -> dict:
    return {
        "note": {
            "source": "manual",
            "text": (
                "Mr. John Smith MRN: AB12345678 with chronic lumbar radicular pain. "
                "Failed conservative therapy of 6 weeks PT + NSAIDs. "
                "Imaging confirms radiculopathy."
            ),
            "patient_first_name": "John",
            "patient_last_name": "Smith",
            "patient_mrn": "AB12345678",
        },
        "meta": {
            "jurisdiction": {"jurisdiction": "us-state", "state_code": "CA"},
            "payer_id": "anthem",
            "procedure_code": "64483",
            "diagnosis_codes": ["M54.16"],
            "urgency": "routine",
        },
    }


def test_run_pa_happy_path(client: TestClient) -> None:
    r = client.post("/v1/pa", json=_intake_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "submitted"
    assert body["needs_human_approval"] is False
    assert body["pa_request"] is not None
    assert body["document"] is not None
    assert body["audit"] is not None
    assert body["receipt"] is not None
    # PHI never leaks back to client.
    cleaned = body["pa_request"]["safe_context"]["cleaned_text"]
    assert "Smith" not in cleaned
    assert "AB12345678" not in cleaned


def test_get_pa_returns_persisted_run(client: TestClient) -> None:
    r1 = client.post("/v1/pa", json=_intake_payload())
    body = r1.json()
    rid = body["pa_request"]["meta"]["request_id"]
    UUID(rid)  # validates shape

    r2 = client.get(f"/v1/pa/{rid}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "submitted"


def test_get_pa_unknown_returns_404(client: TestClient) -> None:
    r = client.get("/v1/pa/00000000-0000-4000-8000-000000000000")
    assert r.status_code == 404


def test_appeal_runs(client: TestClient) -> None:
    r1 = client.post("/v1/pa", json=_intake_payload())
    body = r1.json()
    rid = body["pa_request"]["meta"]["request_id"]
    document = body["document"]
    evidence = body["evidence"]

    appeal_payload = {
        "denial": {
            "request_id": rid,
            "reason_codes": ["MN-1"],
            "summary": "Insufficient conservative-therapy documentation.",
            "appealable": True,
        },
        "document": document,
        "evidence": evidence,
    }
    r2 = client.post(f"/v1/pa/{rid}/appeal", json=appeal_payload)
    assert r2.status_code == 200, r2.text
    appeal = r2.json()
    assert appeal["counter_arguments"]
    assert appeal["narrative"]


def test_appeal_rejects_mismatched_rid(client: TestClient) -> None:
    r1 = client.post("/v1/pa", json=_intake_payload())
    body = r1.json()
    document = body["document"]
    evidence = body["evidence"]
    other_rid = "11111111-1111-4111-8111-111111111111"
    appeal_payload = {
        "denial": {
            "request_id": other_rid,
            "reason_codes": ["MN-1"],
            "summary": "x",
            "appealable": True,
        },
        "document": document,
        "evidence": evidence,
    }
    r = client.post(f"/v1/pa/{other_rid}/appeal", json=appeal_payload)
    assert r.status_code == 400


def test_voice_dictation_de_identifies(client: TestClient) -> None:
    r = client.post(
        "/v1/voice/dictation",
        json={
            "text": "Mr. John Smith MRN: AB12345678 follow-up appointment.",
            "speaker_role": "provider",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Smith" not in body["cleaned_text"]
    assert "AB12345678" not in body["cleaned_text"]
    assert body["identifiers_redacted"] >= 2
