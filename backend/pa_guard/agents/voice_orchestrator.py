"""VoiceOrchestratorAgent — hybrid voice pipeline coordinator.

Routes audio through the **correct** channel (on-device Whisper for
clinician dictation; cloud STT for payer calls), and pushes every transcript
chunk through `PrivacyGuardianAgent` for Safe Harbor de-identification
**before** anything is persisted, logged, or fed to downstream agents.

Phase 0 deliverables
--------------------
* Async streaming interface for both directions.
* Aggregated `VoiceCallOutcome` per call (suitable for self-critique).
* Hooks for `FHEInferenceService.infer` (risk scoring) and `ZkStarkProver.prove`
  (verifiable proof of outcome) — both ready to flip on in Phase 2.
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID, uuid4

from ..core.models import VoiceCallOutcome, VoiceChannel
from ..services.fhe_inference import FHEInferenceService
from ..services.voice_service import VoiceService
from ..services.zkstark import StatementInputs, ZkStarkProver
from .base import BaseAgent
from .privacy_guardian import PrivacyGuardianAgent, TranscriptResult


@dataclass
class VoiceTask:
    """A single voice task (inbound dictation or outbound payer call)."""

    direction: Literal["inbound-dictation", "outbound-payer"]
    audio: AsyncIterator[bytes]
    speaker_role: Literal["provider", "payer-agent", "patient", "unknown"]
    payer_id: str | None = None
    request_id: UUID = field(default_factory=uuid4)


@dataclass
class VoiceRunReport:
    """Aggregate run report for one voice task — feeds OutcomeLogger."""

    outcome: VoiceCallOutcome
    transcript: list[TranscriptResult]
    fhe_risk_score: float | None
    proof_id: UUID | None
    raw_audio_left_device: bool


class VoiceOrchestratorAgent(BaseAgent[VoiceTask, VoiceRunReport]):
    """Coordinates a voice session end-to-end with privacy guarantees."""

    def __init__(
        self,
        voice: VoiceService,
        privacy: PrivacyGuardianAgent,
        fhe: FHEInferenceService | None = None,
        prover: ZkStarkProver | None = None,
    ) -> None:
        super().__init__(name="VoiceOrchestratorAgent")
        self._voice = voice
        self._privacy = privacy
        self._fhe = fhe
        self._prover = prover

    async def _run(self, payload: VoiceTask) -> VoiceRunReport:
        started = time.perf_counter()

        # 1. Route to the correct STT channel.
        if payload.direction == "inbound-dictation":
            stream = self._voice.transcribe_on_device(
                payload.audio, speaker_role=payload.speaker_role
            )
            channel = VoiceChannel.ON_DEVICE_WHISPER
            raw_left_device = False
        else:
            stream = self._voice.transcribe_cloud(
                payload.audio, speaker_role=payload.speaker_role
            )
            channel = VoiceChannel.CLOUD_DEEPGRAM
            raw_left_device = True

        # 2. De-identify every chunk *before* it lands anywhere persistent.
        deid_chunks: list[TranscriptResult] = []
        async for chunk in stream:
            cleaned = await self._privacy.deidentify_transcript(chunk)
            deid_chunks.append(cleaned)

        # 3. Summary text from de-identified chunks only.
        cleaned_concat = " ".join(c.cleaned_text for c in deid_chunks).strip()
        summary = cleaned_concat[:1024] or "(no transcript)"

        # 4. Optional FHE risk scoring (no-op until Phase 2 enables FHE).
        risk_score: float | None = None
        if self._fhe is not None:
            risk_score = await self._maybe_score_call(deid_chunks)

        # 5. Heuristic outcome classification — Phase 1 replaces this with a
        #    proper classifier (and the classifier itself runs under FHE).
        outcome_kind = self._classify_outcome(cleaned_concat)

        outcome = VoiceCallOutcome(
            channel=channel,
            payer_id=payload.payer_id or "unknown",
            outcome=outcome_kind,
            duration_seconds=time.perf_counter() - started,
            summary=summary,
        )

        # 6. Optional zk-STARK proof binding (channel, outcome, transcript_hash).
        proof_id: UUID | None = None
        if self._prover is not None:
            from blake3 import blake3

            transcript_hash = blake3(cleaned_concat.encode()).hexdigest()
            output_hash = blake3(outcome_kind.encode()).hexdigest()
            proof = await self._prover.prove(
                StatementInputs(
                    model_commitment="voice-orchestrator-v0",
                    input_hash=transcript_hash,
                    output_hash=output_hash,
                )
            )
            proof_id = proof.proof_id
            outcome = outcome.model_copy(update={"proof_id": proof_id})

        return VoiceRunReport(
            outcome=outcome,
            transcript=deid_chunks,
            fhe_risk_score=risk_score,
            proof_id=proof_id,
            raw_audio_left_device=raw_left_device,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _maybe_score_call(
        self, deid_chunks: list[TranscriptResult]
    ) -> float | None:
        if not self._fhe:
            return None
        from ..core.models import FHEInferenceRequest

        denial_hits = sum(
            1 for c in deid_chunks if "denied" in c.cleaned_text.lower()
        )
        try:
            result = await self._fhe.infer(
                FHEInferenceRequest(
                    circuit_name="denial_risk_v0",
                    features={
                        "urgency": "routine",
                        "prior_denials": float(denial_hits),
                        "missing_docs_count": 0.0,
                    },
                )
            )
            return float(result.prediction) if isinstance(result.prediction, (int, float)) else None
        except Exception as exc:  # pragma: no cover — defensive
            self._log.warning("fhe_scoring_skipped", error=str(exc))
            return None

    @staticmethod
    def _classify_outcome(
        text: str,
    ) -> Literal[
        "approved", "denied", "more-info-requested", "transferred", "voicemail", "failed"
    ]:
        lowered = text.lower()
        if "approved" in lowered:
            return "approved"
        if "denied" in lowered or "denial" in lowered:
            return "denied"
        if "additional information" in lowered or "more info" in lowered:
            return "more-info-requested"
        if "transfer" in lowered:
            return "transferred"
        if "voicemail" in lowered or "leave a message" in lowered:
            return "voicemail"
        return "failed" if not lowered.strip() else "more-info-requested"

    # ------------------------------------------------------------------
    # KPIs for self-critique
    # ------------------------------------------------------------------

    def _extra_kpis(
        self, payload: VoiceTask, result: VoiceRunReport | None
    ) -> dict[str, float]:
        if result is None:
            return {}
        total_redactions = float(
            sum(
                sum(c.deid_report.identifier_counts.values())
                for c in result.transcript
            )
        )
        return {
            "transcript_chunks": float(len(result.transcript)),
            "total_identifiers_redacted": total_redactions,
            "raw_audio_left_device": 1.0 if result.raw_audio_left_device else 0.0,
            "fhe_risk_score": result.fhe_risk_score if result.fhe_risk_score is not None else -1.0,
            "duration_seconds": result.outcome.duration_seconds,
        }


__all__ = ["VoiceOrchestratorAgent", "VoiceRunReport", "VoiceTask"]
