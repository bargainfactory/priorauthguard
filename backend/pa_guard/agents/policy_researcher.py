"""PolicyResearcherAgent — jurisdiction-aware RAG over payer / clinical policy."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.config import Jurisdiction
from ..core.models import PARequest, PolicyEvidence
from ..services.rag import PolicyCorpus
from .base import BaseAgent


@dataclass(frozen=True)
class PolicyResearchOutput:
    request_id: str
    evidence: list[PolicyEvidence]


class PolicyResearcherAgent(BaseAgent[PARequest, PolicyResearchOutput]):
    def __init__(self, corpus: PolicyCorpus | None = None, *, top_k: int = 4) -> None:
        super().__init__(name="PolicyResearcherAgent")
        self._corpus = corpus or PolicyCorpus()
        self._top_k = top_k

    async def _run(self, payload: PARequest) -> PolicyResearchOutput:
        # Query is constructed from de-identified context only.
        query = " ".join([
            payload.meta.procedure_code,
            *payload.meta.diagnosis_codes,
            payload.safe_context.cleaned_text[:512],
        ]).strip()
        jurisdiction = self._jurisdiction(payload)
        evidence = self._corpus.search(
            query,
            jurisdiction=jurisdiction,
            payer_id=payload.meta.payer_id,
            top_k=self._top_k,
        )
        # Fallback: if payer-filtered query returns nothing, retry payer-agnostic.
        if not evidence:
            evidence = self._corpus.search(
                query, jurisdiction=jurisdiction, top_k=self._top_k
            )
        return PolicyResearchOutput(
            request_id=str(payload.meta.request_id),
            evidence=evidence,
        )

    @staticmethod
    def _jurisdiction(req: PARequest) -> Jurisdiction:
        value = req.meta.jurisdiction.jurisdiction
        if isinstance(value, Jurisdiction):
            return value
        return Jurisdiction(value)

    def _extra_kpis(
        self, payload: PARequest, result: PolicyResearchOutput | None
    ) -> dict[str, float]:
        if result is None:
            return {}
        if not result.evidence:
            return {"evidence_count": 0.0, "avg_similarity": 0.0}
        avg = sum(e.similarity for e in result.evidence) / len(result.evidence)
        return {
            "evidence_count": float(len(result.evidence)),
            "avg_similarity": float(avg),
        }


__all__ = ["PolicyResearchOutput", "PolicyResearcherAgent"]
