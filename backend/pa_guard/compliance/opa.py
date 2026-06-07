"""OPA / Rego policy engine — org-level compliance overlays.

Per-customer overlays are expressed in OPA's Rego language and evaluated
against the same `(PARequest, PADocument)` pair the built-in rule packs
already see. Findings are merged into the ComplianceEngine output so a
tenant can:

- Add new blockers (e.g., "require PCP attestation for biologics").
- Override severities (e.g., demote a universal warning to info).
- Layer per-payer business rules without forking the codebase.

Network shape
-------------
Default backend is the OPA REST API over HTTP. Production deployments run
OPA as a sidecar (`opa run --server`) so the call is loopback-only. The
implementation falls back to **noop** when:

- `PAG_OPA_URL` is not set, or
- the OPA server returns 404 (no policy bundle loaded for the tenant), or
- the HTTP call raises (timeout / connection refused).

The noop fallback returns no findings — it never blocks submission on
infrastructure failure, only on real policy decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.models import (
    ComplianceFinding,
    PADocument,
    PARequest,
)


@dataclass(frozen=True)
class OpaInput:
    """Wire shape handed to Rego — strictly de-identified."""

    request: dict[str, Any]
    document: dict[str, Any] | None
    tenant_id: str


class OpaPolicyEngine:
    """Async client around the OPA REST API + a noop fallback.

    `transport` is an optional `httpx.BaseTransport` for tests to inject a
    `httpx.MockTransport`. Production callers leave it `None`.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: object | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._log = get_logger("OpaPolicyEngine")
        self._transport = transport

    # ------------------------------------------------------------------

    @property
    def is_enabled(self) -> bool:
        return bool(getattr(self._settings, "opa_url", None))

    async def evaluate(
        self,
        request: PARequest,
        document: PADocument | None,
    ) -> list[ComplianceFinding]:
        if not self.is_enabled:
            return []
        tenant_id = getattr(request.meta, "tenant_id", "default") or "default"
        payload = {
            "input": {
                "request": request.model_dump(mode="json"),
                "document": document.model_dump(mode="json") if document else None,
                "tenant_id": tenant_id,
            }
        }
        try:
            findings = await self._post(tenant_id, payload)
        except Exception as exc:
            self._log.warning("opa_call_failed", error=str(exc), tenant=tenant_id)
            return []
        return [self._to_finding(f) for f in findings if isinstance(f, dict)]

    # ------------------------------------------------------------------

    async def _post(self, tenant_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        import httpx

        url = str(self._settings.opa_url).rstrip("/")
        # Per-tenant package convention: `data.pa_guard.tenants.<tenant_id>.findings`.
        package = f"pa_guard/tenants/{tenant_id}/findings"
        endpoint = f"{url}/v1/data/{package}"

        kwargs: dict[str, Any] = {"timeout": 2.0}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        async with httpx.AsyncClient(**kwargs) as client:
            res = await client.post(endpoint, json=payload)
        if res.status_code == 404:
            # No tenant-specific policy bundle loaded.
            return []
        res.raise_for_status()
        body = res.json()
        result = body.get("result")
        if result is None:
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return list(result.get("findings", [])) if "findings" in result else [result]
        return []

    @staticmethod
    def _to_finding(raw: dict[str, Any]) -> ComplianceFinding:
        severity = str(raw.get("severity", "info"))
        if severity not in {"info", "warning", "blocker"}:
            severity = "info"
        return ComplianceFinding(
            rule_id=str(raw.get("rule_id", "OPA-UNKNOWN")),
            severity=severity,  # type: ignore[arg-type]
            message=str(raw.get("message", "(opa finding)")),
        )


__all__ = ["OpaInput", "OpaPolicyEngine"]
