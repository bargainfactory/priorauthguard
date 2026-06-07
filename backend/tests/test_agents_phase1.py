"""Phase 1 agent integration tests (Intake / PolicyResearcher /
DocumentGenerator / Submission / DenialAppeal / ComplianceAuditor)."""
from __future__ import annotations

import pytest

from pa_guard.agents.compliance_auditor import AuditInput, ComplianceAuditorAgent
from pa_guard.agents.denial_appeal import AppealInput, DenialAppealAgent
from pa_guard.agents.document_generator import (
    DocumentGenerationInput,
    DocumentGeneratorAgent,
)
from pa_guard.agents.intake import IntakeAgent, IntakeInput
from pa_guard.agents.policy_researcher import PolicyResearcherAgent
from pa_guard.agents.submission import SubmissionAgent, SubmissionInput
from pa_guard.core.config import Jurisdiction
from pa_guard.core.models import (
    DeidentificationReport,
    DeidMethod,
    DenialReport,
    JurisdictionTag,
    PARequest,
    PARequestMeta,
    RawClinicalNote,
    SafeClinicalContext,
    SubmissionChannel,
)

pytestmark = pytest.mark.asyncio


def _request() -> PARequest:
    return PARequest(
        meta=PARequestMeta(
            jurisdiction=JurisdictionTag(jurisdiction=Jurisdiction.US_STATE, state_code="CA"),
            payer_id="anthem",
            procedure_code="64483",
            diagnosis_codes=["M54.16"],
            urgency="routine",
        ),
        safe_context=SafeClinicalContext(
            pseudo_id="pid_" + "a" * 16,
            age_band="45-64",
            cleaned_text=(
                "Patient with chronic lumbar radicular pain. "
                "Failed conservative therapy including physical therapy and "
                "NSAIDs over 6 weeks. Imaging confirms radiculopathy."
            ),
        ),
        deid_report=DeidentificationReport(
            deid_method=DeidMethod.HIPAA_SAFE_HARBOR,
            identifier_counts={},
            content_hash="x" * 64,
        ),
    )


# ---------------------------------------------------------------------------
# IntakeAgent
# ---------------------------------------------------------------------------

async def test_intake_flags_missing_fields() -> None:
    agent = IntakeAgent()
    meta = PARequestMeta(
        jurisdiction=JurisdictionTag(jurisdiction=Jurisdiction.US_FEDERAL),
        payer_id="cms-medicare",
        procedure_code="",
        diagnosis_codes=[],
        urgency="routine",
    )
    note = RawClinicalNote(text="")
    report = await agent.run(meta.request_id, IntakeInput(note=note, meta=meta))
    assert report.clarification is not None
    assert "procedure_code" in report.clarification.missing_fields
    assert "diagnosis_codes" in report.clarification.missing_fields
    assert "note.text" in report.clarification.missing_fields


async def test_intake_passes_when_complete() -> None:
    agent = IntakeAgent()
    meta = PARequestMeta(
        jurisdiction=JurisdictionTag(jurisdiction=Jurisdiction.US_FEDERAL),
        payer_id="cms-medicare",
        procedure_code="64483",
        diagnosis_codes=["M54.16"],
        urgency="routine",
    )
    note = RawClinicalNote(text="Chronic radiculopathy.")
    report = await agent.run(meta.request_id, IntakeInput(note=note, meta=meta))
    assert report.clarification is None


# ---------------------------------------------------------------------------
# PolicyResearcherAgent
# ---------------------------------------------------------------------------

async def test_policy_researcher_returns_evidence() -> None:
    req = _request()
    agent = PolicyResearcherAgent()
    out = await agent.run(req.meta.request_id, req)
    assert out.evidence  # at least one hit
    assert all(0.0 <= e.similarity <= 1.0 for e in out.evidence)


# ---------------------------------------------------------------------------
# DocumentGeneratorAgent
# ---------------------------------------------------------------------------

