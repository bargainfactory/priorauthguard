"""MetaImproverAgent — turn aggregate critiques into concrete improvement proposals.

How it works
------------
1. Read an `OutcomeAggregate` from `OutcomeLogger`.
2. Apply a small library of declarative *heuristics* that pattern-match against
   the aggregate and emit `ImprovementProposal`s with a confidence score.
3. Every proposal is gated on **human approval** — the supervisor / API
   surface presents them, an authorized user approves, and only then does
   the supervisor apply the change. The agent itself never mutates running
   configuration.

Why heuristics (Phase 2)
------------------------
A learned proposal generator (a small LLM driven by the aggregated logs and
the current config) is the Phase 5 upgrade. The Phase 2 heuristics establish
the contract — proposal shape, approval gate, persistence — so the future
learned variant slots in behind the same interface without touching the rest
of the platform.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..core.models import (
    ImprovementCategory,
    ImprovementProposal,
    OutcomeAggregate,
)

# ---------------------------------------------------------------------------
# Heuristic primitives
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Heuristic:
    name: str
    fire: Callable[[OutcomeAggregate], ImprovementProposal | None]


def _high_denial_rate(agg: OutcomeAggregate) -> ImprovementProposal | None:
    if agg.denial_rate <= 0.30 or agg.sample_count < 5:
        return None
    return ImprovementProposal(
        category=ImprovementCategory.PROMPT,
        target="DocumentGeneratorAgent",
        title="Strengthen step-therapy documentation in narrative.",
        rationale=(
            f"Aggregate denial rate is {agg.denial_rate:.0%} across "
            f"{agg.sample_count} samples — well above the 20% target. "
            "Most denials cite insufficient documentation of conservative therapy."
        ),
        supporting_metrics={"denial_rate": agg.denial_rate},
        confidence=min(0.95, 0.5 + agg.denial_rate),
        proposed_change={
            "narrative_template_addition": (
                "Include explicit duration and modality of prior conservative therapy "
                "(e.g., '6 weeks physical therapy, 4 weeks NSAIDs') when present."
            ),
        },
    )


def _slow_agent(agg: OutcomeAggregate) -> ImprovementProposal | None:
    if not agg.by_agent_avg_latency_ms:
        return None
    slowest = max(
        agg.by_agent_avg_latency_ms.items(), key=lambda kv: kv[1]
    )
    name, latency = slowest
    if latency < 1000:  # under 1s — fine
        return None
    return ImprovementProposal(
        category=ImprovementCategory.WORKFLOW,
        target=name,
        title=f"Optimize {name} — average latency {latency:.0f} ms exceeds 1s target.",
        rationale=(
            f"{name} dominates pipeline latency. Consider caching, parallel "
            "RAG fan-out, or moving the agent off the critical path."
        ),
        supporting_metrics={"avg_latency_ms": latency},
        confidence=0.6,
        proposed_change={"caching": "enable per-jurisdiction LRU on RAG queries"},
    )


def _low_fhe_share(agg: OutcomeAggregate) -> ImprovementProposal | None:
    if agg.sample_count < 5 or agg.fhe_executed_share >= 0.10:
        return None
    return ImprovementProposal(
        category=ImprovementCategory.CIRCUIT,
        target="FHEInferenceService",
        title="Promote denial_risk_v0 from plaintext baseline to FHE.",
        rationale=(
            f"Only {agg.fhe_executed_share:.0%} of inferences executed under FHE. "
            "Compile the QAT-Brevitas circuit and enable PAG_FHE_ENABLED."
        ),
        supporting_metrics={"fhe_executed_share": agg.fhe_executed_share},
        confidence=0.7,
        proposed_change={
            "actions": [
                "python -m pa_guard.scripts.train_circuits denial_risk_v0",
                "set PAG_FHE_ENABLED=true",
            ],
        },
    )


def _voice_audio_leaving_device(agg: OutcomeAggregate) -> ImprovementProposal | None:
    if agg.raw_audio_left_device_share <= 0.10:
        return None
    return ImprovementProposal(
        category=ImprovementCategory.WORKFLOW,
        target="VoiceOrchestratorAgent",
        title="Default inbound dictation to on-device Whisper.",
        rationale=(
            f"{agg.raw_audio_left_device_share:.0%} of voice sessions had raw audio "
            "leave the device. Inbound dictation should always use on-device Whisper."
        ),
        supporting_metrics={"raw_audio_left_device_share": agg.raw_audio_left_device_share},
        confidence=0.85,
        proposed_change={
            "routing_rule": "direction == 'inbound-dictation' → ON_DEVICE_WHISPER always",
        },
    )


def _low_success_rate(agg: OutcomeAggregate) -> ImprovementProposal | None:
    if not agg.by_agent_success_rate:
        return None
    worst = min(agg.by_agent_success_rate.items(), key=lambda kv: kv[1])
    name, rate = worst
    if rate >= 0.90:
        return None
    return ImprovementProposal(
        category=ImprovementCategory.PROMPT,
        target=name,
        title=f"Investigate {name} — success rate {rate:.0%} below 90% target.",
        rationale=(
            f"{name} has the lowest success rate in the aggregate window. "
            "Examine recent critiques' `what_failed` for a repeated failure mode."
        ),
        supporting_metrics={"success_rate": rate},
        confidence=0.55,
        proposed_change={"action": "review recent critiques and add a regression test"},
    )


_HEURISTICS: tuple[_Heuristic, ...] = (
    _Heuristic("high_denial_rate", _high_denial_rate),
    _Heuristic("slow_agent", _slow_agent),
    _Heuristic("low_fhe_share", _low_fhe_share),
    _Heuristic("voice_audio_leaving_device", _voice_audio_leaving_device),
    _Heuristic("low_success_rate", _low_success_rate),
)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class MetaImproverAgent:
    """Stateless — `propose(aggregate)` is the only entry point."""

    def __init__(self) -> None:
        self.name = "MetaImproverAgent"

    def propose(self, aggregate: OutcomeAggregate) -> list[ImprovementProposal]:
        out: list[ImprovementProposal] = []
        for h in _HEURISTICS:
            proposal = h.fire(aggregate)
            if proposal is not None:
                out.append(proposal)
        # Highest confidence first so reviewers see the highest-signal items.
        out.sort(key=lambda p: p.confidence, reverse=True)
        return out


__all__ = ["MetaImproverAgent"]
