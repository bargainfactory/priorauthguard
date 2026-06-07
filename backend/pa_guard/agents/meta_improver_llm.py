"""LLM-backed MetaImprover — calls Anthropic Claude when a key is configured,
falls back to the Phase 2 heuristic engine otherwise.

Contract
--------
Same `ImprovementProposal` shape, same approval gate. The supervisor / API
caller can swap between the two without touching consumers — the LLM variant
is just a different *generator* feeding the same review surface.

Privacy
-------
The LLM only sees the **aggregate metrics** (`OutcomeAggregate`) and the
*structured* prompt-shaping inputs we hand it. It never sees raw critiques,
PA notes, voice transcripts, or any PHI-bearing payload.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.models import (
    ImprovementCategory,
    ImprovementProposal,
    ImprovementProposalStatus,
    OutcomeAggregate,
)
from .meta_improver import MetaImproverAgent

SYSTEM_PROMPT = (
    "You are PriorAuthGuard's MetaImprover. You read aggregate pipeline "
    "metrics and propose 1-5 concrete, actionable improvement proposals that "
    "the platform team can review and approve. Each proposal MUST be one of:\n"
    "  - prompt | rag | workflow | script | rule | circuit\n"
    "Constraints:\n"
    "  - NEVER reference any PHI; you have no access to it.\n"
    "  - Return STRICT JSON matching the schema below. No prose.\n"
    "Schema:\n"
    "{ \"proposals\": [ {\n"
    "   \"category\": <ImprovementCategory>,\n"
    "   \"target\": <agent or circuit name>,\n"
    "   \"title\": <short imperative>,\n"
    "   \"rationale\": <2-4 sentences citing metrics>,\n"
    "   \"confidence\": <0.0-1.0 float>,\n"
    "   \"supporting_metrics\": <map of metric name -> number>,\n"
    "   \"proposed_change\": <map of key -> string|number|string[]>\n"
    " } ] }"
)


@dataclass
class _LLMResult:
    proposals: list[dict[str, Any]]


class MetaImproverLLM:
    """LLM-backed proposal generator with a deterministic fallback."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        heuristic: MetaImproverAgent | None = None,
        client: object | None = None,   # opaque, lets tests inject a fake
    ) -> None:
        self._settings = settings or get_settings()
        self._log = get_logger("MetaImproverLLM")
        self._heuristic = heuristic or MetaImproverAgent()
        self._client = client

    # ------------------------------------------------------------------

    async def propose(self, aggregate: OutcomeAggregate) -> list[ImprovementProposal]:
        if not self._settings.anthropic_api_key and self._client is None:
            self._log.info("meta_improver_llm_falling_back_no_key")
            return self._heuristic.propose(aggregate)

        try:
            llm = await self._call_llm(aggregate)
        except Exception as exc:  # pragma: no cover — defensive
            self._log.warning("meta_improver_llm_failed", error=str(exc))
            return self._heuristic.propose(aggregate)

        # If the LLM produced nothing usable, still surface heuristic signals.
        if not llm.proposals:
            return self._heuristic.propose(aggregate)
        out = [self._to_proposal(p) for p in llm.proposals]
        return [p for p in out if p is not None]

    # ------------------------------------------------------------------

    async def _call_llm(self, aggregate: OutcomeAggregate) -> _LLMResult:
        client = self._client or await self._build_client()
        prompt = self._render_prompt(aggregate)
        # The anthropic SDK is sync-with-async-helper. We use the async client
        # when available and fall back to sync inside `run_in_executor` so
        # injected fakes can be either shape.
        response_text = await self._send(client, prompt)
        return _LLMResult(proposals=self._parse_json(response_text))

    async def _build_client(self) -> object:
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover — install-time guard
            raise RuntimeError(
                "anthropic is required for MetaImproverLLM; "
                "install with `pip install anthropic`."
            ) from e
        return anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key)

    async def _send(self, client: object, prompt: str) -> str:
        # Accept either an `AsyncAnthropic` client or a test double exposing
        # a `messages.create(...)` coroutine.
        messages = getattr(client, "messages", None)
        if messages is None:
            raise RuntimeError("LLM client has no .messages accessor")
        create = messages.create
        if asyncio.iscoroutinefunction(create):
            response = await create(
                model=self._settings.meta_improver_model,
                max_tokens=self._settings.meta_improver_max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        else:  # sync client — run in default thread pool
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: create(
                    model=self._settings.meta_improver_model,
                    max_tokens=self._settings.meta_improver_max_tokens,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )
        # Anthropic returns a `Message` with `.content` as a list of blocks.
        blocks = getattr(response, "content", None) or []
        for b in blocks:
            text = getattr(b, "text", None)
            if isinstance(text, str) and text.strip():
                return text
        return ""

    # ------------------------------------------------------------------

    @staticmethod
    def _render_prompt(agg: OutcomeAggregate) -> str:
        return (
            "Aggregate pipeline metrics (no PHI present):\n"
            f"```json\n{json.dumps(agg.model_dump(mode='json'), default=str, indent=2)}\n```\n\n"
            "Produce JSON per the schema. Prioritize proposals with the "
            "highest expected impact on denial rate and FHE coverage."
        )

    @staticmethod
    def _parse_json(text: str) -> list[dict[str, Any]]:
        # The model sometimes wraps JSON in ``` fences; strip them.
        s = text.strip()
        if s.startswith("```"):
            s = s.strip("`")
            # Drop a leading "json" tag if present.
            s = s.lstrip("json").lstrip()
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, dict):
            return []
        items = parsed.get("proposals")
        return items if isinstance(items, list) else []

    @staticmethod
    def _to_proposal(raw: dict[str, Any]) -> ImprovementProposal | None:
        try:
            category = ImprovementCategory(str(raw.get("category", "")).strip())
        except ValueError:
            return None
        confidence = float(raw.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        return ImprovementProposal(
            proposal_id=uuid4(),
            category=category,
            target=str(raw.get("target", "unknown")),
            title=str(raw.get("title", "Improvement"))[:256],
            rationale=str(raw.get("rationale", ""))[:4096],
            supporting_metrics={
                str(k): float(v) for k, v in (raw.get("supporting_metrics") or {}).items()
                if isinstance(v, (int, float))
            },
            confidence=confidence,
            proposed_change={
                str(k): v for k, v in (raw.get("proposed_change") or {}).items()
                if isinstance(v, (str, int, float, list))
            },
            status=ImprovementProposalStatus.PROPOSED,
        )


__all__ = ["MetaImproverLLM"]
