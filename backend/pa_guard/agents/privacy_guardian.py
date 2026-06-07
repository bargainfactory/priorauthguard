"""PrivacyGuardianAgent — the privacy gatekeeper.

Responsibilities (Phase 0):
1. Run **HIPAA Safe Harbor** de-identification on every PHI-bearing payload
   the moment it enters the system (clinical note OR voice transcript chunk).
2. Build a `PARequest` from a `RawClinicalNote` so downstream agents only
   see the de-identified `SafeClinicalContext` + auditable `DeidentificationReport`.
3. Tag downstream payloads with the correct `SensitivityTier` so the FHE
   service can reject misrouted PHI.

Future phases:
- Phase 1: add a learned NER overlay on top of the Safe Harbor regex pass.
- Phase 2: produce zk-STARK proofs binding (raw_hash, deid_hash) for audit.

The agent inherits self-critique automatically via `BaseAgent`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from blake3 import blake3

from ..compliance.safe_harbor import SafeHarborEngine
from ..core.models import (
    DeidentificationReport,
    DeidMethod,
    PARequest,
    PARequestMeta,
    PatientPseudoId,
    RawClinicalNote,
    SensitivityTier,
    VoiceTranscriptChunk,
)
from ..services.deidentification import DeidentificationService, SafeHarborService
from .base import BaseAgent


@dataclass(frozen=True)
class IntakePayload:
    """Bundle a raw note with the metadata needed to assemble a PARequest."""

    note: RawClinicalNote
    meta: PARequestMeta
    pseudo_id: PatientPseudoId | None = None


@dataclass(frozen=True)
class TranscriptPayload:
    """A voice transcript chunk that needs de-identification."""

    chunk: VoiceTranscriptChunk


@dataclass(frozen=True)
class TranscriptResult:
    chunk_id: UUID
    cleaned_text: str
    deid_report: DeidentificationReport
    speaker_role: Literal["provider", "payer-agent", "patient", "unknown"]


class PrivacyGuardianAgent(BaseAgent[IntakePayload, PARequest]):
    """Gatekeeper that applies Safe Harbor before anything else runs."""

    def __init__(
        self,
        deid_service: DeidentificationService | None = None,
    ) -> None:
        super().__init__(name="PrivacyGuardianAgent")
        self._deid: DeidentificationService = deid_service or SafeHarborService()

    # ------------------------------------------------------------------
    # Primary path: clinical note → PARequest
    # ------------------------------------------------------------------

    async def _run(self, payload: IntakePayload) -> PARequest:
        report, safe_ctx = await self._deid.deidentify(
            payload.note, pseudo_id=payload.pseudo_id
        )
        return PARequest(
            meta=payload.meta,
            safe_context=safe_ctx,
            deid_report=report,
            sensitivity=SensitivityTier.PHI_DEIDENTIFIED,
        )

    # ------------------------------------------------------------------
    # Secondary path: voice transcript chunk → safe transcript
    # ------------------------------------------------------------------

    async def deidentify_transcript(
        self, chunk: VoiceTranscriptChunk
    ) -> TranscriptResult:
        """De-identify a single voice transcript chunk in place.

        Used by `VoiceOrchestratorAgent`; bypasses the `run` lifecycle because
        chunks are high-frequency and each one carrying a critique would
        overwhelm `OutcomeLogger`. The orchestrator emits one aggregate
        critique per call instead.
        """
        # Direct call into the engine for speed; no per-chunk pseudo-id needed.
        engine = SafeHarborEngine()
        cleaned, counts = engine.deidentify_text(chunk.text)
        report = DeidentificationReport(
            deid_method=DeidMethod.HIPAA_SAFE_HARBOR,
            identifier_counts=dict(counts),
            content_hash=blake3(cleaned.encode("utf-8")).hexdigest(),
            notes=["Per-chunk Safe Harbor pass on voice transcript."],
        )
        return TranscriptResult(
            chunk_id=chunk.chunk_id,
            cleaned_text=cleaned,
            deid_report=report,
            speaker_role=chunk.speaker_role,  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------------
    # Self-critique KPIs
    # ------------------------------------------------------------------

    def _extra_kpis(
        self, payload: IntakePayload, result: PARequest | None
    ) -> dict[str, float]:
        if result is None:
            return {}
        total_redacted = float(sum(result.deid_report.identifier_counts.values()))
        return {
            "identifiers_redacted": total_redacted,
            "deid_method_is_safe_harbor": 1.0,
        }


__all__ = ["IntakePayload", "PrivacyGuardianAgent", "TranscriptPayload", "TranscriptResult"]
