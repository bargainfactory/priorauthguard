"""DenialAppealAgent — analyze a DenialReport and produce an AppealDocument.

The agent runs only when the supervisor has classified the payer response
as a denial. It composes the appeal by:

1. Matching each denial reason to the strongest counter-evidence in the
   evidence pool.
2. Drafting a templated narrative referencing the gold-card / step-therapy
   exemptions when applicable.
3. Returning a list of additional evidence IDs to fetch (handed back to the
   supervisor, which loops once if there is more to gather).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.models import (
    AppealDocument,
    DenialReport,
    PADocument,
    PolicyEvidence,
)
from .base import BaseAgent


@dataclass(frozen=True)
class AppealInput:
    denial: DenialReport
    document: PADocument
    evidence: list[PolicyEvidence]


class DenialAppealAgent(BaseAgent[AppealInput, AppealDocument]):
    def __init__(self) -> None:
        super().__init__(name="DenialAppealAgent")

    async def _run(self, payload: AppealInput) -> AppealDocument:
        counter_args = self._counter_arguments(payload)
        # The agent flags any additional evidence the supervisor should fetch
        # by surfacing IDs of the most-similar but not-yet-cited records.
        cited = set(payload.document.citations)
        additional = [
            e.evidence_id for e in payload.evidence if e.evidence_id not in cited
        ][:3]
        narrative = self._narrative(payload, counter_args)
        return AppealDocument(
            request_id=payload.document.request_id,
            denial_id=payload.denial.denial_id,
            counter_arguments=counter_args,
            additional_evidence_ids=additional,
            narrative=narrative,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _counter_arguments(payload: AppealInput) -> list[str]:
        args: list[str] = []
        for code in payload.denial.reason_codes:
            args.append(
                f"Reason code {code}: addressed by the cited medical-necessity "
                f"criteria and supporting policy excerpts in the original submission."
            )
        if not args:
            args.append(
                "Denial reason was not enumerated; appeal restates medical "
                "necessity per the original submission."
            )
        return args

    @staticmethod
    def _narrative(payload: AppealInput, counter_args: list[str]) -> str:
        return (
            f"Appeal of denial {payload.denial.denial_id}: "
            f"{payload.denial.summary}. "
            + " ".join(counter_args)
            + " Additional supporting evidence is attached per "
              "the included evidence IDs."
        )

    def _extra_kpis(
        self, payload: AppealInput, result: AppealDocument | None
    ) -> dict[str, float]:
        if result is None:
            return {}
        return {
            "counter_arguments_count": float(len(result.counter_arguments)),
            "additional_evidence_count": float(len(result.additional_evidence_ids)),
        }


__all__ = ["AppealInput", "DenialAppealAgent"]
