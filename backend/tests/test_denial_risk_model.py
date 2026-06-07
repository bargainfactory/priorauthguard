"""Tests for the trained denial-risk model.

The persisted weights live at
`pa_guard/services/denial_risk_v1.weights.json`. These tests pin:
- Loading the weights returns a sane model.
- Higher-risk feature vectors produce higher predicted probabilities.
- The plaintext baseline (now backed by the trained model) is the
  default for `FHEInferenceService`'s `denial_risk_v0` circuit.
"""
from __future__ import annotations

import pytest

from pa_guard.core.models import FHEInferenceRequest
from pa_guard.services.denial_risk_model import (
    DenialRiskModel,
    train_denial_risk_v1,
)
from pa_guard.services.fhe_inference import FHEInferenceService


def test_load_persisted_weights() -> None:
    model = DenialRiskModel.load()
    assert len(model.weights) == 3
    assert model.feature_names == ("urgency", "prior_denials", "missing_docs_count")
    assert model.sample_count > 0


def test_monotonic_in_urgency() -> None:
    model = DenialRiskModel.load()
    p_routine = model.predict_proba(
        {"urgency": "routine", "prior_denials": 0, "missing_docs_count": 0}
    )
    p_emergent = model.predict_proba(
        {"urgency": "emergent", "prior_denials": 0, "missing_docs_count": 0}
    )
    assert 0.0 <= p_routine <= 1.0
    assert 0.0 <= p_emergent <= 1.0
    assert p_emergent > p_routine


def test_monotonic_in_prior_denials() -> None:
    model = DenialRiskModel.load()
    p0 = model.predict_proba({"urgency": "routine", "prior_denials": 0, "missing_docs_count": 0})
    p3 = model.predict_proba({"urgency": "routine", "prior_denials": 3, "missing_docs_count": 0})
    assert p3 > p0


def test_monotonic_in_missing_docs() -> None:
    model = DenialRiskModel.load()
    p0 = model.predict_proba({"urgency": "routine", "prior_denials": 0, "missing_docs_count": 0})
    p3 = model.predict_proba({"urgency": "routine", "prior_denials": 0, "missing_docs_count": 3})
    assert p3 > p0


def test_training_reproducible() -> None:
    # Same seed → identical weights.
    a = train_denial_risk_v1(n_samples=500, seed=99, epochs=200)
    b = train_denial_risk_v1(n_samples=500, seed=99, epochs=200)
    assert a.weights == b.weights
    assert a.bias == b.bias


@pytest.mark.asyncio
async def test_fhe_service_uses_trained_baseline() -> None:
    svc = FHEInferenceService()
    res = await svc.infer(
        FHEInferenceRequest(
            circuit_name="denial_risk_v0",
            features={
                "urgency": "emergent",
                "prior_denials": 4.0,
                "missing_docs_count": 2.0,
            },
        )
    )
    # With the trained weights the high-risk vector should score above 0.5.
    assert isinstance(res.prediction, float)
    assert res.prediction > 0.5
