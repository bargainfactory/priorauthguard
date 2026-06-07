"""NHS Spine adapter — UK specialised commissioning prior authorizations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..core.config import Settings
from ..core.logging import get_logger
from ..core.models import PADocument, SubmissionChannel, SubmissionReceipt


@dataclass
class NhsSpineAdapter:
    settings: Settings
    channel: SubmissionChannel = SubmissionChannel.PORTAL

    def __post_init__(self) -> None:
        api_key = getattr(self.settings, "nhs_spine_api_key", None)
        if not api_key:
            raise RuntimeError("NHS Spine credentials missing")
        self._api_key = api_key
        self._base_url = (
            getattr(self.settings, "nhs_spine_base_url", None)
            or "https://api.spine.nhs.uk"
        ).rstrip("/")
        self._sandbox = bool(getattr(self.settings, "payer_sandbox_mode", False))
        self._log = get_logger("NhsSpineAdapter")

    async def submit(self, document: PADocument) -> SubmissionReceipt:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            # NHS Spine uses an HL7 FHIR R4 ServiceRequest with PA extension;
            # we transmit a minimal de-identified JSON shape and let the
            # gateway adapt it.
            res = await client.post(
                f"{self._base_url}/specialised-commissioning/v1/requests",
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/fhir+json",
                    "nhsd-session-urid": str(document.document_id),
                },
                json={
                    "resourceType": "ServiceRequest",
                    "status": "active",
                    "intent": "order",
                    "code": {"coding": [{"code": document.procedure_code}]},
                    "reasonCode": [
                        {"coding": [{"code": c}]} for c in document.diagnosis_codes
                    ],
                    "supportingInfo": [
                        {"reference": document.medical_necessity_narrative}
                    ],
                },
            )
        res.raise_for_status()
        out = res.json()
        self._log.info(
            "nhs_spine_accepted",
            payer=document.payer_id,
            ref=out.get("id"),
            sandbox=self._sandbox,
            base_url=self._base_url,
        )
        return SubmissionReceipt(
            request_id=document.request_id,
            channel=self.channel,
            payer_id=document.payer_id,
            confirmation_code=out.get("id"),
            submitted_at=datetime.now(UTC),
            expected_response_seconds=14 * 24 * 3600,
        )


__all__ = ["NhsSpineAdapter"]
