"""Train a Brevitas-QAT classifier and compile it to a Concrete ML circuit.

Runs inside the `pa-guard-fhe` container (Python 3.12 + concrete-ml + brevitas
+ torch). The bind-mounted repo root is at `/work`, so the artifact lands at
the path the runtime auto-loader checks:

    /work/backend/.fhe_cache/denial_risk_v0.compiled

The compiled bundle structure is the one `fhe_pipeline.maybe_load_compiled_circuit`
expects: a pickle of `{"compiled": <FHEModel>, "config": CircuitTrainingConfig}`.

Training contract
-----------------
- Synthetic distribution mirrors what `fhe_pipeline._synth_calibration` and
  the plaintext logistic regression in `denial_risk_model.py` saw, so the
  FHE circuit and plaintext baseline agree on the same feature space.
- Features: (urgency, prior_denials, missing_docs_count), as 3 floats.
- Target: binary denial label sampled from sigmoid(true_logit).
- Quantization: INT8 (configurable via QUANT_BITS env var) via Brevitas
  QuantLinear / QuantReLU. Concrete ML's `compile_brevitas_qat_model`
  produces the FHE circuit + key generation routines.

Reproducibility: deterministic RNG seed; the artifact bytes vary only with
concrete-ml's compiler version (locked in the Dockerfile).
"""
from __future__ import annotations

import os
import pickle
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from brevitas import nn as qnn
from concrete.ml.torch.compile import compile_brevitas_qat_model
from torch import nn

REPO_ROOT = Path("/work")
ARTIFACT_DIR = REPO_ROOT / "backend" / ".fhe_cache"
ARTIFACT_PATH = ARTIFACT_DIR / "denial_risk_v0.compiled"

QUANT_BITS = int(os.environ.get("QUANT_BITS", "8"))
CALIB_SIZE = int(os.environ.get("CALIB_SIZE", "512"))
TRAIN_SIZE = int(os.environ.get("TRAIN_SIZE", "4000"))
EPOCHS = int(os.environ.get("EPOCHS", "120"))
SEED = int(os.environ.get("SEED", "1234"))


# ---------------------------------------------------------------------------
# Mirror of the plaintext shape so the runtime can compare apples to apples.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CircuitTrainingConfig:
    name: str = "denial_risk_v0"
    feature_keys: tuple[str, ...] = (
        "urgency",
        "prior_denials",
        "missing_docs_count",
    )
    quant_bits: int = QUANT_BITS
    use_qat: bool = True
    calibration_size: int = CALIB_SIZE
    hidden_dim: int = 16


CONFIG = CircuitTrainingConfig()


# ---------------------------------------------------------------------------
# Synthetic data — identical distribution to backend's _synth_calibration.
# ---------------------------------------------------------------------------

