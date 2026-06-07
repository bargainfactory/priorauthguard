"""FastAPI app — Phase 0 surface.

Exposes:
- `GET  /healthz`            liveness
- `GET  /readyz`             readiness (lists FHE circuits, voice channels)
- `POST /v1/intake`          run a raw clinical note through PrivacyGuardian
- `POST /v1/fhe/infer`       run a registered FHE circuit (baseline in Phase 0)

PHI considerations
------------------
* `/v1/intake` is the **only** endpoint that accepts PHI-bearing payloads.
  The raw note is de-identified inside the request handler and dropped from
  memory before the response is built. The response NEVER contains the raw
  note text — only the de-identified `cleaned_text` and the audit report.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from ..agents.privacy_guardian import IntakePayload, PrivacyGuardianAgent
from ..core.config import get_settings
from ..core.logging import configure_logging, get_logger
from ..core.models import (
    FHEInferenceRequest,
    FHEInferenceResult,
    PARequest,
    PARequestMeta,
    RawClinicalNote,
)
from ..services.fhe_inference import FHEInferenceService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log = get_logger("api")
    settings = get_settings()
    log.info(
        "api_startup",
        env=settings.environment,
        fhe_enabled=settings.fhe_enabled,
        voice_on_device=settings.voice_on_device_enabled,
        voice_cloud=settings.voice_cloud_enabled,
    )
    app.state.privacy_guardian = PrivacyGuardianAgent()
    app.state.fhe = FHEInferenceService(settings=settings)
    yield
    log.info("api_shutdown")


app = FastAPI(
    title="PriorAuthGuard",
    version="0.1.0",
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
# Intake
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


# ---------------------------------------------------------------------------
# FHE inference
# ---------------------------------------------------------------------------

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
