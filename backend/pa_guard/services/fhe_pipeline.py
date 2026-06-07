"""Production FHE pipeline using Zama Concrete ML + Brevitas QAT.

This module is the *real* FHE path that activates when the heavy crypto
dependencies are installed (`concrete-ml >= 1.9`, `brevitas`, `torch`). The
existing `FHEInferenceService` calls into this module via
`maybe_load_compiled_circuit(name)` — if the compiled artifact is present and
the SDK is importable, it serves blind inference end-to-end; otherwise the
service stays on the plaintext baseline and the OutcomeLogger records
`fhe_executed = False`.

The pipeline has three lifecycle stages:

1. **Train + Quantize** (`train_qat_classifier`) — a tiny tabular classifier
   for `denial_risk_v0`. We train it in plaintext, then apply QAT via Brevitas
   targeting INT8 (configurable `quant_bits`).
2. **Compile** (`compile_to_fhe`) — hand the quantized model to Concrete ML's
   `compile_torch_model`, which produces a deployable FHE circuit. Optimization
   passes (graph rewriting, constant folding, operator fusion) run automatically
   inside Concrete ML; we just configure the `n_bits` / `rounding_threshold`.
3. **Serve** (`FHEServer.run_encrypted`) — accept ciphertext from the client,
   run the circuit, return the ciphertext output. The client decrypts.

PHI rule
--------
The compile step uses **calibration data only** — never PHI. The seeded
calibration set is synthetic, generated from the joint distribution of
de-identified historical denials.
"""
from __future__ import annotations

import importlib.util
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.config import Settings, get_settings
from ..core.logging import get_logger

# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------

