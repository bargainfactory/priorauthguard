# Phase 0 — Deliverables, Verification, Privacy Impact

## Deliverables (this commit)

| Area | Path |
|---|---|
| Repo scaffolding + tooling | [`backend/pyproject.toml`](../backend/pyproject.toml), [`.gitignore`](../.gitignore), [`README.md`](../README.md) |
| Settings + structured logging | [`backend/pa_guard/core/config.py`](../backend/pa_guard/core/config.py), [`backend/pa_guard/core/logging.py`](../backend/pa_guard/core/logging.py) |
| Core domain models (Pydantic v2) | [`backend/pa_guard/core/models.py`](../backend/pa_guard/core/models.py) |
| Safe Harbor engine (18 identifiers + generalization) | [`backend/pa_guard/compliance/safe_harbor.py`](../backend/pa_guard/compliance/safe_harbor.py) |
| De-identification service | [`backend/pa_guard/services/deidentification.py`](../backend/pa_guard/services/deidentification.py) |
| Base agent + self-critique | [`backend/pa_guard/agents/base.py`](../backend/pa_guard/agents/base.py) |
| **PrivacyGuardianAgent** (early de-id orchestration) | [`backend/pa_guard/agents/privacy_guardian.py`](../backend/pa_guard/agents/privacy_guardian.py) |
| **FHEInferenceService** (Concrete ML pattern skeleton) | [`backend/pa_guard/services/fhe_inference.py`](../backend/pa_guard/services/fhe_inference.py) |
| zk-STARK prover / verifier skeleton | [`backend/pa_guard/services/zkstark.py`](../backend/pa_guard/services/zkstark.py) |
| **VoiceService** (hybrid on-device + cloud) | [`backend/pa_guard/services/voice_service.py`](../backend/pa_guard/services/voice_service.py) |
| **VoiceOrchestratorAgent** skeleton | [`backend/pa_guard/agents/voice_orchestrator.py`](../backend/pa_guard/agents/voice_orchestrator.py) |
| FastAPI surface (`/healthz`, `/readyz`, `/v1/intake`, `/v1/fhe/infer`) | [`backend/pa_guard/api/main.py`](../backend/pa_guard/api/main.py) |
| Tests (Safe Harbor, PrivacyGuardian, FHE, voice, API smoke) | [`backend/tests/`](../backend/tests/) |
| CI | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) |

## Verification checklist

### Automated tests

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # or .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```

Expected: all tests pass. Privacy regressions in `test_safe_harbor.py` are P0.

### Manual flows

1. **De-identification round-trip**
   ```bash
   uvicorn pa_guard.api.main:app --reload
   curl -sX POST http://127.0.0.1:8080/v1/intake \
     -H 'content-type: application/json' \
     -d '{
       "note": {
         "source": "manual",
         "text": "Mr. John Smith MRN: AB12345678 ph (415) 555-0142.",
         "patient_first_name": "John", "patient_last_name": "Smith"
       },
       "meta": {
         "jurisdiction": {"jurisdiction": "us-state", "state_code": "CA"},
         "payer_id": "anthem-001", "procedure_code": "64483",
         "diagnosis_codes": ["M54.16"], "urgency": "routine"
       }
     }'
   ```
   Confirm: response contains no `Smith`, no MRN, no phone; `deid_method = "hipaa-safe-harbor"`.

2. **FHE baseline inference**
   ```bash
   curl -sX POST http://127.0.0.1:8080/v1/fhe/infer \
     -H 'content-type: application/json' \
     -d '{
       "circuit_name": "denial_risk_v0",
       "features": {"urgency": "urgent", "prior_denials": 2, "missing_docs_count": 1}
     }'
   ```
   Confirm: `fhe_executed = false` (baseline runs in Phase 0); `prediction ∈ [0,1]`;
   `plaintext_baseline_latency_ms` reported.

3. **Readiness reflects FHE/voice posture**
   ```bash
   curl -s http://127.0.0.1:8080/readyz | jq
   ```
   Confirm `fhe_circuits` includes `denial_risk_v0` and voice flags match settings.

### Privacy / FHE / Compliance gates

- [x] No code path persists raw clinical text.
- [x] Logs contain no PHI — only counts, hashes, and de-identification metadata.
- [x] `FHEInferenceService` rejects `SensitivityTier.PHI_RAW`.
- [x] `VoiceOrchestratorAgent` routes every transcript chunk through `PrivacyGuardianAgent` before any persistence step.
- [x] zk-STARK proof structure produced for every voice outcome (stub today, real prover in Phase 2).
- [x] Safe Harbor engine covers all 18 identifiers; ZIP3 restricted list matches HHS guidance.

## Phase 0 → Phase 1 handoff

The following are explicitly **not** in Phase 0 and become the Phase 1 backlog:

1. Full LangGraph supervisor + remaining agents (Intake, PolicyResearcher,
   DocumentGenerator, Submission, DenialAppeal, ComplianceAuditor).
2. RAG corpus loader with pgvector + jurisdiction filters.
3. Compliance engine (US per-state + Canadian per-province + UK rule packs).
4. Full VoiceOrchestrator with real Deepgram / ElevenLabs / Twilio adapters.
5. Learned NER overlay on Safe Harbor (for free-text PHI escape hatches).
