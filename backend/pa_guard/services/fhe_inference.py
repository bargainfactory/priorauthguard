"""FHE inference service — Zama Concrete ML pattern (Phase 0 skeleton).

This module encodes the *shape* of the production FHE inference path so the
rest of the platform can be built against a stable interface; the actual
Concrete ML circuits land in **Phase 2**.

Production pattern (Phase 2 implementation target)
--------------------------------------------------
1. **Train / Quantize in plaintext** — preferred path is QAT with Brevitas
   targeting INT8 (6-8 bits acceptable); PTQ as fallback for legacy weights.
2. **Compile to FHE circuit** — `concrete.ml.compile_torch_model(...)` (or the
   equivalent sklearn/xgb path) produces a `CompiledModel` saved under
   `Settings.fhe_cache_dir / circuit_name`.
3. **Client encryption** — the *client* generates keys, encrypts feature
   inputs, and sends ciphertexts (we never see the plaintext server-side).
4. **Server execution** — `CompiledModel.run(ciphertext)` performs blind
   computation.
5. **Client decryption** — client decrypts the result with its private key.
6. **zk-STARK** — alongside the encrypted output, we emit a proof binding
   `(model_commitment, input_hash, output_hash)`.

Circuit optimizations to apply at compile time:
- Graph rewriting / constant folding (Concrete ML default).
- Operator fusion for tight conv/matmul → activation chains.
- Bit-width reduction per layer where accuracy allows.

This skeleton implements steps **(1) interface + (4) execute stub** and emits
the bookkeeping needed by `OutcomeLogger` so Phase 2 only needs to drop in
real circuits.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.models import FHEInferenceRequest, FHEInferenceResult, SensitivityTier

# ---------------------------------------------------------------------------
# Circuit registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CircuitSpec:
    """Static metadata about a registered FHE circuit.

    `model_commitment` is a hash binding the circuit's weights so zk-STARK
    proofs can attest "this output came from THIS exact model."
    """

    name: str
    quant_bits: int
    use_qat: bool
    feature_keys: tuple[str, ...]
    output_type: str  # "score", "class", "embedding"
    model_commitment: str


@dataclass
class _CompiledCircuit:
    """Holds a (placeholder) compiled circuit and bookkeeping."""

    spec: CircuitSpec
    artifact_path: Path
    plaintext_baseline_latency_ms: float | None = None
    # In Phase 2 this becomes a real `concrete.ml.deployment.FHEModel` handle.
    handle: object | None = None
    metrics: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Plaintext baseline fallback (used in Phase 0 + as a sanity check in Phase 2)
# ---------------------------------------------------------------------------

class PlaintextBaseline(Protocol):
    """Reference plaintext model so the same circuit can be evaluated for
    accuracy/latency comparison (the Phase 2 OutcomeLogger persists these)."""

    def predict(self, features: dict[str, float | int | str]) -> float | int | str: ...


class _DenialRiskBaseline:
    """A trivial linear-ish denial-risk scorer used only as a stand-in.

    Real circuit (Phase 2) is a small QAT-Brevitas tabular classifier; this
    keeps the integration testable end-to-end *today*.
    """

    def predict(self, features: dict[str, float | int | str]) -> float:
        # Crude denial-risk heuristic on a few well-known signals.
        urgency = str(features.get("urgency", "routine"))
        prior_denials = float(features.get("prior_denials", 0))
        missing_docs = float(features.get("missing_docs_count", 0))
        score = 0.10
        score += 0.20 if urgency == "urgent" else 0.0
        score += 0.05 * prior_denials
        score += 0.07 * missing_docs
        return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class FHEInferenceService:
    """Async front-door for all FHE inference calls.

    Phase 0 behavior
    ----------------
    * Maintains the **circuit registry** and metadata.
    * Computes a baseline result + latency using a plaintext model so the rest
      of the platform can develop against stable outputs.
    * Returns `FHEInferenceResult.fhe_executed = False` until Phase 2 drops in
      the compiled Concrete ML circuits.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        baselines: dict[str, PlaintextBaseline] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._log = get_logger("FHEInferenceService")
        self._registry: dict[str, _CompiledCircuit] = {}
        self._baselines: dict[str, PlaintextBaseline] = baselines or {
            "denial_risk_v0": _DenialRiskBaseline(),
        }
        self._register_default_circuits()

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def _register_default_circuits(self) -> None:
        self._settings.fhe_cache_dir.mkdir(parents=True, exist_ok=True)
        denial_risk = CircuitSpec(
            name="denial_risk_v0",
            quant_bits=self._settings.fhe_quant_bits,
            use_qat=self._settings.fhe_use_qat,
            feature_keys=("urgency", "prior_denials", "missing_docs_count"),
            output_type="score",
            model_commitment=_commit_to_circuit("denial_risk_v0"),
        )
        self._registry[denial_risk.name] = _CompiledCircuit(
            spec=denial_risk,
            artifact_path=self._settings.fhe_cache_dir / denial_risk.name,
        )
        self._log.info(
            "fhe_circuit_registered",
            circuit=denial_risk.name,
            quant_bits=denial_risk.quant_bits,
            use_qat=denial_risk.use_qat,
            fhe_enabled=self._settings.fhe_enabled,
        )

    def list_circuits(self) -> list[CircuitSpec]:
        return [c.spec for c in self._registry.values()]

    # ------------------------------------------------------------------
    # Public inference API
    # ------------------------------------------------------------------

    async def infer(self, req: FHEInferenceRequest) -> FHEInferenceResult:
        circuit = self._registry.get(req.circuit_name)
        if circuit is None:
            raise KeyError(f"Unknown FHE circuit: {req.circuit_name!r}")

        self._validate_features(circuit.spec, req.features)
        self._validate_sensitivity(req.sensitivity)

        # --- Plaintext baseline (always runs in Phase 0) ---
        t0 = time.perf_counter()
        baseline = self._baselines.get(req.circuit_name)
        if baseline is None:
            raise RuntimeError(
                f"No plaintext baseline registered for circuit {req.circuit_name!r}; "
                "Phase 0 requires baselines to keep downstream agents deterministic."
            )
        prediction = baseline.predict(req.features)
        baseline_latency_ms = (time.perf_counter() - t0) * 1000

        # --- FHE execution (Phase 2 plug-in) ---
        fhe_executed = False
        fhe_latency_ms = baseline_latency_ms
        if self._settings.fhe_enabled and circuit.handle is not None:
            fhe_latency_ms = await self._run_fhe(circuit, req)
            fhe_executed = True

        confidence: float | None = None
        if isinstance(prediction, float):
            # Use distance-from-decision-boundary as a rough confidence proxy.
            confidence = float(min(1.0, abs(prediction - 0.5) * 2))

        result = FHEInferenceResult(
            circuit_name=req.circuit_name,
            prediction=prediction,
            confidence=confidence,
            latency_ms=fhe_latency_ms,
            plaintext_baseline_latency_ms=baseline_latency_ms,
            fhe_executed=fhe_executed,
            proof_id=None,  # zk-STARK wired in Phase 2.
        )
        self._log.info(
            "fhe_inference_completed",
            circuit=req.circuit_name,
            fhe_executed=fhe_executed,
            latency_ms=result.latency_ms,
            baseline_latency_ms=baseline_latency_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Phase 2 hook
    # ------------------------------------------------------------------

    async def _run_fhe(
        self,
        circuit: _CompiledCircuit,
        req: FHEInferenceRequest,
    ) -> float:
        """Run the compiled Concrete ML circuit.

        Phase 0 returns a synthetic small latency so downstream consumers can
        exercise the metrics path. Phase 2 replaces this with an actual
        `circuit.handle.run(ciphertext)` call (`concrete.ml.deployment.FHEModelServer`).
        """
        await asyncio.sleep(0)  # yield to the event loop
        synthetic_latency = 12.5  # ms — placeholder until the real circuit lands
        return synthetic_latency

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_features(
        spec: CircuitSpec, features: dict[str, float | int | str]
    ) -> None:
        missing = [k for k in spec.feature_keys if k not in features]
        if missing:
            raise ValueError(
                f"Circuit {spec.name!r} missing required features: {missing}"
            )

    @staticmethod
    def _validate_sensitivity(tier: SensitivityTier | str) -> None:
        # `use_enum_values=True` on the model means we may see the str value
        # at runtime rather than the enum instance — compare on equality
        # (StrEnum supports cross-type equality), never with `is`.
        if tier == SensitivityTier.PHI_RAW or tier == SensitivityTier.PHI_RAW.value:
            raise PermissionError(
                "FHEInferenceService refuses PHI_RAW input — de-identify or "
                "client-encrypt first."
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit_to_circuit(name: str) -> str:
    """Stable commitment hash for a circuit (placeholder until Phase 2).

    Phase 2 hashes the actual compiled-model bytes; Phase 0 hashes the name so
    the contract / proof bookkeeping path can be exercised end-to-end.
    """
    return hashlib.sha256(f"phase0::{name}".encode()).hexdigest()


__all__ = ["CircuitSpec", "FHEInferenceService"]
