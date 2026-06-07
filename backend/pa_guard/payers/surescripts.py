"""Surescripts PA adapter — specialty pharmacy prior authorization."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..core.config import Settings
from ..core.logging import get_logger
from ..core.models import PADocument, SubmissionChannel, SubmissionReceipt


@dataclass
class SurescriptsAdapter:
    settings: Settings
    channel: SubmissionChannel = SubmissionChannel.API

    def __post_init__(self) -> None:
        client_id = getattr(self.settings, "surescripts_client_id", None)
        client_secret = getattr(self.settings, "surescripts_client_secret", None)
        if not (client_id and client_secret):
            raise RuntimeError("Surescripts credentials missing")
        self._client_id = client_id
        self._client_secret = client_secret
        self._log = get_logger("SurescriptsAdapter")

    async def submit(self, document: PADocument) -> SubmissionReceipt:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Surescripts uses a SOAP envelope in production; the API gateway
            # exposes a JSON-on-the-edge shape for newer consumers, which we
            # use here. The wire is bearer-token authed.
            res = await client.post(
                "https://api.surescripts.com/prior-authorization/v1/submit",
                headers={
                    "authorization": f"Bearer {await self._token(httpx)}",
                    "content-type": "application/json",
                },
                json={
                    "tracking": str(document.document_id),
                    "drug": {"code": document.procedure_code},
                    "diagnoses": document.diagnosis_codes,
                    "narrative": document.medical_necessity_narrative,
                },
            )
        res.raise_for_status()
        out = res.json()
        self._log.info(
            "surescripts_accepted",
            payer=document.payer_id,
            confirmation=out.get("paId"),
        )
        return SubmissionReceipt(
            request_id=document.request_id,
            channel=self.channel,
            payer_id=document.payer_id,
            confirmation_code=out.get("paId"),
            submitted_at=datetime.now(UTC),
            expected_response_seconds=int(out.get("expectedResponseSeconds", 24 * 3600)),
        )

    async def _token(self, httpx: object) -> str:
        client = httpx.AsyncClient(timeout=15.0)  # type: ignore[attr-defined]
        try:
            res = await client.post(
                "https://api.surescripts.com/oauth2/v1/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": "prior_authorization",
                },
            )
            res.raise_for_status()
            return res.json()["access_token"]
        finally:
            await client.aclose()


__all__ = ["SurescriptsAdapter"]
