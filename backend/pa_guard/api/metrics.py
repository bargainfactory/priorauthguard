"""Prometheus metrics endpoint.

Exposes the SLO snapshot, per-agent latency / success aggregates, and a
small set of pipeline counters in Prometheus' text format at `/metrics`.

This is the surface Prometheus / OTel Collector scrapes — it's how the
Grafana SLO dashboard turns the in-memory `OutcomeLogger` aggregates
into time-series. Production deployments typically front this with the
OTel Collector's `prometheus` receiver so cardinality is managed
centrally.

PHI contract: every label is a hardcoded enumeration (`agent`, `slo_id`),
no PHI is ever attached.
"""
from __future__ import annotations

import io
from typing import TYPE_CHECKING

from fastapi import APIRouter, Response

if TYPE_CHECKING:
    from ..core.models import OutcomeAggregate, SloSnapshot
    from .main import PASupervisor  # only for type hints; circular at runtime

router = APIRouter()


def _emit_metric(buf: io.StringIO, name: str, help_text: str, type_: str) -> None:
    buf.write(f"# HELP {name} {help_text}\n")
    buf.write(f"# TYPE {name} {type_}\n")


def _render(agg: OutcomeAggregate, slo: SloSnapshot) -> str:
    buf = io.StringIO()

    _emit_metric(buf, "pa_guard_sample_count", "Aggregate samples in window", "gauge")
    buf.write(f"pa_guard_sample_count {agg.sample_count}\n")

    _emit_metric(buf, "pa_guard_denial_rate", "Denial rate in window", "gauge")
    buf.write(f"pa_guard_denial_rate {agg.denial_rate}\n")

    _emit_metric(buf, "pa_guard_fhe_executed_share", "FHE-executed share", "gauge")
    buf.write(f"pa_guard_fhe_executed_share {agg.fhe_executed_share}\n")

    _emit_metric(
        buf,
        "pa_guard_raw_audio_left_device_share",
        "Share of voice sessions where raw audio left the device (lower is better)",
        "gauge",
    )
    buf.write(f"pa_guard_raw_audio_left_device_share {agg.raw_audio_left_device_share}\n")

    _emit_metric(
        buf,
        "pa_guard_agent_avg_latency_ms",
        "Average per-agent latency (ms)",
        "gauge",
    )
    for agent, latency in agg.by_agent_avg_latency_ms.items():
        buf.write(
            f'pa_guard_agent_avg_latency_ms{{agent="{_label(agent)}"}} {latency}\n'
        )

    _emit_metric(
        buf,
        "pa_guard_agent_success_rate",
        "Per-agent success rate in window",
        "gauge",
    )
    for agent, rate in agg.by_agent_success_rate.items():
        buf.write(
            f'pa_guard_agent_success_rate{{agent="{_label(agent)}"}} {rate}\n'
        )

    # SLO snapshot — emit per-SLO status and budget burn.
    _emit_metric(
        buf,
        "pa_guard_slo_target",
        "SLO target value (lt / gt depending on direction)",
        "gauge",
    )
    for r in slo.reports:
        buf.write(
            f'pa_guard_slo_target{{slo_id="{_label(r.slo_id)}",direction="{r.direction}"}} '
            f"{r.target}\n"
        )

    _emit_metric(buf, "pa_guard_slo_actual", "SLO actual value", "gauge")
    for r in slo.reports:
        buf.write(
            f'pa_guard_slo_actual{{slo_id="{_label(r.slo_id)}",direction="{r.direction}"}} '
            f"{r.actual}\n"
        )

    _emit_metric(
        buf,
        "pa_guard_slo_status",
        "SLO status — 0=met, 1=at-risk, 2=breached",
        "gauge",
    )
    status_map = {"met": 0, "at-risk": 1, "breached": 2}
    for r in slo.reports:
        buf.write(
            f'pa_guard_slo_status{{slo_id="{_label(r.slo_id)}"}} '
            f"{status_map.get(str(r.status), 0)}\n"
        )

    _emit_metric(
        buf,
        "pa_guard_slo_burn",
        "Error-budget burn; >=1 is a breach",
        "gauge",
    )
    for r in slo.reports:
        buf.write(
            f'pa_guard_slo_burn{{slo_id="{_label(r.slo_id)}"}} {r.error_budget_burn}\n'
        )

    _emit_metric(
        buf,
        "pa_guard_slo_overall_status",
        "Overall SLO status — 0=met, 1=at-risk, 2=breached",
        "gauge",
    )
    buf.write(
        f"pa_guard_slo_overall_status {status_map.get(str(slo.overall_status), 0)}\n"
    )

    return buf.getvalue()


def _label(s: str) -> str:
    # Prometheus labels — escape backslashes, quotes, and newlines.
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@router.get("/metrics", tags=["meta"], include_in_schema=False)
async def metrics() -> Response:
    from ..services.slo import SloEvaluator
    from .main import app

    supervisor: PASupervisor = app.state.supervisor
    aggregate = await supervisor.outcome_logger.aggregate(window_seconds=0)
    snapshot = SloEvaluator().evaluate(aggregate)
    body = _render(aggregate, snapshot)
    return Response(content=body, media_type="text/plain; version=0.0.4")


__all__ = ["router"]