async def test_document_generator_produces_complete_document() -> None:
    req = _request()
    research = await PolicyResearcherAgent().run(req.meta.request_id, req)
    doc = await DocumentGeneratorAgent().run(
        req.meta.request_id,
        DocumentGenerationInput(request=req, evidence=research.evidence),
    )
    assert doc.procedure_code == req.meta.procedure_code
    assert doc.medical_necessity_narrative
    assert doc.criteria
    assert doc.citations


async def test_urgent_document_calls_out_urgency() -> None:
    req = _request().model_copy(
        update={
            "meta": _request().meta.model_copy(update={"urgency": "urgent"}),
        }
    )
    research = await PolicyResearcherAgent().run(req.meta.request_id, req)
    doc = await DocumentGeneratorAgent().run(
        req.meta.request_id,
        DocumentGenerationInput(request=req, evidence=research.evidence),
    )
    assert "urgent" in doc.medical_necessity_narrative.lower()


# ---------------------------------------------------------------------------
# ComplianceAuditorAgent
# ---------------------------------------------------------------------------

async def test_compliance_auditor_emits_audit() -> None:
    req = _request()
    research = await PolicyResearcherAgent().run(req.meta.request_id, req)
    doc = await DocumentGeneratorAgent().run(
        req.meta.request_id,
        DocumentGenerationInput(request=req, evidence=research.evidence),
    )
    audit = await ComplianceAuditorAgent().run(
        req.meta.request_id, AuditInput(request=req, document=doc)
    )
    assert audit.blocking is False
    assert audit.findings  # info findings always present (CMS, CA)


# ---------------------------------------------------------------------------
# SubmissionAgent
# ---------------------------------------------------------------------------

async def test_submission_emits_receipt() -> None:
    req = _request()
    research = await PolicyResearcherAgent().run(req.meta.request_id, req)
    doc = await DocumentGeneratorAgent().run(
        req.meta.request_id,
        DocumentGenerationInput(request=req, evidence=research.evidence),
    )
    receipt = await SubmissionAgent().run(
        req.meta.request_id,
        SubmissionInput(document=doc, preferred_channel=SubmissionChannel.API),
    )
    assert receipt.payer_id == req.meta.payer_id
    assert receipt.confirmation_code is not None
    assert receipt.channel == SubmissionChannel.API.value


# ---------------------------------------------------------------------------
# DenialAppealAgent
# ---------------------------------------------------------------------------

async def test_denial_appeal_produces_counter_arguments() -> None:
    req = _request()
    research = await PolicyResearcherAgent().run(req.meta.request_id, req)
    doc = await DocumentGeneratorAgent().run(
        req.meta.request_id,
        DocumentGenerationInput(request=req, evidence=research.evidence),
    )
    denial = DenialReport(
        request_id=req.meta.request_id,
        reason_codes=["MN-1", "STEP-2"],
        summary="Insufficient documentation of conservative therapy failure.",
    )
    appeal = await DenialAppealAgent().run(
        req.meta.request_id,
        AppealInput(denial=denial, document=doc, evidence=research.evidence),
    )
    assert len(appeal.counter_arguments) >= 2
    assert appeal.narrative
    assert appeal.denial_id == denial.denial_id


# ---------------------------------------------------------------------------
# End-to-end pipeline assertion (without supervisor) — purely sequencing.
# ---------------------------------------------------------------------------

async def test_full_pipeline_sequential() -> None:
    req = _request()
    research = await PolicyResearcherAgent().run(req.meta.request_id, req)
    doc = await DocumentGeneratorAgent().run(
        req.meta.request_id,
        DocumentGenerationInput(request=req, evidence=research.evidence),
    )
    audit = await ComplianceAuditorAgent().run(
        req.meta.request_id, AuditInput(request=req, document=doc)
    )
    assert audit.blocking is False
    receipt = await SubmissionAgent().run(
        req.meta.request_id,
        SubmissionInput(document=doc),
    )
    assert receipt.confirmation_code is not None
