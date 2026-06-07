"""Coverage tests for the jurisdiction registry."""
from __future__ import annotations

import pytest

from pa_guard.compliance.jurisdictions import (
    ALL_JURISDICTIONS,
    CA_PROVINCES,
    UK_NATIONS,
    US_STATES,
    lookup,
)

pytestmark = pytest.mark.compliance


def test_us_states_full_coverage() -> None:
    # 50 states + DC
    assert len(US_STATES) == 51
    codes = {j.code for j in US_STATES}
    for required in ("CA", "TX", "NY", "FL", "DC"):
        assert required in codes


def test_canadian_provinces_full_coverage() -> None:
    # 10 provinces + 3 territories = 13
    assert len(CA_PROVINCES) == 13
    codes = {j.code for j in CA_PROVINCES}
    for required in ("ON", "QC", "BC", "AB", "YT", "NT", "NU"):
        assert required in codes


def test_uk_nations() -> None:
    assert len(UK_NATIONS) == 4
    assert {j.code for j in UK_NATIONS} == {"GB-ENG", "GB-SCT", "GB-WLS", "GB-NIR"}


def test_lookup_roundtrip() -> None:
    assert lookup("CA").name == "California"
    assert lookup("on").code == "ON"


def test_lookup_unknown_raises() -> None:
    with pytest.raises(KeyError):
        lookup("ZZ")


def test_quebec_has_law25() -> None:
    qc = next(j for j in CA_PROVINCES if j.code == "QC")
    assert "Law-25" in qc.privacy_frameworks


def test_england_has_uk_gdpr_and_nhs_dspt() -> None:
    eng = next(j for j in UK_NATIONS if j.code == "GB-ENG")
    assert "UK-GDPR" in eng.privacy_frameworks
    assert "NHS-DSPT" in eng.privacy_frameworks


def test_registry_total() -> None:
    # 51 US + 1 US-fed + 13 CA + 1 CA-fed + 4 UK = 70
    assert len(ALL_JURISDICTIONS) == 70
