"""Phase 2 API tests — aggregates, proposals, zk-STARK verify, supervisor
adds FHE risk score + proof_id to the run response."""
from __future__ import annotations

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
                "Failed 6w PT + NSAIDs."
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


def test_pa_run_now_includes_risk_score_and_proof_id(client: TestClient) -> None:
    r = client.post("/v1/pa", json=_intake_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "submitted"
    assert body["risk_score"] is not None
    assert body["risk_score"]["circuit_name"] == "denial_risk_v0"
    assert body["proof_id"]  # zk-STARK proof_id stamped on the response


def test_outcomes_aggregate_returns_metrics(client: TestClient) -> None:
    # Run at least one PA so there's data to aggregate.
    client.post("/v1/pa", json=_intake_payload())
    r = client.get("/v1/outcomes/aggregate")
    assert r.status_code == 200, r.text
    agg = r.json()
    assert agg["sample_count"] > 0
    assert "by_agent_avg_latency_ms" in agg


def test_meta_improver_proposes_and_human_decides(client: TestClient) -> None:
    # Generate proposals from current aggregate (may be empty if everything is healthy).
    r = client.post("/v1/meta-improver/proposals")
    assert r.status_code == 200, r.text
    proposals = r.json()

    if not proposals:
        # Healthy aggregate; nothing to decide on. The list endpoint must still work.
        r2 = client.get("/v1/meta-improver/proposals")
        assert r2.status_code == 200
        return

    pid = proposals[0]["proposal_id"]
    decide = client.post(
        f"/v1/meta-improver/proposals/{pid}/decide",
        json={"approve": True, "approved_by": "test@example.com"},
    )
    assert decide.status_code == 200
    assert decide.json()["status"] == "approved"
    assert decide.json()["approved_by"] == "test@example.com"


def test_zkstark_verify_endpoint(client: TestClient) -> None:
    # Get a proof_id from a real PA run, then verify the underlying proof.
    # The supervisor stamps proof_id but the proof_blob isn't returned in the
    # PA response; we synthesize a stand-alone proof here for the contract.
    import asyncio

    from pa_guard.services.zkstark import StatementInputs, ZkStarkProver

    proof = asyncio.run(
        ZkStarkProver().prove(
            StatementInputs(
                model_commitment="denial_risk_v0",
                input_hash="a" * 64,
                output_hash="b" * 64,
            )
        )
    )
    payload = proof.model_dump(mode="json")
    r = client.post("/v1/zkstark/verify", json=payload)
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_zkstark_verify_rejects_tampered_proof(client: TestClient) -> None:
    import asyncio

    from pa_guard.services.zkstark import StatementInputs, ZkStarkProver

    proof = asyncio.run(
        ZkStarkProver().prove(
            StatementInputs(
                model_commitment="denial_risk_v0",
                input_hash="a" * 64,
                output_hash="b" * 64,
            )
        )
    )
    payload = proof.model_dump(mode="json")
    payload["input_hash"] = "c" * 64
    r = client.post("/v1/zkstark/verify", json=payload)
    assert r.status_code == 200
    assert r.json()["valid"] is False
