"""Rule packs that the ComplianceEngine evaluates against each PA request.

A rule is **declarative**: it describes *what* must be true, not *how* to make
it true. The engine looks at every applicable rule, evaluates its predicate
against the (PARequest, PADocument) pair, and emits findings.

Severity model
--------------
- `info`     informational; never blocks submission.
- `warning`  must be acknowledged but never blocks submission.
- `blocker`  prevents submission until resolved.

Adding a rule
-------------
1. Append a `Rule(...)` to the appropriate pack below.
2. Register the pack in `RULE_PACKS_BY_JURISDICTION`.
3. Add at least one positive + one negative test in `tests/test_compliance.py`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from ..core.config import Jurisdiction
from ..core.models import (
    ClinicalCriterionStatus,
    PADocument,
    PARequest,
)

Severity = Literal["info", "warning", "blocker"]


@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: Severity
    description: str
    predicate: Callable[[PARequest, PADocument | None], bool]
    """Returns True when the rule HOLDS. False → finding emitted."""


# ---------------------------------------------------------------------------
# Predicate helpers (used to keep individual rules one-liners)
# ---------------------------------------------------------------------------

def _has_procedure_code(req: PARequest, _doc: PADocument | None) -> bool:
    return bool(req.meta.procedure_code)


def _has_at_least_one_diagnosis(req: PARequest, _doc: PADocument | None) -> bool:
    return bool(req.meta.diagnosis_codes)


def _safe_context_not_empty(req: PARequest, _doc: PADocument | None) -> bool:
    return bool(req.safe_context.cleaned_text.strip())


def _document_has_narrative(req: PARequest, doc: PADocument | None) -> bool:
    return bool(doc and doc.medical_necessity_narrative.strip())


def _document_addresses_at_least_one_criterion(
    req: PARequest, doc: PADocument | None
) -> bool:
    return bool(doc and doc.criteria)


def _no_criterion_left_unknown(req: PARequest, doc: PADocument | None) -> bool:
    if doc is None:
        return True
    return all(
        c.status != ClinicalCriterionStatus.UNKNOWN.value
        and c.status != ClinicalCriterionStatus.UNKNOWN
        for c in doc.criteria
    )


def _document_has_citations(req: PARequest, doc: PADocument | None) -> bool:
    return bool(doc and doc.citations)


def _urgent_has_dedicated_narrative(req: PARequest, doc: PADocument | None) -> bool:
    urgency = req.meta.urgency
    if urgency not in {"urgent", "emergent"}:
        return True
    if doc is None:
        return False
    return "urgent" in doc.medical_necessity_narrative.lower() or "emergent" in doc.medical_necessity_narrative.lower()


# ---------------------------------------------------------------------------
# Universal pack — applies to every jurisdiction.
# ---------------------------------------------------------------------------

UNIVERSAL_RULES: Final[tuple[Rule, ...]] = (
    Rule("UNIV-001", "blocker",
         "Procedure code is required.",
         _has_procedure_code),
    Rule("UNIV-002", "blocker",
         "At least one diagnosis code is required.",
         _has_at_least_one_diagnosis),
    Rule("UNIV-003", "blocker",
         "De-identified clinical context must not be empty.",
         _safe_context_not_empty),
    Rule("UNIV-004", "blocker",
         "Document must include a medical-necessity narrative.",
         _document_has_narrative),
    Rule("UNIV-005", "warning",
         "Document should address at least one clinical criterion.",
         _document_addresses_at_least_one_criterion),
    Rule("UNIV-006", "warning",
         "Every clinical criterion should have a determined status (met or not-met).",
         _no_criterion_left_unknown),
    Rule("UNIV-007", "warning",
         "Document should cite at least one policy evidence record.",
         _document_has_citations),
    Rule("UNIV-008", "blocker",
         "Urgent/emergent requests must call out urgency in the narrative.",
         _urgent_has_dedicated_narrative),
)


# ---------------------------------------------------------------------------
# US federal pack (HIPAA + CMS-0057-F PA timelines)
# ---------------------------------------------------------------------------

def _cms0057_standard_within_window(req: PARequest, _doc: PADocument | None) -> bool:
    """CMS-0057-F: standard PA decisions within 7 days, expedited within 72h.

    We can't verify the *response* here; what we CAN verify is the request was
    correctly tagged with the urgency that drives those SLAs.
    """
    return req.meta.urgency in {"routine", "urgent", "emergent"}


US_FEDERAL_RULES: Final[tuple[Rule, ...]] = (
    Rule("US-FED-001", "info",
         "Subject to CMS-0057-F prior-authorization timelines (standard 7d / expedited 72h).",
         _cms0057_standard_within_window),
)


# ---------------------------------------------------------------------------
# US state-specific rules (example: CA, TX, NY).
#
# A real production deployment iteratively fills out per-state rules;
# we ship a representative slice that the engine plumbing exercises end-to-end.
# Missing entries fall back to the universal + US-federal pack.
# ---------------------------------------------------------------------------

def _ca_gold_card(req: PARequest, _doc: PADocument | None) -> bool:
    # SB 999 / "gold card" pathway: providers with >90% historical approval
    # on this code are exempt. Without that history here, we just note it.
    return True


def _tx_silver_card(req: PARequest, _doc: PADocument | None) -> bool:
    # TX HB 3459 ("gold card"): similar provider-history exemption.
    return True


def _ny_pa_modernization(req: PARequest, _doc: PADocument | None) -> bool:
    # NY S.3400-A: PA volume reporting / step therapy exemption acknowledgement.
    return True


US_STATE_RULES: Final[dict[str, tuple[Rule, ...]]] = {
    "CA": (
        Rule("US-CA-001", "info",
             "California SB 999 gold-card exemption may apply.",
             _ca_gold_card),
    ),
    "TX": (
        Rule("US-TX-001", "info",
             "Texas HB 3459 gold-card exemption may apply.",
             _tx_silver_card),
    ),
    "NY": (
        Rule("US-NY-001", "info",
             "Subject to NY S.3400-A PA modernization disclosures.",
             _ny_pa_modernization),
    ),
}


# ---------------------------------------------------------------------------
# Canadian rule packs (federal + a representative provincial slice)
# ---------------------------------------------------------------------------

def _pipeda_consent_evidence(req: PARequest, doc: PADocument | None) -> bool:
    return doc is None or "consent" in doc.medical_necessity_narrative.lower() or True


def _quebec_law25_data_residency(req: PARequest, _doc: PADocument | None) -> bool:
    # Law 25: cross-border PHI transfers require an impact assessment. The
    # platform default is to keep QC PHI in-province; we surface the rule.
    return True


CA_FEDERAL_RULES: Final[tuple[Rule, ...]] = (
    Rule("CA-FED-001", "info",
         "PIPEDA consent obligations apply.",
         _pipeda_consent_evidence),
)

CA_PROVINCE_RULES: Final[dict[str, tuple[Rule, ...]]] = {
    "QC": (
        Rule("CA-QC-001", "info",
             "Quebec Law 25 cross-border data-transfer rules apply.",
             _quebec_law25_data_residency),
    ),
    "ON": (
        Rule("CA-ON-001", "info",
             "Ontario PHIPA agent-of-the-HIC obligations apply.",
             lambda r, d: True),
    ),
    "BC": (
        Rule("CA-BC-001", "info",
             "BC PIPA + PHIA obligations apply; data residency preference.",
             lambda r, d: True),
    ),
}


# ---------------------------------------------------------------------------
# UK rule pack (UK-GDPR + DPA 2018 + NHS DSPT)
# ---------------------------------------------------------------------------

def _uk_gdpr_lawful_basis(req: PARequest, doc: PADocument | None) -> bool:
    # Lawful basis for processing PHI must be documented; default is met by
    # treatment necessity (Article 9(2)(h)). We surface as info.
    return True


UK_RULES: Final[tuple[Rule, ...]] = (
    Rule("UK-001", "info",
         "UK-GDPR Article 9(2)(h) treatment-necessity basis assumed.",
         _uk_gdpr_lawful_basis),
    Rule("UK-002", "info",
         "NHS DSPT controls required for any NHS payer.",
         lambda r, d: True),
)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RulePackResolution:
    universal: tuple[Rule, ...]
    federal: tuple[Rule, ...]
    sub: tuple[Rule, ...]

    def all_rules(self) -> tuple[Rule, ...]:
        return (*self.universal, *self.federal, *self.sub)


def resolve_rules(
    jurisdiction: Jurisdiction,
    *,
    state_code: str | None = None,
    province_code: str | None = None,
) -> RulePackResolution:
    """Resolve every rule that applies to the given jurisdiction tag."""
    federal: tuple[Rule, ...] = ()
    sub: tuple[Rule, ...] = ()

    if jurisdiction == Jurisdiction.US_FEDERAL:
        federal = US_FEDERAL_RULES
    elif jurisdiction == Jurisdiction.US_STATE:
        federal = US_FEDERAL_RULES
        if state_code:
            sub = US_STATE_RULES.get(state_code.upper(), ())
    elif jurisdiction == Jurisdiction.CA_FEDERAL:
        federal = CA_FEDERAL_RULES
    elif jurisdiction == Jurisdiction.CA_PROVINCE:
        federal = CA_FEDERAL_RULES
        if province_code:
            sub = CA_PROVINCE_RULES.get(province_code.upper(), ())
    elif jurisdiction == Jurisdiction.UK:
        federal = UK_RULES

    return RulePackResolution(universal=UNIVERSAL_RULES, federal=federal, sub=sub)


__all__ = [
    "CA_FEDERAL_RULES",
    "CA_PROVINCE_RULES",
    "UK_RULES",
    "UNIVERSAL_RULES",
    "US_FEDERAL_RULES",
    "US_STATE_RULES",
    "Rule",
    "RulePackResolution",
    "Severity",
    "resolve_rules",
]
