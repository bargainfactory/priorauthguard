"""Fax adapter — used for payers that still require a fax submission.

Backed by a generic fax API (Phaxio / Documo / etc.). The integration is
intentionally provider-agnostic; the wire is a multipart upload of a rendered
PDF generated from the de-identified `PADocument`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..core.config import Settings
from ..core.logging import get_logger
from ..core.models import PADocument, SubmissionChannel, SubmissionReceipt


@dataclass
class FaxAdapter:
    settings: Settings
    channel: SubmissionChannel = SubmissionChannel.FAX

    def __post_init__(self) -> None:
        api_key = getattr(self.settings, "fax_api_key", None)
        api_url = getattr(self.settings, "fax_api_url", None)
        if not (api_key and api_url):
            raise RuntimeError("Fax provider credentials missing")
        self._api_key = api_key
        self._api_url = api_url
        self._log = get_logger("FaxAdapter")

    async def submit(self, document: PADocument) -> SubmissionReceipt:
        import httpx

        rendered = _render_text_pdf(document)
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                f"{self._api_url}/v2/faxes",
                headers={"authorization": f"Bearer {self._api_key}"},
                files={"file": ("pa.pdf", rendered, "application/pdf")},
                data={
                    "to": getattr(self.settings, "fax_to_number", None) or "",
                    "from": getattr(self.settings, "fax_from_number", None) or "",
                    "metadata": str(document.document_id),
                },
            )
        res.raise_for_status()
        out = res.json()
        self._log.info(
            "fax_submitted",
            payer=document.payer_id,
            fax_id=out.get("id"),
        )
        return SubmissionReceipt(
            request_id=document.request_id,
            channel=self.channel,
            payer_id=document.payer_id,
            confirmation_code=str(out.get("id")) if out.get("id") else None,
            submitted_at=datetime.now(UTC),
            expected_response_seconds=72 * 3600,
        )


def _render_text_pdf(document: PADocument) -> bytes:
    """Minimal pdf builder.

    Avoids reportlab so the core install stays lean — a real deployment
    swaps this for the existing PDF builder. The "pdf" here is plain text
    inside a single-page envelope — enough to exercise the wire shape.
    """
    body = (
        f"PA Document {document.document_id}\n"
        f"Payer: {document.payer_id}\n"
        f"Procedure: {document.procedure_code}\n"
        f"Diagnoses: {', '.join(document.diagnosis_codes)}\n\n"
        f"{document.medical_necessity_narrative}\n"
    ).encode("ascii", errors="replace")
    # Stand-in: most fax APIs accept any binary marked as application/pdf;
    # full text + minimal PDF header keeps the multipart wire structure stable.
    return b"%PDF-1.4\n% PriorAuthGuard fax stub\n" + body