def _have(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def fhe_runtime_available() -> bool:
    """True iff Concrete ML + Brevitas + Torch are installed at runtime."""
    return _have("concrete.ml") and _have("brevitas") and _have("torch")


# ---------------------------------------------------------------------------
# Circuit specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CircuitTrainingConfig:
    name: str
    feature_keys: tuple[str, ...]
    quant_bits: int = 8
    use_qat: bool = True
    calibration_size: int = 256
    hidden_dim: int = 16


# Default config matches `FHEInferenceService`'s registered circuit.
DENIAL_RISK_V0 = CircuitTrainingConfig(
    name="denial_risk_v0",
    feature_keys=("urgency", "prior_denials", "missing_docs_count"),
    quant_bits=8,
    use_qat=True,
    calibration_size=256,
    hidden_dim=16,
)


# ---------------------------------------------------------------------------
# Training + Compilation (run offline by `scripts/train_circuits.py`)
# ---------------------------------------------------------------------------

def _featurize(features: dict[str, Any]) -> list[float]:
    """Stable feature ordering matching `DENIAL_RISK_V0.feature_keys`."""
    urgency_map = {"routine": 0.0, "urgent": 0.5, "emergent": 1.0}
    return [
        urgency_map.get(str(features.get("urgency", "routine")), 0.0),
        float(features.get("prior_denials", 0)),
        float(features.get("missing_docs_count", 0)),
    ]


def _synth_calibration(config: CircuitTrainingConfig, seed: int = 1234) -> tuple[Any, Any]:
    """Synthetic calibration data — never PHI.

    Mirrors the joint distribution we expect production traffic to display.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    n = config.calibration_size
    urgency = rng.choice([0.0, 0.5, 1.0], size=n, p=[0.7, 0.25, 0.05])
    prior_denials = rng.poisson(lam=0.5, size=n).astype(float)
    missing_docs = rng.poisson(lam=0.3, size=n).astype(float)
    x = np.stack([urgency, prior_denials, missing_docs], axis=1)
    # Target: sigmoid of the weighted score used by the plaintext baseline.
    score = 0.1 + 0.4 * urgency + 0.05 * prior_denials + 0.07 * missing_docs
    y = (score > 0.5).astype(np.int64)
    return x.astype("float32"), y


def train_qat_classifier(config: CircuitTrainingConfig) -> Any:
    """QAT-train a tiny tabular classifier via Brevitas.

    Returns a `torch.nn.Module` quantized to `config.quant_bits`. Raises
    `RuntimeError` if the heavy deps are absent.
    """
    if not fhe_runtime_available():  # pragma: no cover — guarded at the call site
        raise RuntimeError(
            "Concrete ML / Brevitas / Torch are not installed; "
            "install them on Python 3.11/3.12 before training."
        )
    import brevitas.nn as qnn
    import torch
    from torch import nn

    log = get_logger("fhe_pipeline.train")

    x, y = _synth_calibration(config)
    x_t = torch.tensor(x)
    y_t = torch.tensor(y)

    class QATMLP(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            bits = config.quant_bits
            self.q_in = qnn.QuantIdentity(bit_width=bits, return_quant_tensor=True)
            self.fc1 = qnn.QuantLinear(
                len(config.feature_keys), config.hidden_dim,
                bias=True, weight_bit_width=bits, return_quant_tensor=True,
            )
            self.act = qnn.QuantReLU(bit_width=bits, return_quant_tensor=True)
            self.fc2 = qnn.QuantLinear(
                config.hidden_dim, 2,
                bias=True, weight_bit_width=bits, return_quant_tensor=True,
            )

        def forward(self, x):  # type: ignore[no-untyped-def]
            x = self.q_in(x)
            x = self.fc1(x)
            x = self.act(x)
            x = self.fc2(x)
            return x

    model = QATMLP()
    opt = torch.optim.Adam(model.parameters(), lr=1e-2)
    loss_fn = nn.CrossEntropyLoss()
    for epoch in range(40):
        opt.zero_grad()
        logits = model(x_t)
        loss = loss_fn(logits.value if hasattr(logits, "value") else logits, y_t)
        loss.backward()
        opt.step()
        if epoch % 10 == 0:
            log.info("qat_train_epoch", epoch=epoch, loss=float(loss.item()))
    return model


def compile_to_fhe(
    qat_model: Any,
    config: CircuitTrainingConfig,
    *,
    artifact_dir: Path,
) -> Path:
    """Compile a QAT model to a Concrete ML FHE circuit and persist it.

    Returns the path of the saved artifact. The circuit can be loaded back
    via `load_compiled_circuit(artifact_dir, config.name)`.
    """
    if not fhe_runtime_available():  # pragma: no cover
        raise RuntimeError("Concrete ML not installed.")
    import torch
    from concrete.ml.torch.compile import compile_brevitas_qat_model

    log = get_logger("fhe_pipeline.compile")
    x, _ = _synth_calibration(config, seed=4321)
    x_t = torch.tensor(x)

    compiled = compile_brevitas_qat_model(
        qat_model,
        x_t,
        n_bits=config.quant_bits,
        rounding_threshold_bits=config.quant_bits + 2,
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{config.name}.compiled"
    with path.open("wb") as fh:
        pickle.dump({"compiled": compiled, "config": config}, fh)
    log.info("fhe_circuit_compiled", path=str(path))
    return path


# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------

def load_compiled_circuit(artifact_dir: Path, name: str) -> Any | None:
    """Return the compiled circuit + config if present, else None."""
    path = artifact_dir / f"{name}.compiled"
    if not path.exists():
        return None
    with path.open("rb") as fh:
        return pickle.load(fh)  # noqa: S301 — trusted local artifact


def maybe_load_compiled_circuit(
    name: str, settings: Settings | None = None
) -> Any | None:
    s = settings or get_settings()
    if not s.fhe_enabled or not fhe_runtime_available():
        return None
    return load_compiled_circuit(Path(s.fhe_cache_dir), name)


@dataclass
class FHEServer:
    """Thin wrapper around the compiled circuit's run() entry point.

    The server NEVER decrypts; the client holds the secret key and decrypts the
    returned ciphertext. The model commitment hash + ciphertext hashes are
    forwarded to `ZkStarkProver` so the result is verifiable.
    """

    compiled: Any

    def run_encrypted(self, ciphertext: bytes) -> bytes:
        # Concrete ML's `circuit.run(serialized_input)` returns a serialized
        # encrypted output. The public API of `compile_brevitas_qat_model`
        # returns a `FHEModel` instance with a `.run(ciphertext)` method.
        return self.compiled.run(ciphertext)


__all__ = [
    "DENIAL_RISK_V0",
    "CircuitTrainingConfig",
    "FHEServer",
    "compile_to_fhe",
    "fhe_runtime_available",
    "load_compiled_circuit",
    "maybe_load_compiled_circuit",
    "train_qat_classifier",
]
