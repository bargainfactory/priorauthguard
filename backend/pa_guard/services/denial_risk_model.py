"""Trained denial-risk predictor.

Replaces the hand-tuned heuristic that shipped in Phase 0. Now ships:

  - A small **logistic regression** trained on synthetic data whose joint
    distribution matches what we expect from production PA traffic
    (urgency x prior_denials x missing_docs_count -> denial probability).
  - A reproducible training routine (`train_denial_risk_v1`) — the same
    one used in the `scripts/train_denial_risk.py` CLI.
  - Persisted weights at `pa_guard/services/denial_risk_v1.weights.json`
    so the predictor runs without any sklearn / torch dependency at
    request time.

The model is the plaintext baseline that the FHE path
(`pa_guard/services/fhe_pipeline.py`) compiles to a Brevitas-QAT
circuit when the optional `[fhe]` extras are installed. Both paths share
the same `_featurize` function so plaintext and FHE outputs stay aligned.

Privacy
-------
The model is trained on **synthetic** data only. No PHI is involved at
any stage of training or inference. The feature vector is deliberately
narrow (3 dimensions, all numeric, all de-identified at the boundary).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WEIGHTS_PATH = Path(__file__).with_name("denial_risk_v1.weights.json")


@dataclass(frozen=True)
class DenialRiskModel:
    """Logistic regression: prob = sigmoid(w · x + b)."""

    weights: tuple[float, float, float]
    bias: float
    feature_names: tuple[str, str, str]
    trained_at: str
    sample_count: int

    def predict_proba(self, features: dict[str, Any]) -> float:
        x = _featurize(features)
        z = self.bias + sum(w * v for w, v in zip(self.weights, x, strict=True))
        return 1.0 / (1.0 + math.exp(-z))

    @classmethod
    def load(cls, path: Path | None = None) -> DenialRiskModel:
        target = path or WEIGHTS_PATH
        if not target.exists():
            raise FileNotFoundError(
                f"denial_risk weights not found at {target}; "
                "re-run `python -m pa_guard.scripts.train_denial_risk` to materialize them."
            )
        with target.open() as fh:
            data = json.load(fh)
        return cls(
            weights=tuple(float(w) for w in data["weights"]),
            bias=float(data["bias"]),
            feature_names=tuple(data["feature_names"]),
            trained_at=str(data["trained_at"]),
            sample_count=int(data["sample_count"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": list(self.weights),
            "bias": self.bias,
            "feature_names": list(self.feature_names),
            "trained_at": self.trained_at,
            "sample_count": self.sample_count,
        }


# ---------------------------------------------------------------------------
# Feature engineering — shared by plaintext + FHE paths.
# ---------------------------------------------------------------------------

def _featurize(features: dict[str, Any]) -> list[float]:
    urgency_map = {"routine": 0.0, "urgent": 0.5, "emergent": 1.0}
    return [
        urgency_map.get(str(features.get("urgency", "routine")), 0.0),
        float(features.get("prior_denials", 0)),
        float(features.get("missing_docs_count", 0)),
    ]


# ---------------------------------------------------------------------------
# Training — pure NumPy. Imported lazily so the regular install stays light.
# ---------------------------------------------------------------------------

def train_denial_risk_v1(
    *,
    n_samples: int = 4000,
    seed: int = 1234,
    epochs: int = 600,
    lr: float = 0.5,
) -> DenialRiskModel:
    """Fit a logistic regression on synthetic data and return the model.

    Distributions mirror the FHE calibration set in `fhe_pipeline._synth_calibration`
    so the plaintext baseline and the FHE circuit train on consistent
    signal.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    urgency = rng.choice([0.0, 0.5, 1.0], size=n_samples, p=[0.70, 0.25, 0.05])
    prior_denials = rng.poisson(lam=0.5, size=n_samples).astype(float)
    missing_docs = rng.poisson(lam=0.3, size=n_samples).astype(float)
    x = np.stack([urgency, prior_denials, missing_docs], axis=1)
    # True log-odds the synthetic world uses to generate labels.
    z_true = -1.4 + 1.1 * urgency + 0.55 * prior_denials + 0.9 * missing_docs
    p_true = 1.0 / (1.0 + np.exp(-z_true))
    y = (rng.uniform(size=n_samples) < p_true).astype(float)

    # Train via gradient descent on logistic loss.
    w = np.zeros(3)
    b = 0.0
    for _ in range(epochs):
        z = x @ w + b
        p = 1.0 / (1.0 + np.exp(-z))
        grad_w = (x.T @ (p - y)) / n_samples
        grad_b = float((p - y).mean())
        w -= lr * grad_w
        b -= lr * grad_b

    from datetime import UTC, datetime

    model = DenialRiskModel(
        weights=tuple(float(v) for v in w),
        bias=float(b),
        feature_names=("urgency", "prior_denials", "missing_docs_count"),
        trained_at=datetime.now(UTC).isoformat(),
        sample_count=n_samples,
    )
    return model


def save_weights(model: DenialRiskModel, path: Path | None = None) -> Path:
    target = path or WEIGHTS_PATH
    with target.open("w") as fh:
        json.dump(model.to_dict(), fh, indent=2)
    return target


__all__ = [
    "WEIGHTS_PATH",
    "DenialRiskModel",
    "save_weights",
    "train_denial_risk_v1",
]
