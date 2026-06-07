"""Prometheus /metrics endpoint smoke tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pa_guard.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_metrics_endpoint_returns_prometheus_text(client: TestClient) -> None:
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    # The aggregate gauges are always present.
    assert "pa_guard_sample_count" in body
    assert "pa_guard_denial_rate" in body
    assert "pa_guard_fhe_executed_share" in body
    # SLO gauges + overall status are always present.
    assert "pa_guard_slo_target" in body
    assert "pa_guard_slo_actual" in body
    assert "pa_guard_slo_status" in body
    assert "pa_guard_slo_overall_status" in body


def test_metrics_endpoint_emits_help_and_type_lines(client: TestClient) -> None:
    body = client.get("/metrics").text
    # Prometheus exposition format requires HELP + TYPE before each metric.
    assert "# HELP pa_guard_denial_rate" in body
    assert "# TYPE pa_guard_denial_rate gauge" in body
