"""OutcomeLogger — collects every agent critique + key lifecycle outcomes.

Phase 2 upgrades:
- `SqlSink` works against any SQLAlchemy async URL (Postgres via asyncpg in
  production, SQLite for hermetic tests).
- `OutcomeLogger.aggregate(window_seconds)` produces an `OutcomeAggregate`
  with the metrics `MetaImproverAgent` consumes (per-agent latency / success
  rates, denial rate, FHE executed share, raw-audio-on-device share).
- The in-memory sink is still the default for tests + dev.
"""
from __future__ import annotations

import json
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import orjson

from ..core.logging import get_logger
from ..core.models import (
    AgentCritique,
    ComplianceAuditReport,
    DenialReport,
    FHEInferenceResult,
    OutcomeAggregate,
    SubmissionReceipt,
    VoiceCallOutcome,
)

# ---------------------------------------------------------------------------
# Event kinds — stable strings used by all sinks
# ---------------------------------------------------------------------------

class EventKind:
    AGENT_CRITIQUE = "agent_critique"
    COMPLIANCE_AUDIT = "compliance_audit"
    SUBMISSION_RECEIPT = "submission_receipt"
    VOICE_OUTCOME = "voice_outcome"
    DENIAL = "denial"
    FHE_INFERENCE = "fhe_inference"


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------

class OutcomeSink(Protocol):
    async def write(self, kind: str, payload: dict[str, Any]) -> None: ...
    async def read(self, since: datetime | None = None) -> Iterable[tuple[str, dict[str, Any]]]: ...


@dataclass
class InMemorySink:
    """Default for tests + dev."""

    entries: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def write(self, kind: str, payload: dict[str, Any]) -> None:
        self.entries.append((kind, payload))

    async def read(
        self, since: datetime | None = None
    ) -> Iterable[tuple[str, dict[str, Any]]]:
        if since is None:
            return list(self.entries)
        cutoff = since.isoformat()
        return [
            (k, p)
            for k, p in self.entries
            if str(p.get("created_at") or p.get("audited_at") or p.get("submitted_at") or "") >= cutoff
        ]


