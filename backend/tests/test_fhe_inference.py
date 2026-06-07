"""FHEInferenceService Phase 0 tests.

Validates the contract the rest of the system depends on. Phase 2 will add
parity tests comparing FHE outputs against the plaintext baseline.
"""
from __future__ import annotations

import pytest

from pa_guard.core.models import FHEInferenceRequest, SensitivityTier
from pa_guard.services.fhe_inference import FHEInferenceService

pytestmark = [pytest.mark.fhe, pytest.mark.asyncio]


async def test_registered_circuits_include_denial_risk() -> None:
    svc = FHEInferenceService()
    names = {c.name for c in svc.list_circuits()}
    assert "denial_risk_v0" in names


async def test_infer_returns_baseline_with_fhe_disabled() -> None:
    svc = FHEInferenceService()
    res = await svc.infer(
        FHEInferenceRequest(
            circuit_name="denial_risk_v0",
            features={
                "urgency": "urgent",
                "prior_denials": 2.0,
                "missing_docs_count": 1.0,
            },
        )
    )
    # Baseline executed (FHE off in Phase 0).
    assert res.fhe_executed is False
    assert res.plaintext_baseline_latency_ms is not None
    assert isinstance(res.prediction, float)
    assert 0.0 <= res.prediction <= 1.0


async def test_infer_rejects_phi_raw() -> None:
    svc = FHEInferenceService()
    with pytest.raises(PermissionError):
        await svc.infer(
            FHEInferenceRequest(
                circuit_name="denial_risk_v0",
                features={
                    "urgency": "routine",
                    "prior_denials": 0.0,
                    "missing_docs_count": 0.0,
                },
                sensitivity=SensitivityTier.PHI_RAW,
            )
        )


async def test_infer_rejects_unknown_circuit() -> None:
    svc = FHEInferenceService()
    with pytest.raises(KeyError):
        await svc.infer(
            FHEInferenceRequest(circuit_name="not_a_circuit", features={})
        )


async def test_infer_rejects_missing_features() -> None:
    svc = FHEInferenceService()
    with pytest.raises(ValueError):
        await svc.infer(
            FHEInferenceRequest(
                circuit_name="denial_risk_v0",
                features={"urgency": "routine"},  # missing prior_denials, missing_docs_count
            )
        )
