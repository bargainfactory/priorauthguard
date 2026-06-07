"""FastAPI app — Phase 1 surface.

Adds the full PA lifecycle (the supervisor-driven graph) on top of the
Phase 0 entry points.

Endpoints
---------
Meta
- `GET  /healthz`            liveness
- `GET  /readyz`             readiness (FHE / voice / zk-STARK posture)

Phase 0
- `POST /v1/intake`          run PrivacyGuardian on a raw note (de-id only)
- `POST /v1/fhe/infer`       run a registered FHE circuit (baseline today)

Phase 1
- `POST /v1/pa`              run the full PA pipeline through the supervisor
- `POST /v1/pa/{rid}/appeal` run the denial-appeal subflow for an existing PA
- `POST /v1/voice/dictation` open a one-shot dictation transcription cycle
  (Phase 5 upgrades this to a true WS stream)

PHI considerations
------------------
* `/v1/intake` and `/v1/pa` are the **only** endpoints that accept PHI.
  Both run de-identification inside the request handler; responses never
  contain raw clinical text.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from ..agents.denial_appeal import AppealInput, DenialAppealAgent
from ..agents.meta_improver import MetaImproverAgent
from ..agents.meta_improver_llm import MetaImproverLLM
from ..agents.privacy_guardian import IntakePayload, PrivacyGuardianAgent
from ..agents.supervisor import PASupervisor, SupervisorConfig
from ..core.config import get_settings
from ..core.logging import configure_logging, get_logger
from ..core.models import (
    AppealDocument,
    ComplianceAuditReport,
    DenialReport,
    FHEInferenceRequest,
    FHEInferenceResult,
    ImprovementProposal,
    ImprovementProposalStatus,
    OutcomeAggregate,
    PADocument,
    PARequest,
    PARequestMeta,
    PolicyEvidence,
    RawClinicalNote,
    SubmissionReceipt,
    ZkStarkProof,
)
from ..core.otel import configure_otel
from ..payers.registry import PayerAdapterRegistry
from ..services.fhe_inference import FHEInferenceService
from ..services.zkstark import ZkStarkVerifier
from ..storage.pa_registry import InMemoryPARegistry, PARegistry, SqlPARegistry
from .voice_stream import router as voice_stream_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log = get_logger("api")
    settings = get_settings()
    # OpenTelemetry — no-op when PAG_OTEL_ENABLED is false.
    configure_otel(app=app, settings=settings)
    log.info(
        "api_startup",
        env=settings.environment,
        fhe_enabled=settings.fhe_enabled,
        voice_on_device=settings.voice_on_device_enabled,
        voice_cloud=settings.voice_cloud_enabled,
    )
    # Long-lived singletons.
    app.state.privacy_guardian = PrivacyGuardianAgent()
    app.state.fhe = FHEInferenceService(settings=settings)
    app.state.payer_registry = PayerAdapterRegistry(settings=settings)
    app.state.supervisor = PASupervisor(
        config=SupervisorConfig(),
        # Wire the payer adapter registry into the SubmissionAgent so real
        # adapters are picked when payer credentials are present.
    )
    # The supervisor's SubmissionAgent has its own `_adapters` map; promote
    # the per-payer adapter resolution to the supervisor's submission call.
    _wire_payer_adapters(app.state.supervisor, app.state.payer_registry)

    app.state.appealer = DenialAppealAgent()
    app.state.meta_improver_heuristic = MetaImproverAgent()
    app.state.meta_improver_llm = MetaImproverLLM(settings=settings)
    app.state.zk_verifier = ZkStarkVerifier(settings=settings)

    # PA registry — sql when PAG_PA_REGISTRY_BACKEND=sql, in-memory otherwise.
    pa_registry: PARegistry
    if settings.pa_registry_backend == "sql":
        pa_registry = SqlPARegistry(database_url=settings.database_url)
    else:
        pa_registry = InMemoryPARegistry()
    app.state.pa_registry = pa_registry
    app.state.proposals_registry = {}
    yield
    log.info("api_shutdown")


def _wire_payer_adapters(
    supervisor: PASupervisor, registry: PayerAdapterRegistry
) -> None:
    """Replace the supervisor's stub submission with a payer-aware dispatcher."""
    submission = supervisor.submission
    original_run = submission._run  # type: ignore[attr-defined]

    async def dispatch(payload):  # type: ignore[no-untyped-def]
        payer_id = payload.document.payer_id
        adapter, channel = registry.resolve(payer_id)
        # Mutate adapter map for this single dispatch so the agent's lifecycle
        # / critique path stays intact.
        submission._adapters[channel] = adapter  # type: ignore[attr-defined]
        payload = payload.__class__(
            document=payload.document, preferred_channel=channel
        )
        return await original_run(payload)

    submission._run = dispatch  # type: ignore[attr-defined]


