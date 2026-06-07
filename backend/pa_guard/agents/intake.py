"""IntakeAgent — normalize input and surface clarification requests.

The IntakeAgent is the **first** thing the supervisor invokes after the
raw payload arrives. It does not see PHI directly — the supervisor wraps it
with PrivacyGuardian on either side. Intake operates on the already-typed
`PARequestMeta` + `RawClinicalNote` skeleton and:

1. Validates that the minimum routing fields are present.
2. Surfaces a structured `IntakeClarificationRequest` listing missing fields
   if any (the supervisor can pause the graph and ask a human / upstream
   system to fill them in).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.models import (
    IntakeClarificationRequest,
    PARequestMeta,
    RawClinicalNote,
)
from .base import BaseAgent


@dataclass(frozen=True)
class IntakeInput:
    note: RawClinicalNote
    meta: PARequestMeta


@dataclass(frozen=True)
class IntakeReport:
    note: RawClinicalNote
    meta: PARequestMeta
    clarification: IntakeClarificationRequest | None


class IntakeAgent(BaseAgent[IntakeInput, IntakeReport]):
    def __init__(self) -> None:
        super().__init__(name="IntakeAgent")

    async def _run(self, payload: IntakeInput) -> IntakeReport:
        missing: list[str] = []
        questions: list[str] = []

        if not payload.meta.procedure_code:
            missing.append("procedure_code")
            questions.append("Which CPT/HCPCS/ICD-10 procedure is being requested?")
        if not payload.meta.diagnosis_codes:
            missing.append("diagnosis_codes")
            questions.append("What diagnosis codes (ICD-10) justify this procedure?")
        if not payload.meta.payer_id:
            missing.append("payer_id")
            questions.append("Which payer is this PA submitted to?")
        if not payload.note.text.strip():
            missing.append("note.text")
            questions.append("Provide the clinical narrative supporting medical necessity.")

        clarification = (
            IntakeClarificationRequest(
                request_id=payload.meta.request_id,
                missing_fields=missing,
                questions=questions,
            )
            if missing
            else None
        )
        return IntakeReport(
            note=payload.note,
            meta=payload.meta,
            clarification=clarification,
        )

    def _extra_kpis(self, payload: IntakeInput, result: IntakeReport | None) -> dict[str, float]:
        return {
            "missing_fields_count": float(
                len(result.clarification.missing_fields) if result and result.clarification else 0
            ),
        }


__all__ = ["IntakeAgent", "IntakeInput", "IntakeReport"]
