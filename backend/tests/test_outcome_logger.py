"""OutcomeLogger sinks + aggregation tests."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from pa_guard.agents.outcome_logger import (
    InMemorySink,
    JsonlSink,
    OutcomeLogger,
    SqlSink,
)
from pa_guard.core.models import (
    AgentCritique,
    FHEInferenceResult,
    SubmissionChannel,
    SubmissionReceipt,
)

pytestmark = pytest.mark.asyncio


def _critique(agent: str, latency: float, success: float = 1.0) -> AgentCritique:
    return AgentCritique(
        agent_name=agent,
        request_id=uuid4(),
        kpi={"latency_ms": latency, "success": success},
    )


def _receipt() -> SubmissionReceipt:
    return SubmissionReceipt(
        request_id=uuid4(),
        channel=SubmissionChannel.API,
        payer_id="anthem",
        confirmation_code="ok-1",
    )


# ---------------------------------------------------------------------------
# InMemorySink
# ---------------------------------------------------------------------------

async def test_in_memory_sink_writes_and_reads() -> None:
    sink = InMemorySink()
    logger = OutcomeLogger(sink=sink)
    await logger.log_critique(_critique("IntakeAgent", 5.0))
    assert len(sink.entries) == 1
    assert sink.entries[0][0] == "agent_critique"


# ---------------------------------------------------------------------------
# JsonlSink
# ---------------------------------------------------------------------------

async def test_jsonl_sink_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "outcomes.jsonl"
    sink = JsonlSink(path=path)
    logger = OutcomeLogger(sink=sink)
    await logger.log_critique(_critique("IntakeAgent", 5.0))
    await logger.log_submission(_receipt())

    events = list(await sink.read())
    kinds = [k for k, _ in events]
    assert "agent_critique" in kinds
    assert "submission_receipt" in kinds


# ---------------------------------------------------------------------------
# SqlSink (SQLite)
# ---------------------------------------------------------------------------

async def test_sql_sink_sqlite_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "outcomes.sqlite"
    sink = SqlSink(database_url=f"sqlite+aiosqlite:///{db}")
    try:
        logger = OutcomeLogger(sink=sink)
        await logger.log_critique(_critique("IntakeAgent", 5.0))
        await logger.log_submission(_receipt())
        rows = list(await sink.read())
        assert len(rows) == 2
    except ModuleNotFoundError as e:
        # aiosqlite isn't a hard dep — skip cleanly if it's not installed.
        pytest.skip(f"aiosqlite not available: {e}")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

async def test_aggregate_computes_latency_and_success_by_agent() -> None:
    logger = OutcomeLogger()
    await logger.log_critique(_critique("IntakeAgent", 10.0, success=1.0))
    await logger.log_critique(_critique("IntakeAgent", 30.0, success=1.0))
    await logger.log_critique(_critique("PolicyResearcherAgent", 100.0, success=0.0))

    agg = await logger.aggregate()
    assert agg.sample_count == 3
    assert agg.by_agent_avg_latency_ms["IntakeAgent"] == 20.0
    assert agg.by_agent_avg_latency_ms["PolicyResearcherAgent"] == 100.0
    assert agg.by_agent_success_rate["IntakeAgent"] == 1.0
    assert agg.by_agent_success_rate["PolicyResearcherAgent"] == 0.0


async def test_aggregate_computes_denial_rate() -> None:
    logger = OutcomeLogger()
    await logger.log_submission(_receipt())
    await logger.log_submission(_receipt())
    from pa_guard.core.models import DenialReport

    await logger.log_denial(
        DenialReport(
            request_id=uuid4(),
            reason_codes=["MN-1"],
            summary="x",
        )
    )
    agg = await logger.aggregate()
    assert agg.denial_rate == pytest.approx(0.5)


async def test_aggregate_computes_fhe_executed_share() -> None:
    logger = OutcomeLogger()
    await logger.log_fhe(
        FHEInferenceResult(
            circuit_name="denial_risk_v0",
            prediction=0.3,
            latency_ms=12.0,
            fhe_executed=True,
        )
    )
    await logger.log_fhe(
        FHEInferenceResult(
            circuit_name="denial_risk_v0",
            prediction=0.1,
            latency_ms=5.0,
            fhe_executed=False,
        )
    )
    agg = await logger.aggregate()
    assert agg.fhe_executed_share == pytest.approx(0.5)
    assert agg.avg_fhe_latency_ms == pytest.approx(8.5)
