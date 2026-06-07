"""Learned NER overlay tests."""
from __future__ import annotations

import pytest

from pa_guard.compliance.ner_overlay import NerDeidOverlay

pytestmark = pytest.mark.compliance


def test_overlay_redacts_untitled_capitalized_bigram() -> None:
    overlay = NerDeidOverlay()
    cleaned, added = overlay.apply("Discussed plan with Sarah Connor in clinic.")
    assert "Sarah Connor" not in cleaned
    assert "[REDACTED-NAME]" in cleaned
    assert added == 1


def test_overlay_does_not_redact_clinical_phrases() -> None:
    overlay = NerDeidOverlay()
    text = "Patient has Coronary Artery Disease and Type Two Diabetes Mellitus."
    cleaned, added = overlay.apply(text)
    # These are whitelisted clinical phrases — must be preserved.
    assert "Coronary Artery" in cleaned
    assert "Diabetes Mellitus" in cleaned
    assert added == 0


def test_overlay_handles_no_matches() -> None:
    overlay = NerDeidOverlay()
    cleaned, added = overlay.apply("patient reports back pain.")
    assert added == 0
    assert cleaned == "patient reports back pain."
