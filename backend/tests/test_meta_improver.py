"""MetaImproverAgent heuristics tests."""
from __future__ import annotations

import pytest

from pa_guard.agents.meta_improver import MetaImproverAgent
from pa_guard.core.models import (
    ImprovementCategory,
    ImprovementProposalStatus,
    OutcomeAggregate,
)

pytestmark = pytest.mark.compliance


def _agg(**overrides) -> OutcomeAggregate:
    base = {
        "window_seconds": 0,
        "sample_count": 50,
        "by_agent_avg_latency_ms": {},
        "by_agent_success_rate": {},
        "denial_rate": 0.05,
        "appeal_success_rate": 0.0,
        "fhe_executed_share": 1.0,
        "avg_fhe_latency_ms": 50.0,
        "avg_voice_call_duration_seconds": 30.0,
        "raw_audio_left_device_share": 0.0,
    }
    base.update(overrides)
    return OutcomeAggregate(**base)


def test_no_proposals_on_healthy_aggregate() -> None:
    agg = _agg()
    proposals = MetaImproverAgent().propose(agg)
    assert proposals == []


def test_high_denial_rate_triggers_prompt_proposal() -> None:
    agg = _agg(denial_rate=0.45)
    proposals = MetaImproverAgent().propose(agg)
    assert any(
        p.category == ImprovementCategory.PROMPT.value
        and p.target == "DocumentGeneratorAgent"
        for p in proposals
    )


def test_slow_agent_triggers_workflow_proposal() -> None:
    agg = _agg(by_agent_avg_latency_ms={"PolicyResearcherAgent": 2500.0})
    proposals = MetaImproverAgent().propose(agg)
    assert any(
        p.category == ImprovementCategory.WORKFLOW.value
        and p.target == "PolicyResearcherAgent"
        for p in proposals
    )


def test_low_fhe_share_triggers_circuit_proposal() -> None:
    agg = _agg(fhe_executed_share=0.0)
    proposals = MetaImproverAgent().propose(agg)
    assert any(p.category == ImprovementCategory.CIRCUIT.value for p in proposals)


def test_audio_leaving_device_triggers_workflow_proposal() -> None:
    agg = _agg(raw_audio_left_device_share=0.3)
    proposals = MetaImproverAgent().propose(agg)
    assert any(
        p.category == ImprovementCategory.WORKFLOW.value
        and p.target == "VoiceOrchestratorAgent"
        for p in proposals
    )


def test_low_success_rate_triggers_prompt_proposal() -> None:
    agg = _agg(by_agent_success_rate={"SubmissionAgent": 0.6})
    proposals = MetaImproverAgent().propose(agg)
    assert any(
        p.category == ImprovementCategory.PROMPT.value
        and p.target == "SubmissionAgent"
        for p in proposals
    )


def test_proposals_default_to_proposed_status() -> None:
    agg = _agg(denial_rate=0.45)
    [p] = [p for p in MetaImproverAgent().propose(agg) if p.target == "DocumentGeneratorAgent"]
    assert p.status == ImprovementProposalStatus.PROPOSED.value