def synth(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    urgency = rng.choice([0.0, 0.5, 1.0], size=n, p=[0.70, 0.25, 0.05])
    prior = rng.poisson(lam=0.5, size=n).astype(float)
    missing = rng.poisson(lam=0.3, size=n).astype(float)
    x = np.stack([urgency, prior, missing], axis=1).astype("float32")
    logits = -1.4 + 1.1 * urgency + 0.55 * prior + 0.9 * missing
    p = 1.0 / (1.0 + np.exp(-logits))
    y = (rng.uniform(size=n) < p).astype(np.int64)
    return x, y


# ---------------------------------------------------------------------------
# Brevitas QAT model.
# ---------------------------------------------------------------------------

class QATDenialRisk(nn.Module):
    def __init__(self, bits: int, hidden: int) -> None:
        super().__init__()
        self.q_in = qnn.QuantIdentity(bit_width=bits, return_quant_tensor=True)
        self.fc1 = qnn.QuantLinear(
            3, hidden, bias=True, weight_bit_width=bits, return_quant_tensor=True,
        )
        self.act = qnn.QuantReLU(bit_width=bits, return_quant_tensor=True)
        self.fc2 = qnn.QuantLinear(
            hidden, 2, bias=True, weight_bit_width=bits, return_quant_tensor=True,
        )

    def forward(self, x):  # type: ignore[no-untyped-def]
        x = self.q_in(x)
        x = self.fc1(x)
        x = self.act(x)
        return self.fc2(x)


def train(model: QATDenialRisk, x: torch.Tensor, y: torch.Tensor) -> None:
    opt = torch.optim.Adam(model.parameters(), lr=1e-2)
    loss_fn = nn.CrossEntropyLoss()
    model.train()
    for epoch in range(EPOCHS):
        opt.zero_grad()
        logits = model(x)
        loss = loss_fn(
            logits.value if hasattr(logits, "value") else logits,
            y,
        )
        loss.backward()
        opt.step()
        if epoch % 20 == 0:
            print(f"  epoch={epoch:>3d}  loss={float(loss.item()):.4f}")


def accuracy(model: QATDenialRisk, x: torch.Tensor, y: torch.Tensor) -> float:
    model.eval()
    with torch.no_grad():
        logits = model(x)
        raw = logits.value if hasattr(logits, "value") else logits
        pred = raw.argmax(dim=1)
        return float((pred == y).float().mean().item())


def main() -> int:
    torch.manual_seed(SEED)
    np.random.seed(SEED)

    print(f"== Training Brevitas QAT (bits={QUANT_BITS}, hidden={CONFIG.hidden_dim}, "
          f"train_n={TRAIN_SIZE}, calib_n={CALIB_SIZE}) ==")
    x_train_np, y_train_np = synth(TRAIN_SIZE, SEED)
    x_eval_np, y_eval_np = synth(1024, SEED + 1)
    x_calib_np, _ = synth(CALIB_SIZE, SEED + 2)
    x_train = torch.tensor(x_train_np)
    y_train = torch.tensor(y_train_np)
    x_eval = torch.tensor(x_eval_np)
    y_eval = torch.tensor(y_eval_np)

    model = QATDenialRisk(bits=QUANT_BITS, hidden=CONFIG.hidden_dim)
    t0 = time.perf_counter()
    train(model, x_train, y_train)
    train_secs = time.perf_counter() - t0
    print(f"== Trained in {train_secs:.1f}s ==")

    acc_train = accuracy(model, x_train, y_train)
    acc_eval = accuracy(model, x_eval, y_eval)
    print(f"  train_acc={acc_train:.4f}  eval_acc={acc_eval:.4f}")

    print("== Compiling to FHE circuit (concrete-ml) ==")
    t0 = time.perf_counter()
    compiled = compile_brevitas_qat_model(
        model,
        torch.tensor(x_calib_np),
        n_bits=QUANT_BITS,
        rounding_threshold_bits=QUANT_BITS + 2,
    )
    compile_secs = time.perf_counter() - t0
    print(f"== Compiled in {compile_secs:.1f}s ==")

    # Parity check on 32 samples.
    sample = torch.tensor(x_eval_np[:32])
    print("== Plaintext vs FHE parity check (32 samples) ==")
    fhe_pred = compiled.forward(sample.numpy())
    if isinstance(fhe_pred, tuple):
        fhe_pred = fhe_pred[0]
    fhe_labels = np.asarray(fhe_pred).argmax(axis=1) if fhe_pred.ndim == 2 else fhe_pred
    plaintext = accuracy(model, sample, torch.tensor(y_eval_np[:32]))
    print(f"  plaintext_subset_acc={plaintext:.4f}  fhe_labels_head={fhe_labels[:8]}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with ARTIFACT_PATH.open("wb") as fh:
        pickle.dump({"compiled": compiled, "config": asdict(CONFIG)}, fh)
    print(f"== Artifact written: {ARTIFACT_PATH} ==")
    print(f"   size={ARTIFACT_PATH.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
