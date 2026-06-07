"""OPA policy overlay tests — engine + ComplianceEngine integration."""
from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from pa_guard.compliance.engine import ComplianceEngine
from pa_guard.compliance.opa import OpaPolicyEngine
from pa_guard.core.config import Jurisdiction, Settings
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


def _make_request(tenant: str = "acme") -> PARequest:
    return PARequest(
        meta=PARequestMeta(
            jurisdiction=JurisdictionTag(
                jurisdiction=Jurisdiction.US_STATE, state_code="CA"
            ),
            payer_id="anthem",
            procedure_code="64483",
            diagnosis_codes=["M54.16"],
            urgency="routine",
            tenant_id=tenant,
        ),
        safe_context=SafeClinicalContext(
            pseudo_id="pid_" + "a" * 16,
            age_band="45-64",
            cleaned_text="Patient with chronic lumbar radiculopathy.",
        ),
        deid_report=DeidentificationReport(
            deid_method=DeidMethod.HIPAA_SAFE_HARBOR,
            identifier_counts={},
            content_hash="x" * 64,
        ),
    )


def _make_document(req: PARequest) -> PADocument:
    return PADocument(
        request_id=req.meta.request_id,
        payer_id=req.meta.payer_id,
        procedure_code=req.meta.procedure_code,
        diagnosis_codes=list(req.meta.diagnosis_codes),
        medical_necessity_narrative="Medically necessary procedure.",
        criteria=[
            ClinicalCriterion(
                label="conservative therapy",
                status=ClinicalCriterionStatus.MET,
                rationale="Documented.",
                evidence_ids=[uuid4()],
            )
        ],
        citations=[uuid4()],
    )


# ---------------------------------------------------------------------------
# Engine — noop when no URL configured
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_opa_noop_when_url_unset() -> None:
    engine = OpaPolicyEngine(Settings(opa_url=None))
    assert engine.is_enabled is False
    findings = await engine.evaluate(_make_request(), _make_document(_make_request()))
    assert findings == []


@pytest.mark.asyncio
async def test_opa_returns_empty_on_404() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(404))
    engine = OpaPolicyEngine(
        Settings(opa_url="http://opa:8181"),
        transport=transport,
    )
    findings = await engine.evaluate(_make_request(), _make_document(_make_request()))
    assert findings == []


@pytest.mark.asyncio
async def test_opa_parses_array_result() -> None:
    payload = {
        "result": [
            {
                "rule_id": "ACME-LUMBAR-001",
                "severity": "warning",
                "message": "Need 6w conservative therapy",
            }
        ]
    }
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json=payload))
    engine = OpaPolicyEngine(
        Settings(opa_url="http://opa:8181"),
        transport=transport,
    )
    req = _make_request()
    findings = await engine.evaluate(req, _make_document(req))
    assert len(findings) == 1
    assert findings[0].rule_id == "ACME-LUMBAR-001"
    assert findings[0].severity == "warning"


@pytest.mark.asyncio
async def test_opa_parses_object_with_findings_key() -> None:
    payload = {
        "result": {
            "findings": [
                {"rule_id": "X", "severity": "blocker", "message": "stop"},
            ]
        }
    }
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json=payload))
    engine = OpaPolicyEngine(
        Settings(opa_url="http://opa:8181"),
        transport=transport,
    )
    req = _make_request()
    findings = await engine.evaluate(req, _make_document(req))
    assert findings and findings[0].rule_id == "X"


# ---------------------------------------------------------------------------
# ComplianceEngine integration — overlay adds findings, blockers raise blocking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compliance_audit_async_with_opa_overlay() -> None:
    payload = {
        "result": [
            {
                "rule_id": "ACME-BIO-001",
                "severity": "blocker",
                "message": "Need PCP attestation",
            }
        ]
    }
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json=payload))
    opa = OpaPolicyEngine(
        Settings(opa_url="http://opa:8181"),
        transport=transport,
    )
    engine = ComplianceEngine(opa=opa)

    req = _make_request()
    doc = _make_document(req)
    report = await engine.audit_async(req, doc)

    assert report.blocking is True
    assert any(f.rule_id == "ACME-BIO-001" for f in report.findings)
    # Built-in findings are still surfaced.
    assert any(f.rule_id.startswith("US-CA") or f.rule_id.startswith("UNIV") for f in report.findings)


@pytest.mark.asyncio
async def test_compliance_audit_async_without_opa_matches_sync() -> None:
    engine = ComplianceEngine()
    req = _make_request()
    doc = _make_document(req)
    sync_report = engine.audit(req, doc)
    async_report = await engine.audit_async(req, doc)
    assert sync_report.findings == async_report.findings
    assert sync_report.blocking == async_report.blocking
