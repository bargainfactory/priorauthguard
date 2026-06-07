"""PrivacyGuardianAgent integration tests."""
from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from pa_guard.agents.privacy_guardian import IntakePayload, PrivacyGuardianAgent
from pa_guard.core.config import Jurisdiction
from pa_guard.core.models import (
    DeidMethod,
    JurisdictionTag,
    PARequestMeta,
    PAStatus,
    RawClinicalNote,
    SensitivityTier,
    VoiceChannel,
    VoiceTranscriptChunk,
)

pytestmark = [pytest.mark.compliance, pytest.mark.asyncio]


async def test_run_produces_phi_deidentified_request() -> None:
    guardian = PrivacyGuardianAgent()
    note = RawClinicalNote(
        text="Mr. John Smith MRN: AB12345678 ph (415) 555-0142 dob 1972-04-09.",
        patient_first_name="John",
        patient_last_name="Smith",
        patient_dob=date(1972, 4, 9),
        patient_mrn="AB12345678",
    )
    meta = PARequestMeta(
        jurisdiction=JurisdictionTag(
            jurisdiction=Jurisdiction.US_STATE, state_code="CA"
        ),
        payer_id="anthem-001",
        procedure_code="64483",
        diagnosis_codes=["M54.16"],
        urgency="routine",
    )
    payload = IntakePayload(note=note, meta=meta)

    result = await guardian.run(request_id=uuid4(), payload=payload)

    assert result.sensitivity == SensitivityTier.PHI_DEIDENTIFIED.value
    assert result.status == PAStatus.DEIDENTIFIED.value
    assert result.deid_report.deid_method == DeidMethod.HIPAA_SAFE_HARBOR.value
    assert "Smith" not in result.safe_context.cleaned_text
    assert "AB12345678" not in result.safe_context.cleaned_text
    assert "555-0142" not in result.safe_context.cleaned_text
    assert sum(result.deid_report.identifier_counts.values()) >= 4


async def test_transcript_chunk_is_deidentified() -> None:
    guardian = PrivacyGuardianAgent()
    now = datetime.now(tz=UTC)
    chunk = VoiceTranscriptChunk(
        channel=VoiceChannel.ON_DEVICE_WHISPER,
        speaker_role="provider",
        text="Calling about MRN: AB12345678 for Mr. John Smith.",
        started_at=now,
        ended_at=now,
        on_device=True,
    )
    result = await guardian.deidentify_transcript(chunk)
    assert "Smith" not in result.cleaned_text
    assert "AB12345678" not in result.cleaned_text
    assert result.deid_report.deid_method == DeidMethod.HIPAA_SAFE_HARBOR.value
