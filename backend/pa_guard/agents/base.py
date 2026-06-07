"""Base agent class with built-in self-critique.

Every specialized agent in the platform inherits from `BaseAgent`. The base
class:

1. Times every task and emits an `AgentCritique` record automatically.
2. Provides a standard `self_critique` hook that subclasses can override to
   inject task-specific KPIs (e.g. denial-risk score, FHE latency, voice
   word-error-rate).
3. Routes critiques to `OutcomeLogger` (Phase 2) for `MetaImprover` analysis.

The class is deliberately tiny — agents stay easy to reason about and easy to
unit-test in isolation.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar
from uuid import UUID

from ..core.logging import get_logger
from ..core.models import AgentCritique

TIn = TypeVar("TIn")
TOut = TypeVar("TOut")


class BaseAgent(ABC, Generic[TIn, TOut]):
    """Stateful base class for every agent.

    Subclasses implement `_run` and (optionally) `_extra_kpis` / `_observations`.
    Callers invoke `run`, which wraps the body with timing, logging, and
    self-critique emission.
    """

    #: Agents may opt out of self-critique (rare; only for trivial passthrough nodes).
    emits_critique: bool = True

    def __init__(self, name: str | None = None) -> None:
        self.name = name or type(self).__name__
        self._log = get_logger(self.name)
        # Hook injected by the supervisor in Phase 2 once OutcomeLogger lands.
        self._critique_sink: Callable[[AgentCritique], Awaitable[None]] | None = None

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def run(self, request_id: UUID, payload: TIn) -> TOut:
        from ..core.otel import get_tracer

        tracer = get_tracer()
        # When OTel is disabled, use a null context manager so the lifecycle
        # stays identical and we avoid any per-call branching cost.
        if tracer is not None:
            cm = tracer.start_as_current_span(f"agent.{self.name}")
        else:
            from contextlib import nullcontext

            cm = nullcontext(None)

        start = time.perf_counter()
        ok = True
        result: TOut
        with cm as span:
            if span is not None:
                span.set_attribute("pa_guard.agent.name", self.name)
                span.set_attribute("pa_guard.request_id", str(request_id))
            try:
                result = await self._run(payload)
                return result
            except Exception as exc:
                ok = False
                if span is not None:
                    span.record_exception(exc)
                self._log.error("agent_failed", error=str(exc), request_id=str(request_id))
                raise
            finally:
                latency_ms = (time.perf_counter() - start) * 1000
                if self.emits_critique:
                    critique = self._build_critique(
                        request_id=request_id,
                        latency_ms=latency_ms,
                        ok=ok,
                        payload=payload,
                        result=locals().get("result"),
                    )
                    if span is not None:
                        for k, v in critique.kpi.items():
                            span.set_attribute(f"pa_guard.kpi.{k}", v)
                    await self._emit_critique(critique)

    def attach_critique_sink(
        self, sink: Callable[[AgentCritique], Awaitable[None]]
    ) -> None:
        """Wire this agent's critiques into `OutcomeLogger` (Phase 2)."""
        self._critique_sink = sink

    # ------------------------------------------------------------------
    # To be overridden
    # ------------------------------------------------------------------

    @abstractmethod
    async def _run(self, payload: TIn) -> TOut:
        """The actual task body."""

    def _extra_kpis(self, payload: TIn, result: TOut | None) -> dict[str, float]:
        """Subclasses add quantitative task-specific KPIs here."""
        return {}

    def _observations(
        self, payload: TIn, result: TOut | None, ok: bool
    ) -> tuple[list[str], list[str], list[str]]:
        """Return (what_worked, what_failed, suggested_improvements)."""
        if ok:
            return ([f"{self.name} completed cleanly."], [], [])
        return ([], [f"{self.name} raised an exception."], [
            "Inspect logs and add a regression test reproducing the failure mode.",
        ])

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_critique(
        self,
        *,
        request_id: UUID,
        latency_ms: float,
        ok: bool,
        payload: TIn,
        result: TOut | None,
    ) -> AgentCritique:
        kpi: dict[str, float] = {"latency_ms": latency_ms, "success": 1.0 if ok else 0.0}
        kpi.update(self._extra_kpis(payload, result))
        worked, failed, suggested = self._observations(payload, result, ok)
        return AgentCritique(
            agent_name=self.name,
            request_id=request_id,
            kpi=kpi,
            what_worked=worked,
            what_failed=failed,
            suggested_improvements=suggested,
        )

    async def _emit_critique(self, critique: AgentCritique) -> None:
        # In Phase 0 we only log critiques. Phase 2 wires `OutcomeLogger`.
        self._log.info(
            "agent_critique",
            kpi=critique.kpi,
            what_worked=critique.what_worked,
            what_failed=critique.what_failed,
            suggested_improvements=critique.suggested_improvements,
            request_id=str(critique.request_id),
        )
        if self._critique_sink is not None:
            await self._critique_sink(critique)


__all__ = ["BaseAgent"]
