"""Availity multi-payer prior authorization API adapter.

Availity is the largest health-information network in the US; most commercial
payers (Anthem, UHC, Aetna, Cigna, BCBS, Humana) accept PAs through its API
behind a single set of credentials.

Spec reference: https://apigw.apicentral.availity.com/availity/auth/v1/
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from ..core.config import Settings
from ..core.logging import get_logger
from ..core.models import PADocument, SubmissionChannel, SubmissionReceipt


@dataclass
class AvailityAdapter:
    """Real Availity adapter.

    Requires `PAG_AVAILITY_CLIENT_ID` + `PAG_AVAILITY_CLIENT_SECRET` to be set.
    Without them, raises `RuntimeError` at construction so
    `PayerAdapterRegistry` can fall back to the deterministic stub.
    """

    settings: Settings
    channel: SubmissionChannel = SubmissionChannel.API

    def __post_init__(self) -> None:
        client_id = getattr(self.settings, "availity_client_id", None)
        client_secret = getattr(self.settings, "availity_client_secret", None)
        if not (client_id and client_secret):
            raise RuntimeError("Availity credentials missing")
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = (
            getattr(self.settings, "availity_base_url", None)
            or "https://api.availity.com"
        ).rstrip("/")
        self._sandbox = bool(getattr(self.settings, "payer_sandbox_mode", False))
        self._log = get_logger("AvailityAdapter")

    async def submit(self, document: PADocument) -> SubmissionReceipt:
        # Lazy import so httpx is only required when this adapter is used.
        import httpx

        token = await self._access_token(httpx)
        payload = _to_availity_x12_278(document)

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                f"{self._base_url}/availity/v1/coverages/prior-authorizations",
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                    "x-correlation-id": str(uuid4()),
                },
                json=payload,
            )
        res.raise_for_status()
        body = res.json()

        self._log.info(
            "availity_submission_accepted",
            payer=document.payer_id,
            confirmation=body.get("trackingNumber"),
            sandbox=self._sandbox,
            base_url=self._base_url,
        )
        return SubmissionReceipt(
            request_id=document.request_id,
            channel=self.channel,
            payer_id=document.payer_id,
            confirmation_code=body.get("trackingNumber"),
            submitted_at=datetime.now(UTC),
            expected_response_seconds=int(body.get("estimatedResponseSeconds", 72 * 3600)),
        )

    # ------------------------------------------------------------------

    async def _access_token(self, httpx: object) -> str:
        # OAuth2 client-credentials flow against Availity's auth gateway.
        client = httpx.AsyncClient(timeout=15.0)  # type: ignore[attr-defined]
        try:
            res = await client.post(
                f"{self._base_url}/availity/v1/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": "hipaa",
                },
            )
            res.raise_for_status()
            return res.json()["access_token"]
        finally:
            await client.aclose()


def _to_availity_x12_278(doc: PADocument) -> dict:
    """Translate a de-identified `PADocument` into Availity's JSON envelope
    around an X12 278 prior-authorization transaction.

    No PHI flows in: only de-identified narrative, codes, and identifiers
    that have already passed Safe Harbor.
    """
    return {
        "requestType": "AUTHORIZATION",
        "submitterTrackingNumber": str(doc.document_id),
        "payer": {"id": doc.payer_id},
        "procedure": {"code": doc.procedure_code},
        "diagnoses": [{"code": c} for c in doc.diagnosis_codes],
        "medicalNecessity": doc.medical_necessity_narrative,
        "criteria": [
            {
                "label": c.label,
                "status": c.status,
                "rationale": c.rationale,
            }
            for c in doc.criteria
        ],
    }


__all__ = ["AvailityAdapter"]
