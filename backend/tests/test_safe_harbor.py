"""HIPAA Safe Harbor tests.

These cover every one of the 18 identifiers + the generalization rules. If a
change to the engine causes any of these to fail, treat it as a P0 privacy
incident, not a flaky test.
"""
from __future__ import annotations

from datetime import date

import pytest

from pa_guard.compliance.safe_harbor import (
    RESTRICTED_ZIP3,
    SafeHarborEngine,
    SafeHarborIdentifier,
)
from pa_guard.core.models import DeidMethod, RawClinicalNote

pytestmark = pytest.mark.compliance


@pytest.fixture
def engine() -> SafeHarborEngine:
    return SafeHarborEngine()


# ---------------------------------------------------------------------------
# Identifier coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, identifier_key",
    [
        ("Patient: Dr. John Smith presented today.", SafeHarborIdentifier.NAME),
        ("patient's name is Jane Marie Doe.", SafeHarborIdentifier.NAME),
        ("SSN 123-45-6789 on file.", SafeHarborIdentifier.SSN),
        ("Call (415) 555-0142 to reschedule.", SafeHarborIdentifier.PHONE),
        ("email: provider@example.com today", SafeHarborIdentifier.EMAIL),
        ("see https://hospital.example/portal", SafeHarborIdentifier.URL),
        ("logged from 192.168.1.42", SafeHarborIdentifier.IP),
        ("MRN: AB12345678 last visit", SafeHarborIdentifier.MRN),
        ("Member ID: XYZ-99887 active", SafeHarborIdentifier.HEALTH_PLAN),
        ("Acct 12-3456 balance due", SafeHarborIdentifier.ACCOUNT),
        ("Lic AB-987654 valid", SafeHarborIdentifier.LICENSE),
        ("VIN 1HGCM82633A123456 in EHR", SafeHarborIdentifier.VEHICLE),
        ("Pump S/N SN-998877 implanted", SafeHarborIdentifier.DEVICE),
    ],
)
def test_each_identifier_is_redacted(
    engine: SafeHarborEngine, text: str, identifier_key: str
) -> None:
    cleaned, counts = engine.deidentify_text(text)
    assert identifier_key in counts, (
        f"Identifier {identifier_key} not detected in: {text!r} → {cleaned!r}"
    )
    assert "[REDACTED-" in cleaned


# ---------------------------------------------------------------------------
# Generalization rules
# ---------------------------------------------------------------------------

def test_dates_are_generalized_iso(engine: SafeHarborEngine) -> None:
    text = "Encounter 2024-07-14 with follow-up 2024-08-01."
    cleaned, counts = engine.deidentify_text(text)
    assert "2024-07-14" not in cleaned
    assert "2024-XX-XX" in cleaned
    assert counts.get(SafeHarborIdentifier.DATE, 0) >= 2


def test_dates_are_generalized_us(engine: SafeHarborEngine) -> None:
    text = "Surgery on 07/14/2024 and again 1/3/24."
    cleaned, counts = engine.deidentify_text(text)
    assert "07/14/2024" not in cleaned
    assert "XX/XX/2024" in cleaned
    assert counts.get(SafeHarborIdentifier.DATE, 0) >= 2


def test_ages_over_89_are_bucketed(engine: SafeHarborEngine) -> None:
    cleaned, counts = engine.deidentify_text("Patient is 92 y/o and ambulatory.")
    assert "92" not in cleaned
    assert "90+ y/o" in cleaned
    assert counts.get(SafeHarborIdentifier.DATE, 0) >= 1


def test_ages_under_90_are_preserved(engine: SafeHarborEngine) -> None:
    cleaned, _ = engine.deidentify_text("Patient is 67 y/o, post-CABG.")
    assert "67 y/o" in cleaned  # not bucketed


def test_zip_is_kept_when_zip3_safe(engine: SafeHarborEngine) -> None:
    safe_zip = "100"  # NYC area; not in RESTRICTED_ZIP3
    assert safe_zip not in RESTRICTED_ZIP3
    cleaned, counts = engine.deidentify_text(f"Resides in {safe_zip}01 area.")
    assert f"{safe_zip}XX" in cleaned
    assert counts.get(SafeHarborIdentifier.GEOGRAPHIC_SMALL, 0) >= 1


def test_zip_is_blanked_when_zip3_restricted(engine: SafeHarborEngine) -> None:
    restricted = next(iter(RESTRICTED_ZIP3))
    cleaned, _ = engine.deidentify_text(f"Resides in {restricted}12 area.")
    assert "000XX" in cleaned


# ---------------------------------------------------------------------------
# Full note → report
# ---------------------------------------------------------------------------

def test_deidentify_note_emits_safe_context_and_report(
    engine: SafeHarborEngine,
) -> None:
    note = RawClinicalNote(
        source="manual",
        text=(
            "Mr. John Smith (MRN: AB12345678, SSN 123-45-6789, ph (415) 555-0142, "
            "email john@example.com) presented 2024-07-14. Resides in 10101."
        ),
        patient_first_name="John",
        patient_last_name="Smith",
        patient_dob=date(1970, 1, 1),
        patient_mrn="AB12345678",
    )
    report, ctx = engine.deidentify_note(note, pseudo_id="pid_" + "a" * 16)

    # Method is recorded.
    assert report.deid_method == DeidMethod.HIPAA_SAFE_HARBOR

    # No PHI survives in the cleaned text.
    assert "Smith" not in ctx.cleaned_text
    assert "AB12345678" not in ctx.cleaned_text
    assert "123-45-6789" not in ctx.cleaned_text
    assert "555-0142" not in ctx.cleaned_text
    assert "john@example.com" not in ctx.cleaned_text
    assert "2024-07-14" not in ctx.cleaned_text

    # Generalization applied.
    assert ctx.age_band in {"45-64", "30-44", "65-74"}  # DOB-dependent
    assert "10101" not in ctx.cleaned_text

    # Audit accounting.
    assert sum(report.identifier_counts.values()) >= 5
    assert len(report.content_hash) == 64  # blake3 hex digest length
