"""DocumentGeneratorAgent — assemble a payer-ready PA document.

The output is a structured `PADocument` containing:
- a medical-necessity narrative derived from the de-identified clinical text;
- a list of `ClinicalCriterion`s, each cross-referenced to RAG evidence;
- the IDs of every cited policy excerpt (for the auditor & for the PDF
  builder Phase 3 will add).

The narrative builder uses templated text in Phase 1; a Claude/LLM-backed
narrative drop-in lands behind the same interface in Phase 5.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.models import (
    ClinicalCriterion,
    ClinicalCriterionStatus,
    PADocument,
    PARequest,
    PolicyEvidence,
)
from .base import BaseAgent


@dataclass(frozen=True)
class DocumentGenerationInput:
    request: PARequest
    evidence: list[PolicyEvidence]


class DocumentGeneratorAgent(BaseAgent[DocumentGenerationInput, PADocument]):
    def __init__(self) -> None:
        super().__init__(name="DocumentGeneratorAgent")

    async def _run(self, payload: DocumentGenerationInput) -> PADocument:
        narrative = self._narrative(payload)
        criteria = self._criteria(payload)
        return PADocument(
            request_id=payload.request.meta.request_id,
            payer_id=payload.request.meta.payer_id,
            procedure_code=payload.request.meta.procedure_code,
            diagnosis_codes=list(payload.request.meta.diagnosis_codes),
            medical_necessity_narrative=narrative,
            criteria=criteria,
            citations=[e.evidence_id for e in payload.evidence],
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _narrative(payload: DocumentGenerationInput) -> str:
        req = payload.request
        dx = ", ".join(req.meta.diagnosis_codes) or "(no dx codes)"
        urgency_prefix = (
            "URGENT — clinical urgency requires expedited review. " if req.meta.urgency == "urgent"
            else "EMERGENT — life- or limb-threatening; immediate review required. " if req.meta.urgency == "emergent"
            else ""
        )
        evidence_strs = "; ".join(
            f"{e.source} (similarity={e.similarity:.2f})" for e in payload.evidence
        ) or "no supporting policy retrieved"
        return (
            f"{urgency_prefix}"
            f"Prior authorization is requested for procedure {req.meta.procedure_code} "
            f"in support of diagnoses {dx}. "
            f"De-identified clinical context: {req.safe_context.cleaned_text[:1024]}. "
            f"Supporting policy excerpts: {evidence_strs}."
        )

    @staticmethod
    def _criteria(payload: DocumentGenerationInput) -> list[ClinicalCriterion]:
        # Phase 1 derives criteria from the top RAG hits; each criterion's
        # status is heuristically set to MET when the cleaned text mentions
        # any of the salient keywords. A learned classifier replaces this in
        # Phase 5.
        crits: list[ClinicalCriterion] = []
        for e in payload.evidence[:3]:
            keywords = _keywords(e.excerpt)
            mentioned = sum(
                1 for kw in keywords if kw in payload.request.safe_context.cleaned_text.lower()
            )
            status = (
                ClinicalCriterionStatus.MET
                if mentioned >= 1
                else ClinicalCriterionStatus.UNKNOWN
            )
            crits.append(
                ClinicalCriterion(
                    label=e.source,
                    status=status,
                    rationale=(
                        "Salient terms from the cited policy were found in the "
                        "de-identified clinical context." if status == ClinicalCriterionStatus.MET
                        else "Cited policy excerpt did not directly intersect the clinical context."
                    ),
                    evidence_ids=[e.evidence_id],
                )
            )
        return crits


def _keywords(excerpt: str) -> list[str]:
    stop = {
        "the", "a", "and", "of", "for", "to", "in", "with", "is", "are",
        "be", "by", "as", "an", "or", "on", "this",
    }
    return [
        w for w in (t.strip(".,;:()") for t in excerpt.lower().split())
        if len(w) > 3 and w not in stop
    ][:12]


__all__ = ["DocumentGenerationInput", "DocumentGeneratorAgent"]
