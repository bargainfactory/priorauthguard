"""OpenTelemetry no-op behavior tests.

We don't try to install the real OTel SDK in CI here — the goal is to lock
in the contract that *every* code path stays a no-op when
`PAG_OTEL_ENABLED` is false. That's the path the existing tests rely on.

A separate integration test (`backend/tests/integration/test_otel_live.py`)
exercises the real SDK once it's available in CI.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from pa_guard.agents.base import BaseAgent
from pa_guard.core.config import Settings
from pa_guard.core.otel import configure_otel, get_tracer, traced_agent_run


def test_configure_otel_is_noop_when_disabled() -> None:
    s = Settings(otel_enabled=False)
    assert configure_otel(app=None, settings=s) is False
    assert get_tracer() is None


def test_traced_agent_run_no_tracer_is_passthrough() -> None:
    async def my_fn(x: int) -> int:
        return x + 1

    decorated = traced_agent_run("Test")(my_fn)
    import asyncio

    assert asyncio.run(decorated(2)) == 3


class _CountAgent(BaseAgent[int, int]):
    """Trivial subclass that lets us drive `BaseAgent.run` without OTel."""

    async def _run(self, payload: int) -> int:
        return payload * 2


@pytest.mark.asyncio
async def test_base_agent_run_works_with_otel_disabled() -> None:
    agent = _CountAgent(name="CountAgent")
    out = await agent.run(uuid4(), 7)
    assert out == 14
