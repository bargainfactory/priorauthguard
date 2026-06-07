"""Payer adapter conformance suite.

Each adapter is run against a pinned `httpx.MockTransport` fixture that
asserts:

  1. The OUTBOUND wire shape matches the payer's spec (URL, headers,
     payload structure).
  2. The adapter parses the canonical response into a
     `SubmissionReceipt` with the right fields populated.

Production traffic is replayed by simply swapping the mock transport for a
live one — the adapter contract is the same.
"""
from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from pa_guard.core.config import Settings
from pa_guard.core.models import (
    ClinicalCriterion,
    ClinicalCriterionStatus,
    PADocument,
)


def _document(payer_id: str, procedure: str = "64483") -> PADocument:
    return PADocument(
        request_id=uuid4(),
        payer_id=payer_id,
        procedure_code=procedure,
        diagnosis_codes=["M54.16"],
        medical_necessity_narrative="De-identified narrative for tests.",
        criteria=[
            ClinicalCriterion(
                label="Conservative therapy >= 6 weeks",
                status=ClinicalCriterionStatus.MET,
                rationale="Documented PT 6w + NSAIDs 4w.",
                evidence_ids=[uuid4()],
            )
        ],
        citations=[uuid4()],
    )


# ---------------------------------------------------------------------------
# Availity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_availity_outbound_wire_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_url: list[str] = []
    seen_payload: dict = {}
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_url.append(str(request.url))
        seen_auth.append(request.headers.get("authorization"))
        path = request.url.path
        if path.endswith("/availity/v1/token"):
            return httpx.Response(200, json={"access_token": "TOKEN", "expires_in": 3600})
        if path.endswith("/availity/v1/coverages/prior-authorizations"):
            seen_payload.update(json.loads(request.content.decode()))
            return httpx.Response(
                200,
                json={
                    "trackingNumber": "AV-12345",
                    "estimatedResponseSeconds": 7 * 24 * 3600,
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(*a, **{**kw, "transport": transport}),
    )

    from pa_guard.payers.availity import AvailityAdapter

    adapter = AvailityAdapter(
        Settings(availity_client_id="ci", availity_client_secret="ci-secret"),
    )
    receipt = await adapter.submit(_document("anthem"))

    assert any("/availity/v1/token" in u for u in seen_url)
    assert any("prior-authorizations" in u for u in seen_url)
    assert seen_auth[-1] == "Bearer TOKEN"
    assert seen_payload["requestType"] == "AUTHORIZATION"
    assert seen_payload["procedure"]["code"] == "64483"
    assert seen_payload["diagnoses"] == [{"code": "M54.16"}]
    assert receipt.confirmation_code == "AV-12345"
    assert receipt.expected_response_seconds == 7 * 24 * 3600


# ---------------------------------------------------------------------------
# CoverMyMeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_covermymeds_outbound_wire_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200, json={"token": "CMM-99", "expected_response_seconds": 24 * 3600}
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(*a, **{**kw, "transport": transport}),
    )

    from pa_guard.payers.covermymeds import CoverMyMedsAdapter

    adapter = CoverMyMedsAdapter(Settings(covermymeds_api_key="ci-key"))
    receipt = await adapter.submit(_document("cms-medicare"))

    assert "/v2/prior_authorizations" in captured["url"]
    assert captured["auth"] == "Bearer ci-key"
    assert captured["body"]["payer_id"] == "cms-medicare"
    assert captured["body"]["request"]["procedure_code"] == "64483"
    assert receipt.confirmation_code == "CMM-99"
    assert receipt.expected_response_seconds == 24 * 3600


# ---------------------------------------------------------------------------
# Surescripts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_surescripts_outbound_wire_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/v1/token"):
            return httpx.Response(200, json={"access_token": "SS-TOKEN"})
        if request.url.path.endswith("/submit"):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={"paId": "PA-001", "expectedResponseSeconds": 12 * 3600}
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(*a, **{**kw, "transport": transport}),
    )

    from pa_guard.payers.surescripts import SurescriptsAdapter

    adapter = SurescriptsAdapter(
        Settings(surescripts_client_id="ci", surescripts_client_secret="ci-secret"),
    )
    receipt = await adapter.submit(_document("specialty", procedure="J1745"))

    assert "/prior-authorization/v1/submit" in seen["url"]
    assert seen["auth"] == "Bearer SS-TOKEN"
    assert seen["body"]["drug"]["code"] == "J1745"
    assert receipt.confirmation_code == "PA-001"


# ---------------------------------------------------------------------------
# NHS Spine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nhs_spine_outbound_wire_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["session"] = request.headers.get("nhsd-session-urid")
        return httpx.Response(200, json={"id": "NHS-77"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(*a, **{**kw, "transport": transport}),
    )

    from pa_guard.payers.nhs import NhsSpineAdapter

    adapter = NhsSpineAdapter(Settings(nhs_spine_api_key="ci-nhs"))
    receipt = await adapter.submit(_document("nhs-england"))

    assert "spine.nhs.uk" in captured["url"]
    assert captured["body"]["resourceType"] == "ServiceRequest"
    assert captured["body"]["code"]["coding"][0]["code"] == "64483"
    assert captured["session"] is not None
    assert receipt.confirmation_code == "NHS-77"
