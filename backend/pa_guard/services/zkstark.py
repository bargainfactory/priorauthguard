"""zk-STARK proof service (Phase 0 skeleton).

We use a transparent (no-trusted-setup) STARK to prove the statement:

    "There exists a private input X such that:
        hash(X) == input_hash
        AND model(model_commitment, X) == output
        AND hash(output) == output_hash"

without revealing X.

The Phase 0 implementation returns a **structurally correct** proof object so
the rest of the system can develop against the verifier interface. Phase 2
swaps in the real prover.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.models import ZkStarkProof


@dataclass(frozen=True)
class StatementInputs:
    model_commitment: str
    input_hash: str
    output_hash: str


class ZkStarkProver:
    """Generates verifiable proofs binding (model, input, output)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._log = get_logger("ZkStarkProver")

    async def prove(self, inputs: StatementInputs) -> ZkStarkProof:
        if not self._settings.zkstark_enabled:
            self._log.info("zkstark_disabled_returning_stub_proof")
        # Phase 0 stub: deterministic "proof blob" derived from the inputs.
        material = "|".join([
            inputs.model_commitment,
            inputs.input_hash,
            inputs.output_hash,
        ]).encode()
        blob = hashlib.sha3_512(material).digest()
        return ZkStarkProof(
            model_commitment=inputs.model_commitment,
            input_hash=inputs.input_hash,
            output_hash=inputs.output_hash,
            proof_blob=blob,
        )


class ZkStarkVerifier:
    """Verifies proofs produced by `ZkStarkProver`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._log = get_logger("ZkStarkVerifier")

    async def verify(self, proof: ZkStarkProof) -> bool:
        material = "|".join([
            proof.model_commitment,
            proof.input_hash,
            proof.output_hash,
        ]).encode()
        expected = hashlib.sha3_512(material).digest()
        ok = expected == proof.proof_blob
        self._log.info("zkstark_verified", ok=ok, proof_id=str(proof.proof_id))
        return ok


__all__ = ["StatementInputs", "ZkStarkProver", "ZkStarkVerifier"]
