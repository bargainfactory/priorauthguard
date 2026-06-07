"""Shared fixtures for the live-sandbox integration suite.

These tests are **disabled by default** — they only run when:

  PAG_RUN_LIVE_SANDBOX_TESTS=true

is set in the environment AND the relevant payer credentials are present.
Without those, every test in this directory is `pytest.skip`-ped so the
default `pytest -q` run stays hermetic.

CI runs this suite as a separate manual job (see `ci/ci.yml.template`)
when secrets are provisioned.
"""
from __future__ import annotations

import os

import pytest

from pa_guard.core.config import Settings


def _flag_enabled() -> bool:
    return os.environ.get("PAG_RUN_LIVE_SANDBOX_TESTS", "false").lower() == "true"


def _settings() -> Settings:
    # Avoid the lru_cache so tests see the env each time.
    return Settings()


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    if not _flag_enabled():
        pytest.skip("PAG_RUN_LIVE_SANDBOX_TESTS is not enabled.")
    return _settings()


def require_availity_credentials() -> Settings:
    s = _settings()
    if not _flag_enabled():
        pytest.skip("PAG_RUN_LIVE_SANDBOX_TESTS is not enabled.")
    if not (s.availity_client_id and s.availity_client_secret):
        pytest.skip("Availity credentials missing.")
    return s


def require_covermymeds_credentials() -> Settings:
    s = _settings()
    if not _flag_enabled():
        pytest.skip("PAG_RUN_LIVE_SANDBOX_TESTS is not enabled.")
    if not s.covermymeds_api_key:
        pytest.skip("CoverMyMeds credentials missing.")
    return s


def require_surescripts_credentials() -> Settings:
    s = _settings()
    if not _flag_enabled():
        pytest.skip("PAG_RUN_LIVE_SANDBOX_TESTS is not enabled.")
    if not (s.surescripts_client_id and s.surescripts_client_secret):
        pytest.skip("Surescripts credentials missing.")
    return s


def require_nhs_credentials() -> Settings:
    s = _settings()
    if not _flag_enabled():
        pytest.skip("PAG_RUN_LIVE_SANDBOX_TESTS is not enabled.")
    if not s.nhs_spine_api_key:
        pytest.skip("NHS Spine credentials missing.")
    return s
