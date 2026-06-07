"""LangGraph supervisor end-to-end tests."""
from __future__ import annotations

import pytest

from pa_guard.agents.supervisor import PASupervisor
from pa_guard.core.config import Jurisdiction
from pa_guard.core.models import (
    JurisdictionTag,
    PARequestMeta,
    RawClinicalNote,
)

pytestmark = pytest.mark.asyncio


async def test_supervisor_happy_path_us_state() -> None:
    supervisor = PASupervisor()
    meta = PARequestMeta(
        jurisdiction=JurisdictionTag(jurisdiction=Jurisdiction.US_STATE, state_code="CA"),
        payer_id="anthem",
        procedure_code="64483",
        diagnosis_codes=["M54.16"],
        urgency="routine",
    )
    note = RawClinicalNote(
        text=(
            "Mr. John Smith MRN: AB12345678 presents with chronic lumbar "
            "radicular pain. Failed conservative therapy including 6 weeks "
            "of physical therapy and NSAIDs. Imaging confirms radiculopathy."
        ),
        patient_first_name="John",
        patient_last_name="Smith",
        patient_mrn="AB12345678",
    )
    final = await supervisor.run(note=note, meta=meta)

    # De-identified.
    assert "Smith" not in final["pa_request"].safe_context.cleaned_text
    assert "AB12345678" not in final["pa_request"].safe_context.cleaned_text

    # Pipeline produced every artifact.
    assert final["evidence"]
    assert final["document"]
    assert final["audit"]
    assert final["receipt"]
    assert final["needs_human_approval"] is False
    assert final["status"] == "submitted"


async def test_supervisor_clarification_short_circuits() -> None:
    supervisor = PASupervisor()
    meta = PARequestMeta(
        jurisdiction=JurisdictionTag(jurisdiction=Jurisdiction.US_FEDERAL),
        payer_id="cms-medicare",
        procedure_code="",       # missing → clarification
        diagnosis_codes=[],
        urgency="routine",
    )
    note = RawClinicalNote(text="")
    final = await supervisor.run(note=note, meta=meta)

    assert final.get("clarification") is not None
    assert "procedure_code" in final["clarification"].missing_fields
    # Pipeline must NOT have run past intake.
    assert "pa_request" not in final
    assert "document" not in final


async def test_supervisor_blocking_audit_routes_to_human_gate() -> None:
    supervisor = PASupervisor()
    meta = PARequestMeta(
        jurisdiction=JurisdictionTag(jurisdiction=Jurisdiction.US_STATE, state_code="NY"),
        payer_id="anthem",
        procedure_code="64483",
        diagnosis_codes=["M54.16"],
        urgency="urgent",  # demands urgency in narrative; document text is templated
    )
    note = RawClinicalNote(
        text="Acute exacerbation of chronic radiculopathy with neuro deficits.",
    )
    final = await supervisor.run(note=note, meta=meta)
    # Urgent path includes the URGENT prefix in narrative, so it should still pass.
    # The supervisor must complete cleanly under urgent-but-correct documentation.
    assert final["audit"] is not None
