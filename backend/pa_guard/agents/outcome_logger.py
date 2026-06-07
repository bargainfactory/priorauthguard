"""OutcomeLogger — collects every agent critique + key lifecycle outcomes.

Phase 1 ships an in-memory implementation with a `JsonlSinkLogger` add-on for
persisting to an append-only JSONL file (audit-friendly). Phase 2's
`MetaImproverAgent` consumes the aggregated stream.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import orjson

from ..core.logging import get_logger
from ..core.models import (
    AgentCritique,
    ComplianceAuditReport,
    DenialReport,
    SubmissionReceipt,
    VoiceCallOutcome,
)

# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------

class OutcomeSink(Protocol):
    async def write(self, kind: str, payload: dict) -> None: ...


@dataclass
class InMemorySink:
    """Simple sink used in tests and dev."""

    entries: list[tuple[str, dict]] = field(default_factory=list)

    async def write(self, kind: str, payload: dict) -> None:
        self.entries.append((kind, payload))


@dataclass
class JsonlSink:
    """Append-only JSONL sink. Each line is one event.

    The file is opened lazily and flushed after every write so audit logs
    survive a crash.
    """

    path: Path

    async def write(self, kind: str, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = orjson.dumps({"kind": kind, **payload}) + b"\n"
        # tiny synchronous append — async wrapper here would only hide the
        # underlying blocking syscall.
        with self.path.open("ab") as fh:
            fh.write(line)


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class OutcomeLogger:
    """Single entry-point for everything that's worth remembering long-term."""

    def __init__(self, sink: OutcomeSink | None = None) -> None:
        self._sink = sink or InMemorySink()
        self._log = get_logger("OutcomeLogger")

    @property
    def sink(self) -> OutcomeSink:
        return self._sink

    # ------------------------------------------------------------------

    async def log_critique(self, critique: AgentCritique) -> None:
        await self._sink.write("agent_critique", json.loads(critique.model_dump_json()))

    async def log_audit(self, audit: ComplianceAuditReport) -> None:
        await self._sink.write("compliance_audit", json.loads(audit.model_dump_json()))

    async def log_submission(self, receipt: SubmissionReceipt) -> None:
        await self._sink.write("submission_receipt", json.loads(receipt.model_dump_json()))

    async def log_voice_outcome(self, outcome: VoiceCallOutcome) -> None:
        await self._sink.write("voice_outcome", json.loads(outcome.model_dump_json()))

    async def log_denial(self, denial: DenialReport) -> None:
        await self._sink.write("denial", json.loads(denial.model_dump_json()))

    async def log_event(self, kind: str, payload: dict) -> None:
        await self._sink.write(kind, payload)


__all__ = ["InMemorySink", "JsonlSink", "OutcomeLogger", "OutcomeSink"]
