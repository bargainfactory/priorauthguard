"""ComplianceEngine — evaluate a PA request + document against the resolved
rule pack for its jurisdiction.
"""
from __future__ import annotations

from ..core.models import (
    ComplianceAuditReport,
    ComplianceFinding,
    JurisdictionTag,
    PADocument,
    PARequest,
)
from .rules import resolve_rules


class ComplianceEngine:
    """Stateless rule evaluator."""

    def audit(
        self,
        request: PARequest,
        document: PADocument | None,
    ) -> ComplianceAuditReport:
        tag: JurisdictionTag = self._tag(request.meta.jurisdiction)
        resolution = resolve_rules(
            self._jurisdiction(request.meta.jurisdiction),
            state_code=request.meta.jurisdiction.state_code,
            province_code=request.meta.jurisdiction.province_code,
        )
        findings: list[ComplianceFinding] = []
        blocking = False
        for rule in resolution.all_rules():
            ok = rule.predicate(request, document)
            if rule.severity == "info":
                # Info rules surface context regardless of predicate result —
                # they are not "violations", they are "be aware".
                findings.append(
                    ComplianceFinding(
                        rule_id=rule.rule_id,
                        severity="info",
                        message=rule.description,
                    )
                )
                continue
            if not ok:
                findings.append(
                    ComplianceFinding(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=rule.description,
                    )
                )
                if rule.severity == "blocker":
                    blocking = True
        return ComplianceAuditReport(
            request_id=request.meta.request_id,
            jurisdiction=tag,
            findings=findings,
            blocking=blocking,
        )

    @staticmethod
    def _tag(tag) -> JurisdictionTag:  # type: ignore[no-untyped-def]
        # Pydantic models with `use_enum_values=True` give us a plain dict-like
        # access path; the field is already a `JurisdictionTag` instance.
        return tag

    @staticmethod
    def _jurisdiction(tag: JurisdictionTag):  # type: ignore[no-untyped-def]
        from ..core.config import Jurisdiction

        # Field may already be the str value because of `use_enum_values=True`.
        value = tag.jurisdiction
        if isinstance(value, Jurisdiction):
            return value
        return Jurisdiction(value)


__all__ = ["ComplianceEngine"]
