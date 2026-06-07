"""Live payer sandbox integration tests.

Each test:

  1. Skips when `PAG_RUN_LIVE_SANDBOX_TESTS` is false or the relevant
     credentials are missing.
  2. Constructs the adapter exactly as the FastAPI lifespan would.
  3. Submits a **synthetic, de-identified** PA document and asserts:
     - The call succeeds (no exception).
     - A `confirmation_code` is returned.
     - The `channel` matches the expected production / sandbox channel.

No PHI is used — the synthetic doc is identical to the one in the
conformance suite. Run with:

    export PAG_RUN_LIVE_SANDBOX_TESTS=true
    export PAG_PAYER_SANDBOX_MODE=true
    export PAG_AVAILITY_CLIENT_ID=...     # and any others
    pytest tests/integration -q
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from pa_guard.core.models import (
    ClinicalCriterion,
    ClinicalCriterionStatus,
    PADocument,
    SubmissionChannel,
)

from .conftest import (
    require_availity_credentials,
    require_covermymeds_credentials,
    require_nhs_credentials,
    require_surescripts_credentials,
)

pytestmark = pytest.mark.live_sandbox


def _synth_document(payer_id: str, procedure: str = "64483") -> PADocument:
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


@pytest.mark.asyncio
async def test_availity_live_sandbox_submission() -> None:
    s = require_availity_credentials()
    from pa_guard.payers.availity import AvailityAdapter

    adapter = AvailityAdapter(s)
    receipt = await adapter.submit(_synth_document("anthem"))
    assert receipt.confirmation_code is not None
    assert receipt.channel == SubmissionChannel.API.value


@pytest.mark.asyncio
async def test_covermymeds_live_sandbox_submission() -> None:
    s = require_covermymeds_credentials()
    from pa_guard.payers.covermymeds import CoverMyMedsAdapter

    adapter = CoverMyMedsAdapter(s)
    receipt = await adapter.submit(_synth_document("cms-medicare"))
    assert receipt.confirmation_code is not None
    assert receipt.channel == SubmissionChannel.API.value


@pytest.mark.asyncio
async def test_surescripts_live_sandbox_submission() -> None:
    s = require_surescripts_credentials()
    from pa_guard.payers.surescripts import SurescriptsAdapter

    adapter = SurescriptsAdapter(s)
    receipt = await adapter.submit(_synth_document("specialty", procedure="J1745"))
    assert receipt.confirmation_code is not None
    assert receipt.channel == SubmissionChannel.API.value


@pytest.mark.asyncio
async def test_nhs_live_sandbox_submission() -> None:
    s = require_nhs_credentials()
    from pa_guard.payers.nhs import NhsSpineAdapter

    adapter = NhsSpineAdapter(s)
    receipt = await adapter.submit(_synth_document("nhs-england"))
    assert receipt.confirmation_code is not None
    assert receipt.channel == SubmissionChannel.PORTAL.value
