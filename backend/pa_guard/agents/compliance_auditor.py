"""ComplianceAuditorAgent — wraps ComplianceEngine in the BaseAgent lifecycle.

Two hooks exist for the supervisor:
- `audit(request, document)`: pre-submission gate; blocking findings stop the
  pipeline until a human approves or the document is amended.
- `audit_post(request, document, receipt)`: optional after-the-fact audit for
  outcome-logging.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..compliance.engine import ComplianceEngine
from ..core.models import ComplianceAuditReport, PADocument, PARequest
from .base import BaseAgent


@dataclass(frozen=True)
class AuditInput:
    request: PARequest
    document: PADocument | None


class ComplianceAuditorAgent(BaseAgent[AuditInput, ComplianceAuditReport]):
    def __init__(self, engine: ComplianceEngine | None = None) -> None:
        super().__init__(name="ComplianceAuditorAgent")
        self._engine = engine or ComplianceEngine()

    async def _run(self, payload: AuditInput) -> ComplianceAuditReport:
        return self._engine.audit(payload.request, payload.document)

    def _extra_kpis(
        self, payload: AuditInput, result: ComplianceAuditReport | None
    ) -> dict[str, float]:
        if result is None:
            return {}
        return {
            "findings_count": float(len(result.findings)),
            "blocking": 1.0 if result.blocking else 0.0,
        }


__all__ = ["AuditInput", "ComplianceAuditorAgent"]
