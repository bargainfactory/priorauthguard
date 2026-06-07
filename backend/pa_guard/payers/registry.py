"""PayerAdapterRegistry — pick the right `SubmissionAdapter` per `payer_id`.

How adapters are resolved
-------------------------
1. The caller hands in a `payer_id` (e.g. "anthem", "uhc", "cms-medicare",
   "ohip", "nhs-england").
2. The registry consults `PAYER_TO_ADAPTER` (data) to find the preferred
   channel + adapter family.
3. If the corresponding adapter was registered AND has credentials, return it.
4. Otherwise, fall back to the deterministic `StubAdapter` so the pipeline
   continues to work end-to-end in dev / CI / sandboxed environments.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..agents.submission import StubAdapter, SubmissionAdapter
from ..core.config import Settings, get_settings
from ..core.models import SubmissionChannel

# ---------------------------------------------------------------------------
# Static payer table — adding a payer is a one-line change here.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PayerRoute:
    payer_id: str
    family: str               # "availity" | "covermymeds" | "surescripts" | "fax" | "nhs"
    preferred_channel: SubmissionChannel


PAYER_TO_ADAPTER: tuple[PayerRoute, ...] = (
    # US commercial — mostly behind Availity's multi-payer API.
    PayerRoute("anthem",        "availity",     SubmissionChannel.API),
    PayerRoute("uhc",           "availity",     SubmissionChannel.API),
    PayerRoute("aetna",         "availity",     SubmissionChannel.API),
    PayerRoute("cigna",         "availity",     SubmissionChannel.API),
    PayerRoute("bcbs",          "availity",     SubmissionChannel.API),
    PayerRoute("humana",        "availity",     SubmissionChannel.API),

    # US gov / public payers — direct portals or CoverMyMeds.
    PayerRoute("cms-medicare",  "covermymeds",  SubmissionChannel.API),
    PayerRoute("medicaid",      "covermymeds",  SubmissionChannel.API),
    PayerRoute("tricare",       "covermymeds",  SubmissionChannel.API),

    # Pharmacy / specialty PA via Surescripts.
    PayerRoute("specialty",     "surescripts",  SubmissionChannel.API),

    # Canadian / UK provincial payers — most don't have public APIs yet;
    # the deterministic stub keeps the flow correct, the channel reflects
    # the realistic operational mode (portal upload + fax fallback).
    PayerRoute("ohip",          "fax",          SubmissionChannel.PORTAL),
    PayerRoute("ramq",          "fax",          SubmissionChannel.PORTAL),
    PayerRoute("nhs-england",   "nhs",          SubmissionChannel.PORTAL),
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class PayerAdapterRegistry:
    """Lazily-built family → adapter map.

    Adapters are constructed once and reused. Each adapter's `__init__`
    enforces its own credential / config requirements; a `RuntimeError` from
    an adapter constructor is treated as "not available, fall back to stub".
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._family_cache: dict[str, SubmissionAdapter | None] = {}
        # Stub always available — never depends on settings.
        self._stub = StubAdapter()

    # ------------------------------------------------------------------

    def resolve(self, payer_id: str) -> tuple[SubmissionAdapter, SubmissionChannel]:
        route = _route_for(payer_id)
        adapter = self._resolve_family(route.family)
        return adapter or self._stub, route.preferred_channel

    # ------------------------------------------------------------------

    def _resolve_family(self, family: str) -> SubmissionAdapter | None:
        if family in self._family_cache:
            return self._family_cache[family]

        adapter: SubmissionAdapter | None
        try:
            adapter = self._build_family(family)
        except RuntimeError:
            # Credentials missing; fall through to the stub.
            adapter = None
        self._family_cache[family] = adapter
        return adapter

    def _build_family(self, family: str) -> SubmissionAdapter | None:
        # Lazy imports so the optional `httpx` / `xmltodict` payloads only
        # cost on registries that actually use them.
        if family == "availity":
            from .availity import AvailityAdapter

            return AvailityAdapter(self._settings)
        if family == "covermymeds":
            from .covermymeds import CoverMyMedsAdapter

            return CoverMyMedsAdapter(self._settings)
        if family == "surescripts":
            from .surescripts import SurescriptsAdapter

            return SurescriptsAdapter(self._settings)
        if family == "fax":
            from .fax import FaxAdapter

            return FaxAdapter(self._settings)
        if family == "nhs":
            from .nhs import NhsSpineAdapter

            return NhsSpineAdapter(self._settings)
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _route_for(payer_id: str) -> PayerRoute:
    pid = payer_id.lower()
    for r in PAYER_TO_ADAPTER:
        if r.payer_id == pid:
            return r
    # Unknown payer → default to Availity API channel + stub adapter.
    return PayerRoute(pid, "availity", SubmissionChannel.API)


__all__ = ["PAYER_TO_ADAPTER", "PayerAdapterRegistry", "PayerRoute"]