app = FastAPI(
    title="PriorAuthGuard",
    version="0.5.0",
    description="Privacy-first, self-recursive prior authorization platform.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# WebSocket streaming voice (Phase 5).
app.include_router(voice_stream_router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["meta"])
async def readyz() -> dict[str, object]:
    settings = get_settings()
    fhe: FHEInferenceService = app.state.fhe
    return {
        "status": "ok",
        "environment": settings.environment.value
        if hasattr(settings.environment, "value")
        else str(settings.environment),
        "fhe_enabled": settings.fhe_enabled,
        "fhe_circuits": [c.name for c in fhe.list_circuits()],
        "voice_on_device": settings.voice_on_device_enabled,
        "voice_cloud": settings.voice_cloud_enabled,
        "zkstark_enabled": settings.zkstark_enabled,
    }


# ---------------------------------------------------------------------------
# Phase 0 endpoints
# ---------------------------------------------------------------------------

class IntakeRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: RawClinicalNote
    meta: PARequestMeta


@app.post("/v1/intake", response_model=PARequest, tags=["intake"])
async def intake(body: IntakeRequestBody) -> PARequest:
    guardian: PrivacyGuardianAgent = app.state.privacy_guardian
    payload = IntakePayload(note=body.note, meta=body.meta)
    return await guardian.run(request_id=uuid4(), payload=payload)


@app.post("/v1/fhe/infer", response_model=FHEInferenceResult, tags=["fhe"])
async def fhe_infer(req: FHEInferenceRequest) -> FHEInferenceResult:
    fhe: FHEInferenceService = app.state.fhe
    try:
        return await fhe.infer(req)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---------------------------------------------------------------------------
# Phase 1 — full PA lifecycle
# ---------------------------------------------------------------------------

class PARunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: RawClinicalNote
    meta: PARequestMeta


class PARunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    pa_request: PARequest | None = None
    evidence: list[PolicyEvidence] = Field(default_factory=list)
    document: PADocument | None = None
    audit: ComplianceAuditReport | None = None
    receipt: SubmissionReceipt | None = None
    risk_score: FHEInferenceResult | None = None
    proof_id: str | None = None
    needs_human_approval: bool = False
    clarification_questions: list[str] = Field(default_factory=list)


def _resolve_tenant(header: str | None, body_tenant: str) -> str:
    """Tenant resolution rule:

    - If `X-Tenant-Id` is present, it MUST match `meta.tenant_id`; mismatch
      is a 403 to prevent cross-tenant smuggling via the header.
    - If absent, `meta.tenant_id` (default "default") wins.
    """
    if header and header != body_tenant:
        raise HTTPException(
            status_code=403,
            detail="X-Tenant-Id header does not match meta.tenant_id",
        )
    return body_tenant


@app.post("/v1/pa", response_model=PARunResponse, tags=["pa"])
async def run_pa(
    body: PARunRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> PARunResponse:
    tenant_id = _resolve_tenant(x_tenant_id, body.meta.tenant_id)
    supervisor: PASupervisor = app.state.supervisor
    final = await supervisor.run(note=body.note, meta=body.meta)

    response = PARunResponse(
        status=final.get("status", "intake"),
        pa_request=final.get("pa_request"),
        evidence=final.get("evidence", []),
        document=final.get("document"),
        audit=final.get("audit"),
        receipt=final.get("receipt"),
        risk_score=final.get("risk_score"),
        proof_id=final.get("proof_id"),
        needs_human_approval=final.get("needs_human_approval", False),
        clarification_questions=(
            final["clarification"].questions if final.get("clarification") else []
        ),
    )
    # Persist via the v1.0 GA async, tenant-scoped registry.
    if response.pa_request is not None:
        registry: PARegistry = app.state.pa_registry
        await registry.put(
            tenant_id,
            response.pa_request.meta.request_id,
            response.model_dump(mode="json"),
        )
    return response


@app.get("/v1/pa/{rid}", response_model=PARunResponse, tags=["pa"])
async def get_pa(
    rid: UUID,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> PARunResponse:
    tenant_id = x_tenant_id or "default"
    registry: PARegistry = app.state.pa_registry
    cached = await registry.get(tenant_id, rid)
    if cached is None:
        raise HTTPException(status_code=404, detail=f"PA {rid} not found")
    return PARunResponse.model_validate(cached)


@app.get("/v1/pa", response_model=list[PARunResponse], tags=["pa"])
async def list_pa(
    limit: int = 50,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> list[PARunResponse]:
    tenant_id = x_tenant_id or "default"
    registry: PARegistry = app.state.pa_registry
    rows = await registry.list_recent(tenant_id, limit=limit)
    return [PARunResponse.model_validate(r) for r in rows]


class AppealRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    denial: DenialReport
    document: PADocument
    evidence: list[PolicyEvidence] = Field(default_factory=list)


@app.post("/v1/pa/{rid}/appeal", response_model=AppealDocument, tags=["pa"])
async def appeal_pa(rid: UUID, body: AppealRequestBody) -> AppealDocument:
    if body.document.request_id != rid:
        raise HTTPException(
            status_code=400,
            detail="document.request_id does not match path rid",
        )
    appealer: DenialAppealAgent = app.state.appealer
    return await appealer.run(
        request_id=rid,
        payload=AppealInput(
            denial=body.denial,
            document=body.document,
            evidence=body.evidence,
        ),
    )


# ---------------------------------------------------------------------------
# Voice (one-shot dictation)
# ---------------------------------------------------------------------------

class DictationRequest(BaseModel):
    """One-shot dictation: client sends already-transcribed text from its
    on-device Whisper and the server de-identifies it.

    Phase 5 upgrades this to a full WebSocket audio stream + server-side
    on-device Whisper for clients that can't transcribe locally.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    speaker_role: str = "provider"


class DictationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cleaned_text: str
    identifiers_redacted: int


@app.post("/v1/voice/dictation", response_model=DictationResponse, tags=["voice"])
async def voice_dictation(body: DictationRequest) -> DictationResponse:
    from datetime import UTC, datetime

    from ..core.models import VoiceChannel, VoiceTranscriptChunk

    guardian: PrivacyGuardianAgent = app.state.privacy_guardian
    now = datetime.now(UTC)
    chunk = VoiceTranscriptChunk(
        channel=VoiceChannel.ON_DEVICE_WHISPER,
        speaker_role=body.speaker_role,  # type: ignore[arg-type]
        text=body.text,
        started_at=now,
        ended_at=now,
        on_device=True,
    )
    result = await guardian.deidentify_transcript(chunk)
    return DictationResponse(
        cleaned_text=result.cleaned_text,
        identifiers_redacted=sum(result.deid_report.identifier_counts.values()),
    )


# ---------------------------------------------------------------------------
# Phase 2 — outcomes + meta-improvement + zk verification
# ---------------------------------------------------------------------------

@app.get("/v1/outcomes/aggregate", response_model=OutcomeAggregate, tags=["outcomes"])
async def outcomes_aggregate(window_seconds: int = 0) -> OutcomeAggregate:
    supervisor: PASupervisor = app.state.supervisor
    return await supervisor.outcome_logger.aggregate(window_seconds=window_seconds)


@app.post(
    "/v1/meta-improver/proposals",
    response_model=list[ImprovementProposal],
    tags=["meta-improver"],
)
async def meta_improver_propose(
    window_seconds: int = 0,
    backend: str = "heuristic",
) -> list[ImprovementProposal]:
    """Run the MetaImprover on the current outcome aggregate.

    `backend` selects the generator:
      - "heuristic" (default) — deterministic Phase 2 engine.
      - "llm"                 — Anthropic Claude (falls back to heuristic
                                when ANTHROPIC_API_KEY is missing).
    """
    supervisor: PASupervisor = app.state.supervisor
    agg = await supervisor.outcome_logger.aggregate(window_seconds=window_seconds)
    if backend == "llm":
        llm: MetaImproverLLM = app.state.meta_improver_llm
        proposals = await llm.propose(agg)
    else:
        heuristic: MetaImproverAgent = app.state.meta_improver_heuristic
        proposals = heuristic.propose(agg)
    for p in proposals:
        app.state.proposals_registry[str(p.proposal_id)] = p
    return proposals


@app.get(
    "/v1/meta-improver/proposals",
    response_model=list[ImprovementProposal],
    tags=["meta-improver"],
)
async def meta_improver_list() -> list[ImprovementProposal]:
    return list(app.state.proposals_registry.values())


class ProposalDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    approved_by: str


@app.post(
    "/v1/meta-improver/proposals/{proposal_id}/decide",
    response_model=ImprovementProposal,
    tags=["meta-improver"],
)
async def meta_improver_decide(
    proposal_id: UUID, body: ProposalDecisionBody
) -> ImprovementProposal:
    proposal = app.state.proposals_registry.get(str(proposal_id))
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    from datetime import UTC, datetime

    updated = proposal.model_copy(
        update={
            "status": (
                ImprovementProposalStatus.APPROVED
                if body.approve
                else ImprovementProposalStatus.REJECTED
            ),
            "approved_by": body.approved_by if body.approve else None,
            "approved_at": datetime.now(UTC) if body.approve else None,
        }
    )
    app.state.proposals_registry[str(proposal_id)] = updated
    return updated


class ZkVerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool


@app.post("/v1/zkstark/verify", response_model=ZkVerifyResponse, tags=["zkstark"])
async def zkstark_verify(proof: ZkStarkProof) -> ZkVerifyResponse:
    verifier: ZkStarkVerifier = app.state.zk_verifier
    return ZkVerifyResponse(valid=await verifier.verify(proof))
