"""SubmissionAgent — dispatches a PADocument to the correct payer channel.

Adapter protocol so production deployments can register real connectors per
payer (Availity, CoverMyMeds, Surescripts, NHS Spine, OHIP API, etc.) and the
Phase 1 stub gives the supervisor a working end-to-end path today.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..core.models import (
    PADocument,
    SubmissionChannel,
    SubmissionReceipt,
)
from .base import BaseAgent


class SubmissionAdapter(Protocol):
    channel: SubmissionChannel

    async def submit(self, document: PADocument) -> SubmissionReceipt: ...


@dataclass
class StubAdapter:
    """Default in-process adapter used in dev / tests / when a payer has no
    real connector yet. Deterministically synthesises a confirmation code."""

    channel: SubmissionChannel = SubmissionChannel.API

    async def submit(self, document: PADocument) -> SubmissionReceipt:
        confirmation = (
            f"stub-{document.payer_id}-{str(document.document_id)[:8]}"
        )
        return SubmissionReceipt(
            request_id=document.request_id,
            channel=self.channel,
            payer_id=document.payer_id,
            confirmation_code=confirmation,
            expected_response_seconds=72 * 3600,
        )


@dataclass(frozen=True)
class SubmissionInput:
    document: PADocument
    preferred_channel: SubmissionChannel = SubmissionChannel.API


class SubmissionAgent(BaseAgent[SubmissionInput, SubmissionReceipt]):
    def __init__(
        self,
        adapters: dict[SubmissionChannel, SubmissionAdapter] | None = None,
    ) -> None:
        super().__init__(name="SubmissionAgent")
        # Default: stub for every channel so the supervisor can run without
        # any external integration provisioned.
        default = {
            ch: StubAdapter(channel=ch)
            for ch in SubmissionChannel
        }
        if adapters:
            default.update(adapters)
        self._adapters = default

    async def _run(self, payload: SubmissionInput) -> SubmissionReceipt:
        adapter = self._adapters.get(payload.preferred_channel)
        if adapter is None:
            # Should be impossible since we seed every channel with a stub.
            raise RuntimeError(
                f"No adapter for channel {payload.preferred_channel.value!r}; "
                "register one before submission."
            )
        return await adapter.submit(payload.document)

    def _extra_kpis(
        self, payload: SubmissionInput, result: SubmissionReceipt | None
    ) -> dict[str, float]:
        return {
            "channel_is_api": 1.0
            if payload.preferred_channel == SubmissionChannel.API
            else 0.0,
        }


__all__ = ["StubAdapter", "SubmissionAdapter", "SubmissionAgent", "SubmissionInput"]
