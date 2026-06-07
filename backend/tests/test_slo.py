"""SLO evaluator + endpoint tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pa_guard.api.main import app
from pa_guard.core.config import Settings
from pa_guard.core.models import OutcomeAggregate, SloStatus
from pa_guard.services.slo import SloEvaluator


def _agg(**overrides) -> OutcomeAggregate:
    base = {
        "window_seconds": 0,
        "sample_count": 100,
        "by_agent_avg_latency_ms": {},
        "by_agent_success_rate": {},
        "denial_rate": 0.05,
        "appeal_success_rate": 0.0,
        "fhe_executed_share": 0.95,
        "avg_fhe_latency_ms": 50.0,
        "avg_voice_call_duration_seconds": 30.0,
        "raw_audio_left_device_share": 0.0,
    }
    base.update(overrides)
    return OutcomeAggregate(**base)


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def test_healthy_aggregate_passes_all_slos() -> None:
    snap = SloEvaluator(Settings()).evaluate(_agg())
    assert snap.overall_status == SloStatus.MET.value
    for r in snap.reports:
        assert r.status == SloStatus.MET.value


def test_high_denial_rate_breaches_slo() -> None:
    snap = SloEvaluator(Settings()).evaluate(_agg(denial_rate=0.40))
    denial = next(r for r in snap.reports if r.slo_id == "denial-rate")
    assert denial.status == SloStatus.BREACHED.value
    assert snap.overall_status == SloStatus.BREACHED.value


def test_denial_rate_at_risk_band() -> None:
    # Just below 0.20 ceiling — within the top 10% band → at-risk.
    snap = SloEvaluator(Settings()).evaluate(_agg(denial_rate=0.19))
    denial = next(r for r in snap.reports if r.slo_id == "denial-rate")
    assert denial.status == SloStatus.AT_RISK.value


def test_low_fhe_coverage_breaches_slo() -> None:
    snap = SloEvaluator(Settings()).evaluate(_agg(fhe_executed_share=0.10))
    fhe = next(r for r in snap.reports if r.slo_id == "fhe-coverage")
    assert fhe.status == SloStatus.BREACHED.value


def test_audio_off_device_breaches_voice_slo() -> None:
    snap = SloEvaluator(Settings()).evaluate(_agg(raw_audio_left_device_share=0.30))
    voice = next(r for r in snap.reports if r.slo_id == "voice-on-device")
    assert voice.status == SloStatus.BREACHED.value


def test_slow_agent_breaches_latency_slo() -> None:
    snap = SloEvaluator(Settings()).evaluate(
        _agg(by_agent_avg_latency_ms={"DocumentGenerator": 10_000.0})
    )
    latency = next(r for r in snap.reports if r.slo_id == "pipeline-latency-p99")
    assert latency.status == SloStatus.BREACHED.value
    assert latency.error_budget_burn >= 1.0


def test_agent_success_rate_breach() -> None:
    snap = SloEvaluator(Settings()).evaluate(
        _agg(by_agent_success_rate={"PolicyResearcher": 0.50})
    )
    agent = next(r for r in snap.reports if r.slo_id == "agent-success-rate")
    assert agent.status == SloStatus.BREACHED.value


def test_overall_at_risk_when_any_at_risk() -> None:
    snap = SloEvaluator(Settings()).evaluate(_agg(denial_rate=0.19))
    assert snap.overall_status == SloStatus.AT_RISK.value


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_slo_endpoint_returns_snapshot(client: TestClient) -> None:
    r = client.get("/v1/slo/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert "overall_status" in body
    assert "reports" in body
    assert isinstance(body["reports"], list)
