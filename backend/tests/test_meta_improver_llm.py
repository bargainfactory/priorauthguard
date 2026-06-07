"""MetaImproverLLM tests — covers Anthropic injection + graceful fallback."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from pa_guard.agents.meta_improver_llm import MetaImproverLLM
from pa_guard.core.config import Settings
from pa_guard.core.models import OutcomeAggregate

pytestmark = pytest.mark.asyncio


def _agg(**overrides: Any) -> OutcomeAggregate:
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


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

@dataclass
class _Block:
    text: str


@dataclass
class _Response:
    content: list[_Block]


@dataclass
class _Messages:
    payload: dict

    async def create(self, **kwargs: Any) -> _Response:
        text = json.dumps(self.payload)
        return _Response(content=[_Block(text=text)])


@dataclass
class _FakeClient:
    payload: dict

    @property
    def messages(self) -> _Messages:
        return _Messages(payload=self.payload)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_falls_back_to_heuristic_when_no_api_key() -> None:
    settings = Settings(anthropic_api_key=None)
    llm = MetaImproverLLM(settings=settings)
    proposals = await llm.propose(_agg(denial_rate=0.45))
    # Heuristic fires its high-denial-rate proposal.
    assert any(p.target == "DocumentGeneratorAgent" for p in proposals)


async def test_uses_llm_proposals_when_client_returns_valid_json() -> None:
    fake = _FakeClient(
        payload={
            "proposals": [
                {
                    "category": "prompt",
                    "target": "DocumentGeneratorAgent",
                    "title": "Cite UM criteria explicitly",
                    "rationale": "LLM rationale.",
                    "confidence": 0.82,
                    "supporting_metrics": {"denial_rate": 0.35},
                    "proposed_change": {"add_section": "UM Criteria"},
                }
            ]
        }
    )
    settings = Settings(anthropic_api_key="sk-test")
    llm = MetaImproverLLM(settings=settings, client=fake)
    proposals = await llm.propose(_agg(denial_rate=0.35))
    assert len(proposals) == 1
    p = proposals[0]
    assert p.target == "DocumentGeneratorAgent"
    assert p.confidence == pytest.approx(0.82)
    assert p.proposed_change["add_section"] == "UM Criteria"


async def test_invalid_llm_json_falls_back_to_heuristic() -> None:
    fake = _FakeClient(payload={"not": "proposals"})
    settings = Settings(anthropic_api_key="sk-test")
    llm = MetaImproverLLM(settings=settings, client=fake)
    proposals = await llm.propose(_agg(denial_rate=0.45))
    # Should not be empty: heuristic kicks in.
    assert any(p.target == "DocumentGeneratorAgent" for p in proposals)


async def test_llm_proposals_default_to_proposed_status() -> None:
    fake = _FakeClient(
        payload={
            "proposals": [
                {
                    "category": "rag",
                    "target": "PolicyResearcherAgent",
                    "title": "Add 2026 CMS NCD updates to corpus",
                    "rationale": "rag bump",
                    "confidence": 0.5,
                }
            ]
        }
    )
    settings = Settings(anthropic_api_key="sk-test")
    llm = MetaImproverLLM(settings=settings, client=fake)
    [p] = await llm.propose(_agg())
    assert p.status == "proposed"
