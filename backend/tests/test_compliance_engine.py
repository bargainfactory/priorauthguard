"""ComplianceEngine tests across jurisdictions."""
from __future__ import annotations

from uuid import uuid4

import pytest

from pa_guard.compliance.engine import ComplianceEngine
from pa_guard.core.config import Jurisdiction
from pa_guard.core.models import (
    ClinicalCriterion,
    ClinicalCriterionStatus,
    DeidentificationReport,
    DeidMethod,
    JurisdictionTag,
    PADocument,
    PARequest,
    PARequestMeta,
    SafeClinicalContext,
)

pytestmark = pytest.mark.compliance


def _make_request(
    *,
    jurisdiction: Jurisdiction = Jurisdiction.US_FEDERAL,
    state_code: str | None = None,
    province_code: str | None = None,
    procedure_code: str = "64483",
    diagnosis_codes: list[str] | None = None,
    urgency: str = "routine",
    cleaned_text: str = "Patient with chronic lumbar radiculopathy.",
) -> PARequest:
    return PARequest(
        meta=PARequestMeta(
            jurisdiction=JurisdictionTag(
                jurisdiction=jurisdiction,
                state_code=state_code,
                province_code=province_code,
            ),
            payer_id="anthem-001",
            procedure_code=procedure_code,
            diagnosis_codes=diagnosis_codes if diagnosis_codes is not None else ["M54.16"],
            urgency=urgency,  # type: ignore[arg-type]
        ),
        safe_context=SafeClinicalContext(
            pseudo_id="pid_" + "a" * 16,
            age_band="45-64",
            cleaned_text=cleaned_text,
        ),
        deid_report=DeidentificationReport(
            deid_method=DeidMethod.HIPAA_SAFE_HARBOR,
            identifier_counts={},
            content_hash="x" * 64,
        ),
    )


def _make_document(req: PARequest, *, narrative: str = "Medically necessary procedure due to chronic radiculopathy.") -> PADocument:
    return PADocument(
        request_id=req.meta.request_id,
        payer_id=req.meta.payer_id,
        procedure_code=req.meta.procedure_code,
        diagnosis_codes=list(req.meta.diagnosis_codes),
        medical_necessity_narrative=narrative,
        criteria=[
            ClinicalCriterion(
                label="conservative therapy >= 4 weeks",
                status=ClinicalCriterionStatus.MET,
                rationale="Documented PT for 6 weeks.",
                evidence_ids=[uuid4()],
            )
        ],
        citations=[uuid4()],
    )


def test_happy_path_us_federal_passes() -> None:
    req = _make_request()
    doc = _make_document(req)
    audit = ComplianceEngine().audit(req, doc)
    assert audit.blocking is False
    # CMS-0057-F info finding should be surfaced.
    assert any(f.rule_id == "US-FED-001" for f in audit.findings)


def test_us_state_ca_includes_gold_card_info() -> None:
    req = _make_request(jurisdiction=Jurisdiction.US_STATE, state_code="CA")
    doc = _make_document(req)
    audit = ComplianceEngine().audit(req, doc)
    assert any(f.rule_id == "US-CA-001" for f in audit.findings)


def test_us_state_tx_includes_gold_card_info() -> None:
    req = _make_request(jurisdiction=Jurisdiction.US_STATE, state_code="TX")
    audit = ComplianceEngine().audit(req, _make_document(req))
    assert any(f.rule_id == "US-TX-001" for f in audit.findings)


def test_canada_quebec_includes_law25() -> None:
    req = _make_request(jurisdiction=Jurisdiction.CA_PROVINCE, province_code="QC")
    audit = ComplianceEngine().audit(req, _make_document(req))
    assert any(f.rule_id == "CA-QC-001" for f in audit.findings)


def test_uk_pack_runs() -> None:
    req = _make_request(jurisdiction=Jurisdiction.UK)
    audit = ComplianceEngine().audit(req, _make_document(req))
    assert any(f.rule_id.startswith("UK-") for f in audit.findings)


def test_missing_procedure_code_blocks() -> None:
    req = _make_request(procedure_code="")
    audit = ComplianceEngine().audit(req, _make_document(req, narrative="ok"))
    assert audit.blocking is True
    assert any(f.rule_id == "UNIV-001" and f.severity == "blocker" for f in audit.findings)


def test_missing_diagnosis_blocks() -> None:
    req = _make_request(diagnosis_codes=[])
    audit = ComplianceEngine().audit(req, _make_document(req))
    assert audit.blocking is True
    assert any(f.rule_id == "UNIV-002" for f in audit.findings)


def test_urgent_without_urgency_in_narrative_blocks() -> None:
    req = _make_request(urgency="urgent")
    doc = _make_document(req, narrative="Patient needs procedure soon for chronic pain.")
    audit = ComplianceEngine().audit(req, doc)
    blockers = [f for f in audit.findings if f.severity == "blocker"]
    assert any(b.rule_id == "UNIV-008" for b in blockers)


def test_urgent_with_urgency_keyword_passes() -> None:
    req = _make_request(urgency="urgent")
    doc = _make_document(
        req,
        narrative="URGENT — patient with acute radiculopathy requires expedited review.",
    )
    audit = ComplianceEngine().audit(req, doc)
    assert not any(
        f.rule_id == "UNIV-008" and f.severity == "blocker" for f in audit.findings
    )
