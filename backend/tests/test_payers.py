"""Payer adapter framework tests."""
from __future__ import annotations

import pytest

from pa_guard.core.config import Settings
from pa_guard.core.models import SubmissionChannel
from pa_guard.payers.registry import PayerAdapterRegistry


def test_unknown_payer_falls_back_to_stub_via_availity_channel() -> None:
    reg = PayerAdapterRegistry(settings=Settings())
    adapter, channel = reg.resolve("payer-that-does-not-exist")
    assert channel == SubmissionChannel.API
    # No credentials → StubAdapter
    from pa_guard.agents.submission import StubAdapter

    assert isinstance(adapter, StubAdapter)


def test_anthem_routes_to_availity_with_stub_fallback_when_no_credentials() -> None:
    reg = PayerAdapterRegistry(settings=Settings())
    adapter, channel = reg.resolve("anthem")
    assert channel == SubmissionChannel.API
    from pa_guard.agents.submission import StubAdapter

    assert isinstance(adapter, StubAdapter)


def test_anthem_routes_to_availity_when_credentials_present() -> None:
    s = Settings(
        availity_client_id="dummy-id",
        availity_client_secret="dummy-secret",
    )
    reg = PayerAdapterRegistry(settings=s)
    adapter, channel = reg.resolve("anthem")
    assert channel == SubmissionChannel.API
    from pa_guard.payers.availity import AvailityAdapter

    assert isinstance(adapter, AvailityAdapter)


def test_ohip_routes_to_fax_family_with_portal_channel() -> None:
    reg = PayerAdapterRegistry(settings=Settings())
    _, channel = reg.resolve("ohip")
    assert channel == SubmissionChannel.PORTAL


def test_cms_medicare_routes_to_covermymeds() -> None:
    s = Settings(covermymeds_api_key="dummy-key")
    reg = PayerAdapterRegistry(settings=s)
    adapter, channel = reg.resolve("cms-medicare")
    assert channel == SubmissionChannel.API
    from pa_guard.payers.covermymeds import CoverMyMedsAdapter

    assert isinstance(adapter, CoverMyMedsAdapter)


def test_nhs_routes_to_nhs_spine_when_credentials_present() -> None:
    s = Settings(nhs_spine_api_key="dummy-key")
    reg = PayerAdapterRegistry(settings=s)
    adapter, channel = reg.resolve("nhs-england")
    assert channel == SubmissionChannel.PORTAL
    from pa_guard.payers.nhs import NhsSpineAdapter

    assert isinstance(adapter, NhsSpineAdapter)


def test_availity_constructor_rejects_missing_credentials() -> None:
    from pa_guard.payers.availity import AvailityAdapter

    with pytest.raises(RuntimeError, match="credentials missing"):
        AvailityAdapter(settings=Settings())


def test_covermymeds_constructor_rejects_missing_credentials() -> None:
    from pa_guard.payers.covermymeds import CoverMyMedsAdapter

    with pytest.raises(RuntimeError, match="credentials missing"):
        CoverMyMedsAdapter(settings=Settings())


def test_surescripts_constructor_rejects_missing_credentials() -> None:
    from pa_guard.payers.surescripts import SurescriptsAdapter

    with pytest.raises(RuntimeError, match="credentials missing"):
        SurescriptsAdapter(settings=Settings())


def test_fax_constructor_rejects_missing_credentials() -> None:
    from pa_guard.payers.fax import FaxAdapter

    with pytest.raises(RuntimeError, match="credentials missing"):
        FaxAdapter(settings=Settings())


def test_nhs_constructor_rejects_missing_credentials() -> None:
    from pa_guard.payers.nhs import NhsSpineAdapter

    with pytest.raises(RuntimeError, match="credentials missing"):
        NhsSpineAdapter(settings=Settings())
