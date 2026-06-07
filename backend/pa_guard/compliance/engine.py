"""ComplianceEngine — evaluate a PA request + document against the resolved
rule pack for its jurisdiction, layered with an optional OPA / Rego overlay.
"""
from __future__ import annotations

from ..core.models import (
    ComplianceAuditReport,
    ComplianceFinding,
    JurisdictionTag,
    PADocument,
    PARequest,
)
from .opa import OpaPolicyEngine
from .rules import resolve_rules


class ComplianceEngine:
    """Stateless rule evaluator.

    Built-in rule packs run first; if an `OpaPolicyEngine` is wired and
    enabled, its findings are appended. A blocker from either layer marks
    the audit as blocking.
    """

    def __init__(self, opa: OpaPolicyEngine | None = None) -> None:
        self._opa = opa

    def audit(
        self,
        request: PARequest,
        document: PADocument | None,
    ) -> ComplianceAuditReport:
        """Sync built-in audit (no OPA overlay). Kept stable for the
        supervisor's existing call site so the LangGraph hot path stays sync."""
        return self._evaluate_builtin(request, document)

    async def audit_async(
        self,
        request: PARequest,
        document: PADocument | None,
    ) -> ComplianceAuditReport:
        """Async audit that layers the OPA overlay on top of the built-ins."""
        report = self._evaluate_builtin(request, document)
        if self._opa is not None and self._opa.is_enabled:
            overlay = await self._opa.evaluate(request, document)
            merged = list(report.findings) + overlay
            blocking = report.blocking or any(f.severity == "blocker" for f in overlay)
            report = report.model_copy(update={"findings": merged, "blocking": blocking})
        return report

    # ------------------------------------------------------------------

    def _evaluate_builtin(
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