@dataclass
class JsonlSink:
    """Append-only JSONL sink. Each line is one event."""

    path: Path

    async def write(self, kind: str, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = orjson.dumps({"kind": kind, **payload}) + b"\n"
        with self.path.open("ab") as fh:
            fh.write(line)

    async def read(
        self, since: datetime | None = None
    ) -> Iterable[tuple[str, dict[str, Any]]]:
        if not self.path.exists():
            return []
        cutoff = since.isoformat() if since else None
        out: list[tuple[str, dict[str, Any]]] = []
        with self.path.open("rb") as fh:
            for raw in fh:
                obj = orjson.loads(raw)
                if cutoff and str(obj.get("created_at") or obj.get("audited_at") or "") < cutoff:
                    continue
                kind = obj.pop("kind")
                out.append((kind, obj))
        return out


class SqlSink:
    """SQLAlchemy-backed sink (Postgres in production, SQLite in tests).

    Schema is intentionally tiny — one append-only table whose `payload`
    column stores the structured event as JSON. This trades query speed for
    flexibility and survives every Phase 1+ model change without migrations.
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS pa_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """

    PG_DDL = """
    CREATE TABLE IF NOT EXISTS pa_outcomes (
        id BIGSERIAL PRIMARY KEY,
        kind TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        payload JSONB NOT NULL
    )
    """

    def __init__(self, database_url: str) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        self._url = database_url
        self._engine = create_async_engine(database_url, future=True)
        self._initialized = False
        self._is_postgres = database_url.startswith(("postgresql", "postgres"))

    async def _ensure_schema(self) -> None:
        if self._initialized:
            return
        from sqlalchemy import text

        ddl = self.PG_DDL if self._is_postgres else self.DDL
        async with self._engine.begin() as conn:
            await conn.execute(text(ddl))
        self._initialized = True

    async def write(self, kind: str, payload: dict[str, Any]) -> None:
        from sqlalchemy import text

        await self._ensure_schema()
        created_at = (
            payload.get("created_at")
            or payload.get("audited_at")
            or payload.get("submitted_at")
            or datetime.now(UTC).isoformat()
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO pa_outcomes (kind, created_at, payload) "
                    "VALUES (:kind, :created_at, :payload)"
                ),
                {"kind": kind, "created_at": created_at, "payload": json.dumps(payload)},
            )

    async def read(
        self, since: datetime | None = None
    ) -> Iterable[tuple[str, dict[str, Any]]]:
        from sqlalchemy import text

        await self._ensure_schema()
        if since:
            query = text(
                "SELECT kind, payload FROM pa_outcomes WHERE created_at >= :since "
                "ORDER BY id ASC"
            )
            params = {"since": since.isoformat()}
        else:
            query = text("SELECT kind, payload FROM pa_outcomes ORDER BY id ASC")
            params = {}
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query, params)).all()
        return [(k, json.loads(p)) for (k, p) in rows]


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
    # Writes
    # ------------------------------------------------------------------

    async def log_critique(self, critique: AgentCritique) -> None:
        await self._sink.write(EventKind.AGENT_CRITIQUE, json.loads(critique.model_dump_json()))

    async def log_audit(self, audit: ComplianceAuditReport) -> None:
        await self._sink.write(EventKind.COMPLIANCE_AUDIT, json.loads(audit.model_dump_json()))

    async def log_submission(self, receipt: SubmissionReceipt) -> None:
        await self._sink.write(EventKind.SUBMISSION_RECEIPT, json.loads(receipt.model_dump_json()))

    async def log_voice_outcome(self, outcome: VoiceCallOutcome) -> None:
        await self._sink.write(EventKind.VOICE_OUTCOME, json.loads(outcome.model_dump_json()))

    async def log_denial(self, denial: DenialReport) -> None:
        await self._sink.write(EventKind.DENIAL, json.loads(denial.model_dump_json()))

    async def log_fhe(self, result: FHEInferenceResult) -> None:
        await self._sink.write(EventKind.FHE_INFERENCE, json.loads(result.model_dump_json()))

    async def log_event(self, kind: str, payload: dict[str, Any]) -> None:
        await self._sink.write(kind, payload)

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    async def aggregate(self, *, window_seconds: int = 0) -> OutcomeAggregate:
        """Compute roll-ups over the most recent `window_seconds` (0 = all-time)."""
        since = (
            datetime.now(UTC) - timedelta(seconds=window_seconds)
            if window_seconds > 0
            else None
        )
        events = list(await self._sink.read(since=since))

        latencies: dict[str, list[float]] = {}
        successes: dict[str, list[float]] = {}
        fhe_latencies: list[float] = []
        fhe_executed_flags: list[float] = []
        voice_durations: list[float] = []
        voice_on_device: list[float] = []
        submissions = 0
        denials = 0

        for kind, payload in events:
            if kind == EventKind.AGENT_CRITIQUE:
                agent = payload.get("agent_name", "unknown")
                kpi = payload.get("kpi", {})
                if "latency_ms" in kpi:
                    latencies.setdefault(agent, []).append(float(kpi["latency_ms"]))
                if "success" in kpi:
                    successes.setdefault(agent, []).append(float(kpi["success"]))
            elif kind == EventKind.SUBMISSION_RECEIPT:
                submissions += 1
            elif kind == EventKind.DENIAL:
                denials += 1
            elif kind == EventKind.FHE_INFERENCE:
                if "latency_ms" in payload:
                    fhe_latencies.append(float(payload["latency_ms"]))
                fhe_executed_flags.append(1.0 if payload.get("fhe_executed") else 0.0)
            elif kind == EventKind.VOICE_OUTCOME:
                voice_durations.append(float(payload.get("duration_seconds", 0.0)))
                # `voice_outcome` doesn't directly carry on-device — the VoiceOrchestratorAgent
                # critique does, via `raw_audio_left_device`.
            elif kind == EventKind.AGENT_CRITIQUE:
                pass  # handled above

        # Voice on-device share is read from VoiceOrchestratorAgent critiques.
        for kind, payload in events:
            if kind == EventKind.AGENT_CRITIQUE and payload.get("agent_name") == "VoiceOrchestratorAgent":
                left = payload.get("kpi", {}).get("raw_audio_left_device")
                if left is not None:
                    voice_on_device.append(0.0 if float(left) > 0.0 else 1.0)

        return OutcomeAggregate(
            window_seconds=window_seconds,
            sample_count=len(events),
            by_agent_avg_latency_ms={a: statistics.fmean(v) for a, v in latencies.items() if v},
            by_agent_success_rate={a: statistics.fmean(v) for a, v in successes.items() if v},
            denial_rate=(denials / submissions) if submissions else 0.0,
            appeal_success_rate=0.0,  # populated in Phase 5 when appeal outcomes are logged
            fhe_executed_share=(
                statistics.fmean(fhe_executed_flags) if fhe_executed_flags else 0.0
            ),
            avg_fhe_latency_ms=(
                statistics.fmean(fhe_latencies) if fhe_latencies else None
            ),
            avg_voice_call_duration_seconds=(
                statistics.fmean(voice_durations) if voice_durations else None
            ),
            raw_audio_left_device_share=(
                1.0 - statistics.fmean(voice_on_device) if voice_on_device else 0.0
            ),
        )


__all__ = [
    "EventKind",
    "InMemorySink",
    "JsonlSink",
    "OutcomeLogger",
    "OutcomeSink",
    "SqlSink",
]
