"""Payer sandbox smoke test.

Pings each adapter that has credentials configured. Useful during payer
onboarding to confirm:

  - The base URL is reachable.
  - The credentials authenticate.
  - The de-identified `PADocument` shape is accepted.

The script does NOT use any PHI — the synthetic document is a stand-in.
It reads `PAG_*` env vars exactly like the running server, so a single
`.env` file documents the connection.

Usage:

    # Point at the sandbox URLs first.
    export PAG_PAYER_SANDBOX_MODE=true
    export PAG_AVAILITY_CLIENT_ID=...
    export PAG_AVAILITY_CLIENT_SECRET=...
    export PAG_AVAILITY_BASE_URL=https://apis-sandbox.availity.com
    python -m pa_guard.scripts.payer_smoke_test

Exit code is 0 only if every configured adapter returned a 2xx.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import uuid4

from pa_guard.core.config import Settings, get_settings
from pa_guard.core.logging import configure_logging, get_logger
from pa_guard.core.models import (
    ClinicalCriterion,
    ClinicalCriterionStatus,
    PADocument,
    SubmissionReceipt,
)


def _document(payer_id: str, procedure: str = "64483") -> PADocument:
    """Synthetic, de-identified document.

    Mirrors a real submission shape — the smoke test exercises the same
    wire we'd send for a routine PA.
    """
    return PADocument(
        request_id=uuid4(),
        payer_id=payer_id,
        procedure_code=procedure,
        diagnosis_codes=["M54.16"],
        medical_necessity_narrative=(
            "Smoke-test document; clinical narrative omitted. "
            "Conservative therapy >= 6 weeks documented."
        ),
        criteria=[
            ClinicalCriterion(
                label="conservative therapy",
                status=ClinicalCriterionStatus.MET,
                rationale="Documented PT + NSAIDs over 6 weeks.",
                evidence_ids=[uuid4()],
            )
        ],
        citations=[uuid4()],
    )


async def _ping_availity(settings: Settings) -> SubmissionReceipt | None:
    if not (settings.availity_client_id and settings.availity_client_secret):
        return None
    from pa_guard.payers.availity import AvailityAdapter

    return await AvailityAdapter(settings).submit(_document("anthem"))


async def _ping_covermymeds(settings: Settings) -> SubmissionReceipt | None:
    if not settings.covermymeds_api_key:
        return None
    from pa_guard.payers.covermymeds import CoverMyMedsAdapter

    return await CoverMyMedsAdapter(settings).submit(_document("cms-medicare"))


async def _ping_surescripts(settings: Settings) -> SubmissionReceipt | None:
    if not (settings.surescripts_client_id and settings.surescripts_client_secret):
        return None
    from pa_guard.payers.surescripts import SurescriptsAdapter

    return await SurescriptsAdapter(settings).submit(
        _document("specialty", procedure="J1745")
    )


async def _ping_nhs(settings: Settings) -> SubmissionReceipt | None:
    if not settings.nhs_spine_api_key:
        return None
    from pa_guard.payers.nhs import NhsSpineAdapter

    return await NhsSpineAdapter(settings).submit(_document("nhs-england"))


ADAPTERS = {
    "availity": _ping_availity,
    "covermymeds": _ping_covermymeds,
    "surescripts": _ping_surescripts,
    "nhs": _ping_nhs,
}


async def _run(only: list[str]) -> int:
    configure_logging()
    log = get_logger("payer_smoke_test")
    settings = get_settings()
    if not settings.payer_sandbox_mode:
        log.warning(
            "payer_sandbox_mode_off",
            note=(
                "PAG_PAYER_SANDBOX_MODE is false; this script will hit "
                "production URLs unless you also overrode PAG_*_BASE_URL."
            ),
        )
    log.info(
        "smoke_test_starting",
        sandbox=settings.payer_sandbox_mode,
        adapters=only if only else list(ADAPTERS.keys()),
    )

    targets = ADAPTERS if not only else {k: v for k, v in ADAPTERS.items() if k in only}
    if not targets:
        log.error("smoke_test_no_targets", filter=only)
        return 2

    failures: list[str] = []
    skipped: list[str] = []
    for name, fn in targets.items():
        try:
            receipt = await fn(settings)
        except Exception as exc:
            log.error("smoke_test_failed", adapter=name, error=str(exc))
            failures.append(name)
            continue
        if receipt is None:
            log.info("smoke_test_skipped", adapter=name, reason="no credentials")
            skipped.append(name)
            continue
        log.info(
            "smoke_test_ok",
            adapter=name,
            confirmation=receipt.confirmation_code,
            channel=receipt.channel,
        )

    log.info(
        "smoke_test_summary",
        ok=len(targets) - len(failures) - len(skipped),
        failed=failures,
        skipped=skipped,
    )
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        nargs="+",
        choices=list(ADAPTERS.keys()),
        default=[],
        help="Limit to specific adapters (default: all configured).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.only)))


if __name__ == "__main__":
    main()
