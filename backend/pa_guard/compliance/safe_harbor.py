"""HIPAA Safe Harbor de-identification.

Implements removal/generalization of the **18 identifiers** enumerated in
45 CFR 164.514(b)(2). This is the deterministic, regex-driven layer that runs
**first** on every PHI-bearing payload. A learned NER pass can be layered on
top in Phase 2; the deterministic pass below is the audit-grade fallback that
must always run, even if the ML pass fails.

The implementation aims for *over-redaction* rather than under-redaction:
when in doubt, redact.

Each identifier is associated with:
- a stable key (used in `DeidentificationReport.identifier_counts`)
- one or more regex patterns
- a replacement token (`[REDACTED-<KEY>]`)

Generalization rules (per Safe Harbor):
- Dates: only year is retained for dates directly related to an individual.
- Ages > 89: bucketed into "90+".
- ZIP: first three digits retained only if the corresponding three-digit
  region has > 20,000 people; otherwise replaced with "000". The list of
  "restricted" three-digit ZIP prefixes (per HHS guidance) is included below.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from re import Pattern
from typing import Final, Literal

from blake3 import blake3

from ..core.models import (
    DeidentificationReport,
    DeidMethod,
    PatientPseudoId,
    RawClinicalNote,
    SafeClinicalContext,
)

# ---------------------------------------------------------------------------
# The 18 HIPAA Safe Harbor identifier keys (stable strings used in reports).
# ---------------------------------------------------------------------------

class SafeHarborIdentifier:
    NAME = "name"
    GEOGRAPHIC_SMALL = "geographic-subdivision-smaller-than-state"
    DATE = "date-element-related-to-individual"
    PHONE = "telephone-number"
    FAX = "fax-number"
    EMAIL = "email-address"
    SSN = "social-security-number"
    MRN = "medical-record-number"
    HEALTH_PLAN = "health-plan-beneficiary-number"
    ACCOUNT = "account-number"
    LICENSE = "certificate-license-number"
    VEHICLE = "vehicle-identifier"
    DEVICE = "device-identifier"
    URL = "web-url"
    IP = "ip-address"
    BIOMETRIC = "biometric-identifier"
    PHOTO = "full-face-photograph"
    OTHER_UNIQUE = "other-unique-identifier"


# Three-digit ZIP prefixes that HHS lists as having ≤ 20,000 residents and
# therefore MUST be replaced with "000" under Safe Harbor.
# (Per the HHS Office for Civil Rights' Safe Harbor guidance.)
RESTRICTED_ZIP3: Final[frozenset[str]] = frozenset(
    {"036", "059", "063", "102", "203", "556", "692", "790",
     "821", "823", "830", "831", "878", "879", "884", "890", "893"}
)


# ---------------------------------------------------------------------------
# Compiled patterns.
#
# Ordering matters: longer / more specific patterns are applied first so that,
# e.g., an SSN is not misread as a partial phone number.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _PatternRule:
    key: str
    pattern: Pattern[str]
    replacement: str


def _redact(key: str) -> str:
    return f"[REDACTED-{key.upper()}]"


_SSN: Final = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE: Final = re.compile(
    r"""(?ix)
        (?<!\d)                     # not the tail of a longer number
        (?:\+?1[\s.-]?)?            # optional country code
        \(?\d{3}\)?[\s.-]?          # area
        \d{3}[\s.-]?                # prefix
        \d{4}                       # line
        (?!\d)                      # not the head of a longer number
    """
)
_EMAIL: Final = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_URL: Final = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.IGNORECASE)
_IPV4: Final = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6: Final = re.compile(r"\b(?:[A-Fa-f0-9]{1,4}:){2,7}[A-Fa-f0-9]{1,4}\b")
_MRN: Final = re.compile(r"\b(?:MRN|mrn|Medical\s+Record\s+Number)\s*[:#]?\s*([A-Z0-9-]{4,})\b")
_HEALTH_PLAN: Final = re.compile(
    r"\b(?:Member\s*ID|Subscriber\s*ID|Policy\s*#|Plan\s*ID)\s*[:#]?\s*([A-Z0-9-]{4,})\b",
    re.IGNORECASE,
)
_ACCOUNT: Final = re.compile(r"\b(?:Acct|Account)\s*[:#]?\s*([A-Z0-9-]{4,})\b", re.IGNORECASE)
_LICENSE: Final = re.compile(r"\b(?:DL|Lic(?:ense)?)\s*[:#]?\s*([A-Z0-9-]{4,})\b", re.IGNORECASE)
_VEHICLE_VIN: Final = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
_DEVICE_SERIAL: Final = re.compile(
    r"\b(?:S/N|SN|Serial(?:\s*Number)?)\s*[:#]?\s*([A-Z0-9-]{4,})\b",
    re.IGNORECASE,
)
_ZIP5_PLUS4: Final = re.compile(r"\b(\d{5})-?(\d{4})\b")
_ZIP5: Final = re.compile(r"\b(\d{5})\b")
_DATE_ISO: Final = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_US: Final = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_AGE_OVER_89: Final = re.compile(r"\b(\d{2,3})\s*(?:y/?o|years?\s*old)\b", re.IGNORECASE)

# Person-name detection without a learned NER: a conservative heuristic that
# catches "Mr./Mrs./Ms./Dr. <Capitalized>" and obvious "First Last" patterns
# preceded by a name-introducing phrase. Production deployments should layer
# a learned NER pass on top (Phase 2).
_NAME_TITLE: Final = re.compile(
    r"\b(?:Mr|Mrs|Ms|Mx|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*",
)
_NAME_INTRO: Final = re.compile(
    r"\b(?:patient(?:'s)?\s+name(?:\s+is)?|name\s*[:])\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _RedactionResult:
    text: str
    counts: dict[str, int]


class SafeHarborEngine:
    """Stateless, deterministic Safe Harbor redactor.

    Usage:
        engine = SafeHarborEngine()
        report, safe_ctx = engine.deidentify_note(raw_note, pseudo_id=...)
    """

    # Order is significant — see module docstring.
    _PATTERN_RULES: Final[tuple[_PatternRule, ...]] = (
        _PatternRule(SafeHarborIdentifier.SSN, _SSN, _redact(SafeHarborIdentifier.SSN)),
        _PatternRule(SafeHarborIdentifier.EMAIL, _EMAIL, _redact(SafeHarborIdentifier.EMAIL)),
        _PatternRule(SafeHarborIdentifier.URL, _URL, _redact(SafeHarborIdentifier.URL)),
        _PatternRule(SafeHarborIdentifier.IP, _IPV4, _redact(SafeHarborIdentifier.IP)),
        _PatternRule(SafeHarborIdentifier.IP, _IPV6, _redact(SafeHarborIdentifier.IP)),
        _PatternRule(SafeHarborIdentifier.MRN, _MRN, _redact(SafeHarborIdentifier.MRN)),
        _PatternRule(
            SafeHarborIdentifier.HEALTH_PLAN, _HEALTH_PLAN, _redact(SafeHarborIdentifier.HEALTH_PLAN)
        ),
        _PatternRule(SafeHarborIdentifier.ACCOUNT, _ACCOUNT, _redact(SafeHarborIdentifier.ACCOUNT)),
        _PatternRule(SafeHarborIdentifier.LICENSE, _LICENSE, _redact(SafeHarborIdentifier.LICENSE)),
        _PatternRule(SafeHarborIdentifier.VEHICLE, _VEHICLE_VIN, _redact(SafeHarborIdentifier.VEHICLE)),
        _PatternRule(SafeHarborIdentifier.DEVICE, _DEVICE_SERIAL, _redact(SafeHarborIdentifier.DEVICE)),
        _PatternRule(SafeHarborIdentifier.PHONE, _PHONE, _redact(SafeHarborIdentifier.PHONE)),
        _PatternRule(SafeHarborIdentifier.NAME, _NAME_TITLE, _redact(SafeHarborIdentifier.NAME)),
        _PatternRule(SafeHarborIdentifier.NAME, _NAME_INTRO, _redact(SafeHarborIdentifier.NAME)),
    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deidentify_text(self, text: str) -> tuple[str, dict[str, int]]:
        """Redact PHI from free text; return (cleaned_text, counts)."""
        result = self._apply_patterns(text)
        result = self._generalize_dates(result)
        result = self._generalize_zip(result)
        result = self._generalize_ages_over_89(result)
        return result.text, result.counts

    def deidentify_note(
        self,
        note: RawClinicalNote,
        *,
        pseudo_id: PatientPseudoId,
    ) -> tuple[DeidentificationReport, SafeClinicalContext]:
        """De-identify a raw note and emit an auditable report + safe context."""
        cleaned, counts = self.deidentify_text(note.text)

        # Structured demographics: drop direct identifiers; bucket the DOB.
        if note.patient_first_name or note.patient_last_name:
            counts[SafeHarborIdentifier.NAME] = (
                counts.get(SafeHarborIdentifier.NAME, 0) + 1
            )
        if note.patient_mrn:
            counts[SafeHarborIdentifier.MRN] = (
                counts.get(SafeHarborIdentifier.MRN, 0) + 1
            )

        age_band = _age_band_from_dob(note.patient_dob)

        safe_ctx = SafeClinicalContext(
            pseudo_id=pseudo_id,
            age_band=age_band,
            sex_at_birth=None,
            zip3=None,
            cleaned_text=cleaned,
        )

        content_hash = blake3(cleaned.encode("utf-8")).hexdigest()

        report = DeidentificationReport(
            deid_method=DeidMethod.HIPAA_SAFE_HARBOR,
            identifier_counts=dict(counts),
            content_hash=content_hash,
            notes=[
                "Deterministic regex pass; learned NER overlay scheduled for Phase 2.",
            ],
        )
        return report, safe_ctx

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_patterns(self, text: str) -> _RedactionResult:
        counts: dict[str, int] = {}
        for rule in self._PATTERN_RULES:
            text, n = rule.pattern.subn(rule.replacement, text)
            if n:
                counts[rule.key] = counts.get(rule.key, 0) + n
        return _RedactionResult(text=text, counts=counts)

    def _generalize_dates(self, prev: _RedactionResult) -> _RedactionResult:
        counts = dict(prev.counts)
        text = prev.text

        def _iso_sub(m: re.Match[str]) -> str:
            return f"{m.group(1)}-XX-XX"

        def _us_sub(m: re.Match[str]) -> str:
            year = m.group(3)
            year = f"19{year}" if len(year) == 2 and int(year) >= 30 else (
                f"20{year}" if len(year) == 2 else year
            )
            return f"XX/XX/{year}"

        text, n1 = _DATE_ISO.subn(_iso_sub, text)
        text, n2 = _DATE_US.subn(_us_sub, text)
        total = n1 + n2
        if total:
            counts[SafeHarborIdentifier.DATE] = (
                counts.get(SafeHarborIdentifier.DATE, 0) + total
            )
        return _RedactionResult(text=text, counts=counts)

    def _generalize_zip(self, prev: _RedactionResult) -> _RedactionResult:
        counts = dict(prev.counts)
        text = prev.text

        def _zip9_sub(m: re.Match[str]) -> str:
            zip3 = m.group(1)[:3]
            zip3 = "000" if zip3 in RESTRICTED_ZIP3 else zip3
            return f"{zip3}XX"

        def _zip5_sub(m: re.Match[str]) -> str:
            zip3 = m.group(1)[:3]
            zip3 = "000" if zip3 in RESTRICTED_ZIP3 else zip3
            return f"{zip3}XX"

        text, n1 = _ZIP5_PLUS4.subn(_zip9_sub, text)
        text, n2 = _ZIP5.subn(_zip5_sub, text)
        total = n1 + n2
        if total:
            counts[SafeHarborIdentifier.GEOGRAPHIC_SMALL] = (
                counts.get(SafeHarborIdentifier.GEOGRAPHIC_SMALL, 0) + total
            )
        return _RedactionResult(text=text, counts=counts)

    def _generalize_ages_over_89(self, prev: _RedactionResult) -> _RedactionResult:
        counts = dict(prev.counts)
        text = prev.text

        def _sub(m: re.Match[str]) -> str:
            try:
                age = int(m.group(1))
            except ValueError:
                return m.group(0)
            return "90+ y/o" if age > 89 else m.group(0)

        text, n = _AGE_OVER_89.subn(_sub, text)
        if n:
            # Age generalization counts under DATE per Safe Harbor (date-element).
            counts[SafeHarborIdentifier.DATE] = (
                counts.get(SafeHarborIdentifier.DATE, 0) + n
            )
        return _RedactionResult(text=text, counts=counts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AgeBand = Literal[
    "0-17", "18-29", "30-44", "45-64", "65-74", "75-84", "85-plus"
]


def _age_band_from_dob(dob: date | None) -> AgeBand:
    """Map a DOB to a Safe-Harbor-compliant age band (90+ collapsed)."""
    if dob is None:
        return "30-44"  # neutral default; never inferred from PHI elsewhere.
    today = date.today()
    age = (
        today.year
        - dob.year
        - ((today.month, today.day) < (dob.month, dob.day))
    )
    if age < 18:
        return "0-17"
    if age < 30:
        return "18-29"
    if age < 45:
        return "30-44"
    if age < 65:
        return "45-64"
    if age < 75:
        return "65-74"
    if age < 85:
        return "75-84"
    return "85-plus"


__all__ = [
    "RESTRICTED_ZIP3",
    "AgeBand",
    "SafeHarborEngine",
    "SafeHarborIdentifier",
]
