"""CoverMyMeds adapter — drug PAs, public payer routing.

Spec reference: https://developers.covermymeds.com/
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..core.config import Settings
from ..core.logging import get_logger
from ..core.models import PADocument, SubmissionChannel, SubmissionReceipt


@dataclass
class CoverMyMedsAdapter:
    settings: Settings
    channel: SubmissionChannel = SubmissionChannel.API

    def __post_init__(self) -> None:
        api_key = getattr(self.settings, "covermymeds_api_key", None)
        if not api_key:
            raise RuntimeError("CoverMyMeds credentials missing")
        self._api_key = api_key
        self._log = get_logger("CoverMyMedsAdapter")

    async def submit(self, document: PADocument) -> SubmissionReceipt:
        import httpx

        body = {
            "tracking_id": str(document.document_id),
            "payer_id": document.payer_id,
            "request": {
                "procedure_code": document.procedure_code,
                "diagnoses": document.diagnosis_codes,
                "narrative": document.medical_necessity_narrative,
                "criteria": [
                    {
                        "label": c.label,
                        "status": c.status,
                        "rationale": c.rationale,
                    }
                    for c in document.criteria
                ],
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                "https://api.covermymeds.com/v2/prior_authorizations",
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                json=body,
            )
        res.raise_for_status()
        out = res.json()
        self._log.info(
            "covermymeds_accepted",
            payer=document.payer_id,
            confirmation=out.get("token"),
        )
        return SubmissionReceipt(
            request_id=document.request_id,
            channel=self.channel,
            payer_id=document.payer_id,
            confirmation_code=out.get("token"),
            submitted_at=datetime.now(UTC),
            expected_response_seconds=int(out.get("expected_response_seconds", 72 * 3600)),
        )


__all__ = ["CoverMyMedsAdapter"]
