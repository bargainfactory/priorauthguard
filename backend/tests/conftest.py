"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

from pa_guard.core.config import Settings, get_settings


@pytest.fixture(scope="session", autouse=True)
def _test_settings() -> None:
    """Force test environment regardless of host env."""
    get_settings.cache_clear()  # type: ignore[attr-defined]
    Settings()  # validates env-loaded config once at session start
