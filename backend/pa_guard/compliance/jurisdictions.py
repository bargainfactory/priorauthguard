"""Per-jurisdiction registries: US (50 states + DC + federal), Canada
(federal + 13 provinces/territories), United Kingdom.

These tables are deliberately data, not branching code. The compliance engine
consults them, so adding a new jurisdiction is a config change, not a refactor.

NOTE: this module is a STATIC fact-table. It does not call out to anything,
log anything, or touch settings. It is safe to import anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from ..core.config import Jurisdiction


@dataclass(frozen=True)
class JurisdictionInfo:
    """Routing facts about one jurisdiction.

    `privacy_frameworks` documents which privacy regimes apply — the compliance
    engine cross-references this with each rule's `applies_under`.
    """

    code: str                       # ISO-style code (CA, ON, GB-ENG, etc.)
    name: str
    parent: Jurisdiction
    privacy_frameworks: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# US — 50 states + DC + federal
# ---------------------------------------------------------------------------

US_STATES: Final[tuple[JurisdictionInfo, ...]] = tuple(
    JurisdictionInfo(
        code=code,
        name=name,
        parent=Jurisdiction.US_STATE,
        privacy_frameworks=("HIPAA",),
    )
    for code, name in [
        ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
        ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"),
        ("DE", "Delaware"), ("DC", "District of Columbia"), ("FL", "Florida"),
        ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"), ("IL", "Illinois"),
        ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"), ("KY", "Kentucky"),
        ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"),
        ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"),
        ("MS", "Mississippi"), ("MO", "Missouri"), ("MT", "Montana"),
        ("NE", "Nebraska"), ("NV", "Nevada"), ("NH", "New Hampshire"),
        ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
        ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"),
        ("OK", "Oklahoma"), ("OR", "Oregon"), ("PA", "Pennsylvania"),
        ("RI", "Rhode Island"), ("SC", "South Carolina"), ("SD", "South Dakota"),
        ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"), ("VT", "Vermont"),
        ("VA", "Virginia"), ("WA", "Washington"), ("WV", "West Virginia"),
        ("WI", "Wisconsin"), ("WY", "Wyoming"),
    ]
)

US_FEDERAL: Final = JurisdictionInfo(
    # ISO 3166-1 alpha-3 to avoid clashing with state code "US" (none) and
    # to disambiguate from per-state entries below.
    code="USA",
    name="United States (federal)",
    parent=Jurisdiction.US_FEDERAL,
    privacy_frameworks=("HIPAA",),
)


# ---------------------------------------------------------------------------
# Canada — federal + 13 provinces/territories
# ---------------------------------------------------------------------------

CA_PROVINCES: Final[tuple[JurisdictionInfo, ...]] = tuple(
    JurisdictionInfo(code=code, name=name, parent=Jurisdiction.CA_PROVINCE, privacy_frameworks=frameworks)
    for code, name, frameworks in [
        ("AB", "Alberta", ("PIPEDA", "HIA")),
        ("BC", "British Columbia", ("PIPEDA", "PIPA-BC")),
        ("MB", "Manitoba", ("PIPEDA", "PHIA-MB")),
        ("NB", "New Brunswick", ("PIPEDA", "PHIPAA-NB")),
        ("NL", "Newfoundland and Labrador", ("PIPEDA", "PHIA-NL")),
        ("NS", "Nova Scotia", ("PIPEDA", "PHIA-NS")),
        ("NT", "Northwest Territories", ("PIPEDA",)),
        ("NU", "Nunavut", ("PIPEDA",)),
        ("ON", "Ontario", ("PIPEDA", "PHIPA-ON")),
        ("PE", "Prince Edward Island", ("PIPEDA", "HIA-PE")),
        ("QC", "Quebec", ("Law-25",)),
        ("SK", "Saskatchewan", ("PIPEDA", "HIPA-SK")),
        ("YT", "Yukon", ("PIPEDA",)),
    ]
)

CA_FEDERAL: Final = JurisdictionInfo(
    # ISO 3166-1 alpha-3 to avoid clashing with California's "CA".
    code="CAN",
    name="Canada (federal)",
    parent=Jurisdiction.CA_FEDERAL,
    privacy_frameworks=("PIPEDA",),
)


# ---------------------------------------------------------------------------
# United Kingdom
# ---------------------------------------------------------------------------

UK_NATIONS: Final[tuple[JurisdictionInfo, ...]] = (
    JurisdictionInfo("GB-ENG", "England", Jurisdiction.UK, ("UK-GDPR", "DPA-2018", "NHS-DSPT")),
    JurisdictionInfo("GB-SCT", "Scotland", Jurisdiction.UK, ("UK-GDPR", "DPA-2018")),
    JurisdictionInfo("GB-WLS", "Wales", Jurisdiction.UK, ("UK-GDPR", "DPA-2018")),
    JurisdictionInfo("GB-NIR", "Northern Ireland", Jurisdiction.UK, ("UK-GDPR", "DPA-2018")),
)


# ---------------------------------------------------------------------------
# Combined registry
# ---------------------------------------------------------------------------

ALL_JURISDICTIONS: Final[dict[str, JurisdictionInfo]] = {
    j.code: j
    for j in (US_FEDERAL, *US_STATES, CA_FEDERAL, *CA_PROVINCES, *UK_NATIONS)
}


def lookup(code: str) -> JurisdictionInfo:
    try:
        return ALL_JURISDICTIONS[code.upper()]
    except KeyError as e:
        raise KeyError(f"Unknown jurisdiction code: {code!r}") from e


__all__ = [
    "ALL_JURISDICTIONS",
    "CA_FEDERAL",
    "CA_PROVINCES",
    "UK_NATIONS",
    "US_FEDERAL",
    "US_STATES",
    "JurisdictionInfo",
    "lookup",
]
