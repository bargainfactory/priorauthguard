"""VoiceOrchestratorAgent end-to-end test with stub backends."""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from pa_guard.agents.privacy_guardian import PrivacyGuardianAgent
from pa_guard.agents.voice_orchestrator import VoiceOrchestratorAgent, VoiceTask
from pa_guard.core.config import Settings, get_settings
from pa_guard.services.fhe_inference import FHEInferenceService
from pa_guard.services.voice_service import VoiceService
from pa_guard.services.zkstark import ZkStarkProver

pytestmark = [pytest.mark.voice, pytest.mark.asyncio]


async def _audio_stream() -> AsyncIterator[bytes]:
    for chunk in (b"\x00\x01\x02", b"\x03\x04\x05", b"\x06\x07"):
        yield chunk


async def test_on_device_inbound_dictation_never_leaves_device() -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = Settings(voice_on_device_enabled=True, voice_cloud_enabled=False)
    voice = VoiceService(settings=settings)
    privacy = PrivacyGuardianAgent()
    fhe = FHEInferenceService(settings=settings)
    prover = ZkStarkProver(settings=settings)

    orch = VoiceOrchestratorAgent(voice=voice, privacy=privacy, fhe=fhe, prover=prover)

    task = VoiceTask(
        direction="inbound-dictation",
        audio=_audio_stream(),
        speaker_role="provider",
    )
    report = await orch.run(request_id=uuid4(), payload=task)

    assert report.raw_audio_left_device is False
    assert len(report.transcript) == 3
    # The orchestrator must always emit a zk-STARK proof id when a prover is wired.
    assert report.proof_id is not None
    # Outcome is determined heuristically — make sure it's a valid literal.
    assert report.outcome.outcome in {
        "approved", "denied", "more-info-requested",
        "transferred", "voicemail", "failed",
    }


async def test_outbound_call_requires_cloud_enabled() -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = Settings(voice_on_device_enabled=True, voice_cloud_enabled=False)
    voice = VoiceService(settings=settings)
    privacy = PrivacyGuardianAgent()
    orch = VoiceOrchestratorAgent(voice=voice, privacy=privacy)

    task = VoiceTask(
        direction="outbound-payer",
        audio=_audio_stream(),
        speaker_role="payer-agent",
        payer_id="anthem-001",
    )
    with pytest.raises(RuntimeError):
        await orch.run(request_id=uuid4(), payload=task)
