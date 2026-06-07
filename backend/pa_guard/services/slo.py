"""SLO compute service.

Reads an `OutcomeAggregate` (from the existing `OutcomeLogger`) and turns
it into an `SloSnapshot` — per-SLO status (`met` / `at-risk` / `breached`)
plus a 30-day error-budget burn estimate.

The SLOs are deliberately platform-level (denial rate, pipeline latency,
FHE coverage, on-device voice share) rather than per-payer; per-payer
breakdowns live in the existing per-agent table on the dashboard.

Targets default to numbers that make sense for the v1.0 GA baseline but
can be overridden via env vars (`PAG_SLO_*`).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.config import Settings, get_settings
from ..core.models import OutcomeAggregate, SloSnapshot, SloStatus, SloTargetReport


@dataclass(frozen=True)
class SloTargets:
    denial_rate_max: float
    pipeline_p99_latency_ms_max: float
    fhe_executed_share_min: float
    on_device_voice_share_min: float
    agent_success_rate_min: float

    @classmethod
    def from_settings(cls, s: Settings) -> SloTargets:
        return cls(
            denial_rate_max=s.slo_denial_rate_max,
            pipeline_p99_latency_ms_max=s.slo_pipeline_p99_latency_ms_max,
            fhe_executed_share_min=s.slo_fhe_executed_share_min,
            on_device_voice_share_min=s.slo_on_device_voice_share_min,
            agent_success_rate_min=s.slo_agent_success_rate_min,
        )


class SloEvaluator:
    """Stateless SLO evaluator.

    `evaluate(aggregate)` returns a snapshot ready to be serialized over
    the API.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._targets = SloTargets.from_settings(self._settings)

    @property
    def targets(self) -> SloTargets:
        return self._targets

    def evaluate(self, aggregate: OutcomeAggregate) -> SloSnapshot:
        reports: list[SloTargetReport] = [
            self._lt_target(
                slo_id="denial-rate",
                description="Aggregate denial rate stays below the SLO ceiling.",
                actual=aggregate.denial_rate,
                target=self._targets.denial_rate_max,
                unit="ratio",
            ),
            self._gt_target(
                slo_id="fhe-coverage",
                description="Share of inferences executed under FHE.",
                actual=aggregate.fhe_executed_share,
                target=self._targets.fhe_executed_share_min,
                unit="ratio",
            ),
            self._gt_target(
                slo_id="voice-on-device",
                description=(
                    "Share of voice sessions where raw audio never left the device."
                ),
                actual=1.0 - aggregate.raw_audio_left_device_share,
                target=self._targets.on_device_voice_share_min,
                unit="ratio",
            ),
        ]

        # Pipeline p99 latency proxy = max of per-agent average latencies.
        # When we get true histograms in Phase 7 we'll swap this for a real
        # tail-latency calculation. Until then the worst-agent average is a
        # conservative under-estimate of p99.
        if aggregate.by_agent_avg_latency_ms:
            worst = max(aggregate.by_agent_avg_latency_ms.values())
            reports.append(
                self._lt_target(
                    slo_id="pipeline-latency-p99",
                    description="Slowest agent average (proxy for pipeline p99).",
                    actual=worst,
                    target=self._targets.pipeline_p99_latency_ms_max,
                    unit="ms",
                )
            )

        # Worst per-agent success rate.
        if aggregate.by_agent_success_rate:
            worst_agent, worst_rate = min(
                aggregate.by_agent_success_rate.items(), key=lambda kv: kv[1]
            )
            reports.append(
                self._gt_target(
                    slo_id="agent-success-rate",
                    description=f"Lowest per-agent success rate ({worst_agent}).",
                    actual=worst_rate,
                    target=self._targets.agent_success_rate_min,
                    unit="ratio",
                )
            )

        overall = self._aggregate_status(r.status for r in reports)
        return SloSnapshot(
            window_seconds=aggregate.window_seconds,
            sample_count=aggregate.sample_count,
            overall_status=overall,
            reports=reports,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate_status(statuses: object) -> SloStatus:
        seen = list(statuses)
        if any(s == SloStatus.BREACHED for s in seen):
            return SloStatus.BREACHED
        if any(s == SloStatus.AT_RISK for s in seen):
            return SloStatus.AT_RISK
        return SloStatus.MET

    @staticmethod
    def _lt_target(
        *,
        slo_id: str,
        description: str,
        actual: float,
        target: float,
        unit: str,
    ) -> SloTargetReport:
        """`actual` must stay STRICTLY below `target`. `at_risk` band is
        the top 10% of the budget."""
        if actual > target:
            status = SloStatus.BREACHED
        elif target > 0 and actual > target * 0.9:
            status = SloStatus.AT_RISK
        else:
            status = SloStatus.MET
        # Budget burn over a 30-day window: (actual - 0) / target, clipped to [0, 2].
        burn = min(2.0, max(0.0, actual / target)) if target > 0 else 0.0
        return SloTargetReport(
            slo_id=slo_id,
            description=description,
            target=target,
            actual=actual,
            unit=unit,
            direction="lt",
            status=status,
            error_budget_burn=burn,
        )

    @staticmethod
    def _gt_target(
        *,
        slo_id: str,
        description: str,
        actual: float,
        target: float,
        unit: str,
    ) -> SloTargetReport:
        """`actual` must stay STRICTLY above `target`."""
        if actual < target:
            status = SloStatus.BREACHED
        elif target < 1.0 and actual < target + (1.0 - target) * 0.1:
            status = SloStatus.AT_RISK
        else:
            status = SloStatus.MET
        # For "greater-than" SLOs, burn measures the *gap* from the target.
        # 1.0 = exactly at target; >1.0 = over-performing; <1.0 = behind.
        burn = max(0.0, (target - actual) / max(target, 1e-9))
        return SloTargetReport(
            slo_id=slo_id,
            description=description,
            target=target,
            actual=actual,
            unit=unit,
            direction="gt",
            status=status,
            error_budget_burn=min(2.0, burn),
        )


__all__ = ["SloEvaluator", "SloTargets"]
