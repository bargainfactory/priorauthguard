"""Learned NER overlay for Safe Harbor.

The deterministic regex pass (Phase 0) is the audit-grade fallback that must
ALWAYS run; this overlay catches the long tail of free-text PHI that regex
cannot enumerate — full names without a "Mr./Mrs./Dr." title, location names
without numerals, etc.

Architecture
------------
A pluggable `NerBackend` protocol so:

* Phase 1 ships `HeuristicNerBackend`: capitalized-bigram detection with a
  whitelist of clinical vocabulary so common findings ("Coronary Artery
  Disease") are not mistaken for names.
* Phase 2 swaps in a spaCy / Presidio / model-backed backend behind the same
  interface (the regex pass continues to run, with the model layered on top).

Both paths share the same `apply(text)` shape, so the overlay is invisible
to `PrivacyGuardianAgent`.
"""
from __future__ import annotations

import re
from typing import Final, Protocol


class NerBackend(Protocol):
    def detect_names(self, text: str) -> list[tuple[int, int]]:
        """Return list of (start, end) character spans covering detected names."""


# Vocabulary that LOOKS like a name (capitalized) but is clinical / generic.
# Keep this list small and conservative.
_CLINICAL_WHITELIST: Final[frozenset[str]] = frozenset(
    {
        "Coronary", "Artery", "Disease", "Diabetes", "Mellitus", "Hypertension",
        "Atrial", "Fibrillation", "Pulmonary", "Embolism", "Myocardial",
        "Infarction", "Lumbar", "Cervical", "Thoracic", "Spine", "Knee",
        "Hip", "Shoulder", "Anterior", "Posterior", "Lateral", "Medial",
        "Acute", "Chronic", "Bilateral", "Unilateral", "Severe", "Moderate",
        "Mild", "Stage", "Grade", "Type", "Patient", "Doctor", "Physician",
        "Hospital", "Clinic", "Practice", "Insurance", "Plan", "Provider",
        "Member", "Subscriber", "Policy", "Identification", "Number",
        "Diagnosis", "Procedure", "Surgery", "Treatment", "Therapy",
        "Medication", "Prescription", "Anthem", "Aetna", "Cigna", "UHC",
        "United", "Healthcare", "Medicare", "Medicaid", "Tricare",
        "Blue", "Cross", "Shield", "BCBS", "CMS", "FDA", "NIH", "WHO",
        "January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December",
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday", "Sunday",
    }
)


_BIGRAM = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b")


class HeuristicNerBackend:
    """Phase 1 backend — capitalized-bigram with a clinical whitelist."""

    def detect_names(self, text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        for m in _BIGRAM.finditer(text):
            first, second = m.group(1), m.group(2)
            if first in _CLINICAL_WHITELIST or second in _CLINICAL_WHITELIST:
                continue
            spans.append((m.start(), m.end()))
        return spans


class NerDeidOverlay:
    """Layered on top of the regex pass — adds NAME redactions only."""

    REDACTION_TOKEN: Final = "[REDACTED-NAME]"  # noqa: S105 — not a secret

    def __init__(self, backend: NerBackend | None = None) -> None:
        self._backend = backend or HeuristicNerBackend()

    def apply(self, text: str) -> tuple[str, int]:
        """Returns (cleaned_text, number_of_name_redactions_added)."""
        spans = self._backend.detect_names(text)
        if not spans:
            return text, 0
        # Apply right-to-left so earlier offsets stay valid.
        for start, end in sorted(spans, key=lambda s: s[0], reverse=True):
            text = text[:start] + self.REDACTION_TOKEN + text[end:]
        return text, len(spans)


__all__ = ["HeuristicNerBackend", "NerBackend", "NerDeidOverlay"]
